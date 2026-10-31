"""Database-coordinated, idempotent ingestion work run by Celery workers."""
import ipaddress
import logging
import socket
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from sqlalchemy import or_, select
from sqlalchemy.orm import sessionmaker
from langchain_core.documents import Document

from db.session import get_engine
from core.config import settings
from models.document import DocumentRecord, DocumentStatus, IngestionJob, IngestionJobStatus
from retrieval import build_bm25_index
from services.rag_indexing import (
    artifact_file, build_index_from_vectors, chunk_record, extract_record,
    get_embeddings, storage_file, write_index_artifact,
)

logger = logging.getLogger(__name__)
GENERIC_FAILURE = "Document processing failed. Check the file or URL and try again."


class PermanentIngestionError(Exception):
    pass


class TransientIngestionError(Exception):
    pass


class _PinnedIPHTTPSAdapter(HTTPAdapter):
    """Connect to the resolved IP while retaining hostname TLS verification/SNI."""
    def __init__(self, hostname: str):
        self.hostname = hostname
        super().__init__(max_retries=0)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["assert_hostname"] = self.hostname
        pool_kwargs["server_hostname"] = self.hostname
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


def _session_factory():
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)


def _mark_failed(job_id: UUID, message: str = GENERIC_FAILURE) -> None:
    with _session_factory()() as db:
        job = db.scalar(select(IngestionJob).where(IngestionJob.id == job_id).with_for_update())
        if job is None:
            return
        doc = db.scalar(select(DocumentRecord).where(DocumentRecord.id == job.document_id).with_for_update())
        if doc is None or doc.status == DocumentStatus.DELETING.value:
            return
        job.status = IngestionJobStatus.FAILED.value
        job.error_message = message
        job.finished_at = datetime.now(timezone.utc)
        doc.status = DocumentStatus.FAILED.value
        doc.error_message = message
        db.commit()


def _defer_retry(job_id: UUID, delay_seconds: int) -> bool:
    with _session_factory()() as db:
        job = db.scalar(select(IngestionJob).where(IngestionJob.id == job_id).with_for_update())
        if job is None:
            return False
        doc = db.scalar(select(DocumentRecord).where(DocumentRecord.id == job.document_id).with_for_update())
        if (doc is None or doc.status != DocumentStatus.PROCESSING.value
                or job.status != IngestionJobStatus.PROCESSING.value):
            return False
        job.status = IngestionJobStatus.QUEUED.value
        job.error_message = None
        job.dispatched_at = None
        job.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        doc.status = DocumentStatus.QUEUED.value
        doc.error_message = None
        db.commit()
        return True


def _load_source(record: DocumentRecord):
    if record.file_type != "url":
        try:
            return extract_record(record)
        except (FileNotFoundError, ValueError, OSError) as exc:
            raise PermanentIngestionError("Uploaded document could not be read") from exc
        except Exception as exc:
            raise PermanentIngestionError("Uploaded document could not be parsed") from exc

    try:
        raw_url = storage_file(record).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PermanentIngestionError("Stored URL could not be read") from exc
    parsed = urlsplit(raw_url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None):
        raise PermanentIngestionError("URL is invalid")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        expected_port = 443 if parsed.scheme == "https" else 80
        if port != expected_port:
            raise PermanentIngestionError("URL port is not allowed")
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        resolved = sorted({ipaddress.ip_address(item[4][0]) for item in addresses}, key=lambda item: (item.version, int(item)))
        if not resolved or any(not address.is_global for address in resolved):
            raise PermanentIngestionError("URL host is not public")

        # Pin the HTTP connection to the checked address so a second DNS lookup
        # cannot rebind the request to localhost/private/link-local infrastructure.
        address = resolved[0]
        ip_host = "[{}]".format(address.compressed) if address.version == 6 else address.compressed
        target = parsed._replace(netloc=ip_host, fragment="").geturl()
        host_header = parsed.hostname
        if parsed.scheme == "https" and port == 443:
            host_header = parsed.hostname
        elif port == 80:
            host_header = parsed.hostname
        headers = {"Host": host_header, "User-Agent": "FinDocAI-DocumentFetcher/1.0", "Accept": "text/html,text/plain,application/xhtml+xml"}
        max_bytes = settings.max_upload_size_bytes
        with requests.Session() as client:
            client.trust_env = False
            if parsed.scheme == "https":
                client.mount("https://", _PinnedIPHTTPSAdapter(parsed.hostname))
            with client.get(target, headers=headers, timeout=(5, 20), allow_redirects=False, stream=True) as response:
                if 300 <= response.status_code < 400:
                    raise PermanentIngestionError("URL redirects are not followed")
                if 400 <= response.status_code < 500:
                    raise PermanentIngestionError("URL returned an unsuccessful response")
                if response.status_code >= 500:
                    raise TransientIngestionError("URL server is temporarily unavailable")
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type and content_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
                    raise PermanentIngestionError("URL did not return a supported text document")
                length_header = response.headers.get("Content-Length")
                if length_header and int(length_header) > max_bytes:
                    raise PermanentIngestionError("URL response exceeds the configured size limit")
                chunks, total, started = [], 0, time.monotonic()
                for block in response.iter_content(chunk_size=64 * 1024):
                    if not block:
                        continue
                    total += len(block)
                    if total > max_bytes or time.monotonic() - started > 30:
                        raise PermanentIngestionError("URL response exceeds configured limits")
                    chunks.append(block)
                raw_html = b"".join(chunks)
                encoding = response.encoding or "utf-8"
        text = raw_html.decode(encoding, errors="replace")
        soup = BeautifulSoup(text, "html.parser")
        for node in soup(("script", "style", "noscript", "iframe", "svg")):
            node.decompose()
        extracted = soup.get_text("\n", strip=True) if "html" in content_type or "xhtml" in content_type else text.strip()
        docs = [Document(page_content=extracted, metadata={"source": record.original_filename})] if extracted else []
    except PermanentIngestionError:
        raise
    except (requests.Timeout, requests.ConnectionError, socket.gaierror) as exc:
        raise TransientIngestionError("URL could not be fetched") from exc
    except Exception as exc:
        raise TransientIngestionError("URL could not be fetched") from exc
    if not docs:
        raise PermanentIngestionError("URL contains no extractable text")
    for doc in docs:
        doc.metadata["source"] = record.original_filename
    return docs


def process_ingestion_job(job_id: str, task=None) -> str:
    parsed_job_id = UUID(job_id)
    attempt_number = 0
    with _session_factory()() as db:
        job = db.scalar(select(IngestionJob).where(IngestionJob.id == parsed_job_id).with_for_update())
        if job is None or job.status in {IngestionJobStatus.COMPLETED.value, IngestionJobStatus.FAILED.value}:
            return "already_finished_or_deleted"
        if task is not None and task.request.id and job.task_id != task.request.id:
            return "stale_task_id"
        record = db.scalar(select(DocumentRecord).where(DocumentRecord.id == job.document_id).with_for_update())
        if record is None or record.status == DocumentStatus.DELETING.value:
            return "deleted"
        if job.owner_id != record.owner_id or record.status not in {
            DocumentStatus.QUEUED.value, DocumentStatus.PROCESSING.value,
        }:
            return "not_active"
        # A recently processing job belongs to another delivery. Celery late-ack
        # redelivery after worker loss is recovered by the outbox lease sweeper.
        if job.status == IngestionJobStatus.PROCESSING.value:
            return "already_processing"
        job.status = IngestionJobStatus.PROCESSING.value
        job.attempt_count += 1
        attempt_number = job.attempt_count
        job.started_at = job.started_at or datetime.now(timezone.utc)
        job.finished_at = None
        job.dispatched_at = job.dispatched_at or datetime.now(timezone.utc)
        job.error_message = None
        record.status = DocumentStatus.PROCESSING.value
        record.error_message = None
        db.commit()
        # Detached ORM state is safe for the pure extraction/chunk identity fields.
        db.refresh(record)

    try:
        # An old artifact must never survive a retry that hasn't completed yet.
        artifact_file(record).unlink(missing_ok=True)
        source_docs = _load_source(record)
        chunks = chunk_record(record, source_docs)
        if not chunks:
            raise PermanentIngestionError("Document contains no searchable text")
        try:
            vectors = get_embeddings().embed_documents([chunk.page_content for chunk in chunks])
            build_index_from_vectors(chunks, vectors, {str(record.id)})
            build_bm25_index(chunks)
        except PermanentIngestionError:
            raise
        except Exception as exc:
            raise TransientIngestionError("Embedding or index construction failed") from exc

        with _session_factory()() as db:
            job = db.scalar(select(IngestionJob).where(IngestionJob.id == parsed_job_id).with_for_update())
            current = db.scalar(select(DocumentRecord).where(DocumentRecord.id == record.id).with_for_update())
            if job is None or current is None or current.status != DocumentStatus.PROCESSING.value:
                artifact_file(record).unlink(missing_ok=True)
                return "deleted_or_superseded"
            if job.status != IngestionJobStatus.PROCESSING.value or current.owner_id != job.owner_id:
                artifact_file(record).unlink(missing_ok=True)
                return "superseded"
            # Persist the searchable artifact before making the DB row visible as
            # completed. The API only indexes completed rows with matching artifacts.
            write_index_artifact(current, chunks, vectors)
            current.status = DocumentStatus.COMPLETED.value
            current.error_message = None
            job.status = IngestionJobStatus.COMPLETED.value
            job.error_message = None
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
        return "completed"
    except PermanentIngestionError:
        logger.error("Permanent document ingestion failure", extra={"job_id": job_id})
        artifact_file(record).unlink(missing_ok=True)
        _mark_failed(parsed_job_id)
        return "failed"
    except Exception as exc:
        logger.error("Transient document ingestion failure", extra={
            "job_id": job_id, "error_type": type(exc).__name__,
        })
        if attempt_number < settings.celery_task_max_retries + 1 and task is not None:
            delay = min(300, 2 ** attempt_number)
            if _defer_retry(parsed_job_id, delay):
                logger.info("Ingestion retry scheduled", extra={
                    "job_id": job_id, "attempt": attempt_number, "retry_delay_seconds": delay,
                })
                return "retry_scheduled"
        artifact_file(record).unlink(missing_ok=True)
        _mark_failed(parsed_job_id)
        return "failed"


def dispatch_outbox() -> int:
    """Dispatch queued durable rows; duplicate sends are safe because jobs are idempotent."""
    from tasks.ingestion import ingest_document

    now = datetime.now(timezone.utc)
    # A task can be accepted by Redis and then lost before the worker claims
    # the database row. Re-dispatch old queued rows; duplicate deliveries are
    # safe because process_ingestion_job locks and transitions the durable job.
    redispatch_before = now - timedelta(seconds=60)
    sent = 0
    with _session_factory()() as db:
        candidates = list(db.scalars(select(IngestionJob).where(
            IngestionJob.status == IngestionJobStatus.QUEUED.value,
            or_(IngestionJob.dispatched_at.is_(None), IngestionJob.dispatched_at <= redispatch_before),
            or_(IngestionJob.next_attempt_at.is_(None), IngestionJob.next_attempt_at <= now),
        ).order_by(IngestionJob.created_at).limit(100).with_for_update(skip_locked=True)).all())
        for job in candidates:
            try:
                ingest_document.apply_async(args=[str(job.id)], task_id=job.task_id)
                job.dispatched_at = now
                job.next_attempt_at = None
                sent += 1
            except Exception as exc:
                logger.warning("Outbox dispatch failed; job remains queued", extra={
                    "job_id": str(job.id), "error_type": type(exc).__name__,
                })
        # Recover jobs lost with a worker after the hard time limit plus margin.
        stale_before = now.timestamp() - max(1200, 2 * settings.celery_task_time_limit)
        stale = list(db.scalars(select(IngestionJob).where(
            IngestionJob.status == IngestionJobStatus.PROCESSING.value,
        ).order_by(IngestionJob.updated_at).limit(50).with_for_update(skip_locked=True)).all())
        for job in stale:
            # A durable retry has already returned this row to queued. Never
            # bypass its backoff deadline when recovering abandoned work.
            updated = job.updated_at
            updated_ts = updated.replace(tzinfo=timezone.utc).timestamp() if updated.tzinfo is None else updated.timestamp()
            if updated_ts >= stale_before:
                continue
            doc = db.scalar(select(DocumentRecord).where(DocumentRecord.id == job.document_id).with_for_update())
            if doc is None or doc.status == DocumentStatus.DELETING.value:
                continue
            if job.attempt_count >= settings.celery_task_max_retries + 1:
                job.status = IngestionJobStatus.FAILED.value
                job.error_message = GENERIC_FAILURE
                job.finished_at = now
                doc.status = DocumentStatus.FAILED.value
                doc.error_message = GENERIC_FAILURE
                continue
            job.status = IngestionJobStatus.QUEUED.value
            job.dispatched_at = None
            job.next_attempt_at = None
            doc.status = DocumentStatus.QUEUED.value
        db.commit()
    return sent
