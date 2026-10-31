"""Owned document persistence, local storage, and shared index lifecycle."""
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile
from langchain_core.documents import Document
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

import state
from core.config import settings
from models.document import (
    DocumentRecord, DocumentStatus, IngestionJob, IngestionJobStatus,
)
from models.conversation import MessageCitation
from models.user import User
from services.rag_indexing import (
    artifact_file, build_index_from_vectors, chunk_record, extract_record,
    get_embeddings, load_index_artifact, storage_file, write_index_artifact,
)

logger = logging.getLogger(__name__)
ALLOWED_UPLOADS = {
    ".pdf": ("pdf", "application/pdf"),
    ".txt": ("txt", "text/plain"),
}


def _storage_root() -> Path:
    root = Path(settings.document_storage_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _safe_original_name(name: str | None) -> str:
    # Strip both POSIX and Windows path components; this value is display metadata only.
    basename = (name or "document").replace("\\", "/").split("/")[-1].strip()
    basename = re.sub(r"[\x00-\x1f]", "", basename)
    return (basename or "document")[:512]


async def _save_upload(upload: UploadFile) -> tuple[str, str, str, int, str]:
    original_name = _safe_original_name(upload.filename)
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_UPLOADS:
        raise HTTPException(status_code=415, detail="Only PDF and TXT files are supported")
    file_type, expected_mime = ALLOWED_UPLOADS[ext]
    supplied_mime = (upload.content_type or "").split(";", 1)[0].strip().lower()
    if supplied_mime != expected_mime:
        raise HTTPException(status_code=415, detail="File type does not match its extension")

    root = _storage_root()
    filename = "{}{}".format(uuid4().hex, ext)
    temp_path = root / (".upload-{}".format(uuid4().hex))
    destination = root / filename
    total = 0
    prefix = bytearray()
    try:
        with temp_path.open("xb") as target:
            os.chmod(temp_path, 0o600)
            while True:
                block = await upload.read(64 * 1024)
                if not block:
                    break
                total += len(block)
                if total > settings.max_upload_size_bytes:
                    raise HTTPException(status_code=413, detail="File exceeds the configured upload size limit")
                if len(prefix) < 1024:
                    prefix.extend(block[: 1024 - len(prefix)])
                target.write(block)
        if total == 0:
            raise HTTPException(status_code=400, detail="File is empty")
        if file_type == "pdf" and not prefix.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="The uploaded file is not a valid PDF")
        if file_type == "txt":
            try:
                temp_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise HTTPException(status_code=400, detail="TXT files must contain valid UTF-8 text") from exc
        os.replace(temp_path, destination)
        return filename, original_name, file_type, total, expected_mime
    except Exception:
        temp_path.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise


def _store_url_file(url: str) -> tuple[str, int]:
    content = url.encode("utf-8")
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="URL exceeds the configured storage size limit")
    filename = "{}.url".format(uuid4().hex)
    path = _storage_root() / filename
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return filename, len(content)


def _new_record(owner_id: UUID, filename: str, original_filename: str, file_type: str,
                content_type: str, file_size: int) -> DocumentRecord:
    return DocumentRecord(
        owner_id=owner_id,
        filename=filename,
        original_filename=original_filename,
        file_type=file_type,
        content_type=content_type,
        file_size=file_size,
        storage_path=filename,
        status=DocumentStatus.UPLOADED.value,
    )


def _make_indexes(records: list[DocumentRecord]):
    chunks: list[Document] = []
    vectors: list[list[float]] = []
    indexed_ids: set[str] = set()
    sources: set[str] = set()
    for record in records:
        try:
            record_chunks, record_vectors = load_index_artifact(record)
        except FileNotFoundError:
            # Phase 3 documents predate durable vector artifacts. Backfill once
            # from their existing local files, then subsequent rebuilds are cheap.
            record_chunks = chunk_record(record, extract_record(record))
            if not record_chunks:
                raise ValueError("Legacy document contains no searchable text")
            record_vectors = get_embeddings().embed_documents(
                [chunk.page_content for chunk in record_chunks]
            )
            write_index_artifact(record, record_chunks, record_vectors)
        chunks.extend(record_chunks)
        vectors.extend(record_vectors)
        indexed_ids.add(str(record.id))
        sources.add(record.original_filename)
    vectorstore, chunks, bm25 = build_index_from_vectors(chunks, vectors, indexed_ids)
    return vectorstore, chunks, bm25, indexed_ids, sorted(sources)


def _document_signature(records: list[DocumentRecord]) -> tuple[str, ...]:
    return tuple("{}:{}".format(record.id, record.updated_at.isoformat() if record.updated_at else "")
                 for record in records)


def _publish_index(result, signature: tuple[str, ...] = ()) -> None:
    vectorstore, chunks, bm25, document_ids, sources = result
    state.set_vectorstore(vectorstore, sources, chunks, bm25, document_ids, signature)


def rebuild_index(db: Session) -> None:
    """Rebuild from authoritative completed rows; failed files are deactivated."""
    with state.index_lock:
        records = list(db.scalars(select(DocumentRecord).where(
            DocumentRecord.status == DocumentStatus.COMPLETED.value
        ).order_by(DocumentRecord.created_at, DocumentRecord.id)).all())
        signature = _document_signature(records)
        _publish_index(_make_indexes(records), signature)


def ensure_index_current(db: Session) -> None:
    records = list(db.scalars(select(DocumentRecord).where(
        DocumentRecord.status == DocumentStatus.COMPLETED.value
    ).order_by(DocumentRecord.created_at, DocumentRecord.id)).all())
    signature = _document_signature(records)
    with state.index_lock:
        if state.index_loaded and signature == state.index_signature:
            return
        _publish_index(_make_indexes(records), signature)


def _enqueue_job(db: Session, job: IngestionJob) -> None:
    """Best-effort immediate dispatch; the durable outbox sweeper retries failures."""
    try:
        from celery_app import celery_app
        from tasks.ingestion import ingest_document

        ingest_document.apply_async(args=[str(job.id)], task_id=job.task_id)
        job.dispatched_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("Ingestion job dispatch deferred to outbox", extra={
            "job_id": str(job.id), "error_type": type(exc).__name__,
        })


def _queue_record(db: Session, record: DocumentRecord) -> tuple[DocumentRecord, IngestionJob]:
    record.status = DocumentStatus.QUEUED.value
    db.add(record)
    try:
        db.flush()
        job = IngestionJob(
            document_id=record.id,
            owner_id=record.owner_id,
            task_id=str(uuid4()),
            status=IngestionJobStatus.QUEUED.value,
        )
        db.add(job)
        db.commit()
        db.refresh(record)
        db.refresh(job)
    except Exception:
        db.rollback()
        raise
    _enqueue_job(db, job)
    return record, job


async def queue_upload_document(db: Session, owner_id: UUID, upload: UploadFile) -> tuple[DocumentRecord, IngestionJob]:
    filename, original, file_type, size, mime = await _save_upload(upload)
    record = _new_record(owner_id, filename, original, file_type, mime, size)
    try:
        return _queue_record(db, record)
    except Exception:
        db.rollback()
        (_storage_root() / filename).unlink(missing_ok=True)
        logger.error("Document metadata could not be stored", extra={"error_type": "database_error"})
        raise HTTPException(status_code=503, detail="Document storage is temporarily unavailable")


def queue_url_document(db: Session, owner_id: UUID, url: str) -> tuple[DocumentRecord, IngestionJob]:
    # URL content is fetched by the worker; only the URL and identifiers cross the queue.
    parsed = urlsplit(url)
    if (len(url) > 2048 or parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None):
        raise HTTPException(status_code=422, detail="URL is invalid or too long")
    filename, size = _store_url_file(url)
    display_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))[:512]
    record = _new_record(owner_id, filename, display_url, "url", "text/plain", size)
    try:
        return _queue_record(db, record)
    except Exception:
        db.rollback()
        (_storage_root() / filename).unlink(missing_ok=True)
        logger.error("URL document metadata could not be stored", extra={"error_type": "database_error"})
        raise HTTPException(status_code=503, detail="Document storage is temporarily unavailable")


def get_owned_job(db: Session, owner_id: UUID, job_id: UUID) -> IngestionJob:
    job = db.scalar(select(IngestionJob).where(
        IngestionJob.id == job_id, IngestionJob.owner_id == owner_id
    ))
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return job


def retry_owned_job(db: Session, owner_id: UUID, job_id: UUID) -> IngestionJob:
    job = get_owned_job(db, owner_id, job_id)
    if job.status != IngestionJobStatus.FAILED.value:
        raise HTTPException(status_code=409, detail="Only failed ingestion jobs can be retried")
    record = db.scalar(select(DocumentRecord).where(
        DocumentRecord.id == job.document_id,
        DocumentRecord.owner_id == owner_id,
        DocumentRecord.status == DocumentStatus.FAILED.value,
    ).with_for_update())
    if record is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    job.status = IngestionJobStatus.QUEUED.value
    job.error_message = None
    job.finished_at = None
    job.task_id = str(uuid4())
    job.dispatched_at = None
    job.next_attempt_at = None
    job.attempt_count = 0
    record.status = DocumentStatus.QUEUED.value
    record.error_message = None
    db.commit()
    db.refresh(job)
    _enqueue_job(db, job)
    return job


def resolve_authorized_scope(db: Session, owner_id: UUID) -> dict[str, str]:
    rows = db.execute(select(DocumentRecord.id, DocumentRecord.owner_id).where(
        DocumentRecord.owner_id == owner_id,
        DocumentRecord.status == DocumentStatus.COMPLETED.value,
    )).all()
    return {str(document_id): str(record_owner_id) for document_id, record_owner_id in rows}


def list_owned_documents(db: Session, owner_id: UUID, limit: int, offset: int):
    base = select(DocumentRecord).where(DocumentRecord.owner_id == owner_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = list(db.scalars(base.order_by(DocumentRecord.created_at.desc(), DocumentRecord.id)
                            .limit(limit).offset(offset)).all())
    return items, total


def list_all_documents_for_admin(db: Session, limit: int, offset: int):
    """Return upload metadata and owner identity only; document content stays private."""
    base = select(DocumentRecord, User.email).join(User, User.id == DocumentRecord.owner_id)
    total = db.scalar(select(func.count()).select_from(
        select(DocumentRecord.id).subquery()
    )) or 0
    rows = db.execute(base.options(selectinload(DocumentRecord.ingestion_job))
                     .order_by(DocumentRecord.created_at.desc(), DocumentRecord.id)
                     .limit(limit).offset(offset)).all()
    return rows, total


def get_owned_document(db: Session, owner_id: UUID, document_id: UUID) -> DocumentRecord:
    record = db.scalar(select(DocumentRecord).where(
        DocumentRecord.id == document_id, DocumentRecord.owner_id == owner_id
    ))
    if record is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return record


def delete_owned_document(db: Session, owner_id: UUID, document_id: UUID) -> None:
    with state.index_lock:
        record = get_owned_document(db, owner_id, document_id)
        record.status = DocumentStatus.DELETING.value
        record.error_message = None
        db.commit()  # The DB retrieval scope excludes it before disk cleanup begins.
        try:
            storage_file(record).unlink(missing_ok=True)
            artifact_file(record).unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            logger.exception("Document file cleanup failed", extra={"document_id": str(document_id)})
            raise HTTPException(status_code=500, detail="Document could not be deleted safely") from exc
        try:
            db.execute(update(MessageCitation).where(MessageCitation.document_id == record.id).values(
                source="Source unavailable", chunk_id=None, document_id=None
            ))
            db.delete(record)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("Document metadata deletion failed", extra={"document_id": str(document_id)})
            raise HTTPException(status_code=503, detail="Document deletion is temporarily unavailable") from exc
        # If compaction fails, the database scope still excludes this ID; chat refresh will fail closed.
        try:
            rebuild_index(db)
        except Exception:
            logger.exception("Index compaction after deletion failed", extra={"document_id": str(document_id)})


def clear_all_documents(db: Session) -> int:
    """Admin-only legacy clear action, made durable for DB-backed documents."""
    with state.index_lock:
        records = list(db.scalars(select(DocumentRecord)).all())
        for record in records:
            record.status = DocumentStatus.DELETING.value
        db.commit()
        failures = []
        for record in records:
            try:
                storage_file(record).unlink(missing_ok=True)
                artifact_file(record).unlink(missing_ok=True)
            except (OSError, ValueError):
                failures.append(record)
        if failures:
            for record in failures:
                record.error_message = "Stored file cleanup failed."
            db.commit()
            try:
                rebuild_index(db)
            except Exception:
                logger.exception("Could not rebuild index after a clear failure")
            raise HTTPException(status_code=500, detail="Some documents could not be deleted safely")
        try:
            record_ids = [record.id for record in records]
            if record_ids:
                db.execute(update(MessageCitation).where(MessageCitation.document_id.in_(record_ids)).values(
                    source="Source unavailable", chunk_id=None, document_id=None
                ))
            for record in records:
                db.delete(record)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("Document clear operation failed")
            raise HTTPException(status_code=503, detail="Document clearing is temporarily unavailable") from exc
        rebuild_index(db)
        return len(records)
