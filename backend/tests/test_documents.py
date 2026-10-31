import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4
from unittest.mock import patch

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.testclient import TestClient
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import retrieval
import state
from routers import chat
from core.config import settings
from core.dependencies import get_current_user
from db.base import Base
from db.session import get_db
from main import app
from models.document import DocumentRecord
from models.user import User
from routers import ingest
from services.rag_indexing import build_indexes
from services.worker_ingestion import process_ingestion_job


class FakeEmbeddings(Embeddings):
    def _embed(self, text):
        vector = [0.0] * 128
        for token in retrieval._tokens(text):
            index = sum(token.encode("utf-8")) % len(vector)
            vector[index] += 1.0
        return vector

    def embed_documents(self, texts):
        return [self._embed(text) for text in texts]

    def embed_query(self, text):
        return self._embed(text)


class FakeReranker:
    def predict(self, pairs):
        return [5.0 if set(retrieval._tokens(query)) & set(retrieval._tokens(text)) else -5.0
                for query, text in pairs]


class FakeChatModel:
    def __init__(self):
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return SimpleNamespace(content="The document contains the requested fact [1].")


def make_pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    # A minimal content stream with one text object for the parser validation path.
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
    })
    content = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content.set_data(f"BT /F1 12 Tf 50 740 Td ({escaped}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(content)
    import io
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class DocumentApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.user_a = User(id=uuid4(), email="a@example.test", hashed_password="test-hash")
        self.user_b = User(id=uuid4(), email="b@example.test", hashed_password="test-hash")
        with self.sessions() as db:
            db.add_all([self.user_a, self.user_b])
            db.commit()

        def override_db():
            with self.sessions() as db:
                yield db

        bearer = HTTPBearer(auto_error=False)

        def override_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                          db=Depends(get_db)):
            if credentials is None:
                raise HTTPException(status_code=401, detail="Authentication required")
            try:
                user_id = UUID(credentials.credentials)
            except ValueError as exc:
                raise HTTPException(status_code=401, detail="Invalid test principal") from exc
            user = db.get(User, user_id)
            if user is None:
                raise HTTPException(status_code=401, detail="Invalid test principal")
            return user

        self.previous_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        self.storage_temp = tempfile.TemporaryDirectory(prefix="findocai-doc-test-")
        self.storage_patcher = patch.object(settings, "document_storage_dir", Path(self.storage_temp.name))
        self.size_patcher = patch.object(settings, "max_upload_size_bytes", 1024 * 1024)
        self.storage_patcher.start()
        self.size_patcher.start()
        self.embedding_patcher = patch("services.rag_indexing.get_embeddings", return_value=FakeEmbeddings())
        self.embedding_patcher.start()
        self.document_embedding_patcher = patch("services.documents.get_embeddings", return_value=FakeEmbeddings())
        self.document_embedding_patcher.start()
        self.worker_embedding_patcher = patch("services.worker_ingestion.get_embeddings", return_value=FakeEmbeddings())
        self.worker_embedding_patcher.start()
        self.worker_engine_patcher = patch("services.worker_ingestion.get_engine", return_value=self.engine)
        self.worker_engine_patcher.start()
        self.dispatch_patcher = patch("services.documents._enqueue_job", return_value=None)
        self.dispatch_patcher.start()
        self.reranker_patcher = patch.object(retrieval, "_get_reranker", return_value=FakeReranker())
        self.reranker_patcher.start()
        state.clear_state()
        self.client = TestClient(app)

    def tearDown(self):
        state.clear_state()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)
        self.embedding_patcher.stop()
        self.document_embedding_patcher.stop()
        self.worker_embedding_patcher.stop()
        self.worker_engine_patcher.stop()
        self.dispatch_patcher.stop()
        self.reranker_patcher.stop()
        self.storage_patcher.stop()
        self.size_patcher.stop()
        self.storage_temp.cleanup()
        self.engine.dispose()

    def headers(self, user):
        return {"Authorization": "Bearer {}".format(user.id)}

    def upload_txt(self, user, filename, text):
        response = self.client.post(
            "/api/v1/documents", headers=self.headers(user),
            files={"file": (filename, text.encode("utf-8"), "text/plain")},
        )
        if response.status_code == 202:
            process_ingestion_job(response.json()["job_id"])
            with self.sessions() as db:
                from services.documents import ensure_index_current
                ensure_index_current(db)
            return self.client.get("/api/v1/documents/{}".format(response.json()["document_id"]),
                                   headers=self.headers(user))
        return response

    def test_auth_required_for_documents_and_chat(self):
        for response in (
            self.client.post("/api/v1/documents", files={"file": ("a.txt", b"hello", "text/plain")}),
            self.client.get("/api/v1/documents"),
            self.client.post("/api/v1/chat/ask", json={"question": "secret?"}),
        ):
            self.assertEqual(response.status_code, 401)

    def test_upload_returns_accepted_job_and_job_is_owner_scoped(self):
        response = self.client.post(
            "/api/v1/documents", headers=self.headers(self.user_a),
            files={"file": ("queued.txt", b"Queued financial facts.", "text/plain")},
        )
        self.assertEqual(response.status_code, 202, response.text)
        payload = response.json()
        self.assertEqual(payload["id"], payload["document_id"])
        self.assertEqual(payload["status"], "queued")
        self.assertIn("/ingestion-jobs/", payload["status_url"])
        self.assertEqual(self.client.get(payload["status_url"].replace("/api/v1", "/api"),
                                         headers=self.headers(self.user_a)).status_code, 200)
        self.assertEqual(self.client.get(payload["status_url"].replace("/api/v1", "/api"),
                                         headers=self.headers(self.user_b)).status_code, 404)
        detail = self.client.get("/api/v1/documents/{}".format(payload["document_id"]),
                                 headers=self.headers(self.user_a))
        self.assertEqual(detail.json()["status"], "queued")
        self.assertEqual(detail.json()["ingestion_job_id"], payload["job_id"])

    def test_chat_explains_that_queued_upload_is_not_searchable_yet(self):
        upload = self.client.post(
            "/api/v1/documents", headers=self.headers(self.user_a),
            files={"file": ("article-15.txt", b"Article 15 text is present.", "text/plain")},
        )
        self.assertEqual(upload.status_code, 202, upload.text)
        response = self.client.post("/api/v1/chat/ask", headers=self.headers(self.user_a), json={
            "question": "What is Article 15?",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("still queued for processing", response.json()["answer"])
        self.assertEqual(response.json()["sources"], [])

    def test_admin_can_list_upload_metadata_but_delete_remains_owner_scoped(self):
        first = self.client.post(
            "/api/v1/documents", headers=self.headers(self.user_a),
            files={"file": ("owner-a.txt", b"A user's private document.", "text/plain")},
        )
        second = self.client.post(
            "/api/v1/documents", headers=self.headers(self.user_b),
            files={"file": ("owner-b.txt", b"B user's private document.", "text/plain")},
        )
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        denied = self.client.get("/api/v1/documents/admin", headers=self.headers(self.user_a))
        self.assertEqual(denied.status_code, 403)
        with self.sessions() as db:
            user = db.get(User, self.user_a.id)
            user.role = "admin"
            db.commit()
        response = self.client.get("/api/v1/documents/admin?limit=10", headers=self.headers(self.user_a))
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["total"], 2)
        self.assertEqual({item["owner_email"] for item in payload["items"]},
                         {"a@example.test", "b@example.test"})
        self.assertTrue(all("storage_path" not in item and "content" not in item for item in payload["items"]))
        denied_delete = self.client.delete(
            "/api/v1/documents/{}".format(second.json()["document_id"]), headers=self.headers(self.user_a)
        )
        self.assertEqual(denied_delete.status_code, 404)
        owner_delete = self.client.delete(
            "/api/v1/documents/{}".format(first.json()["document_id"]), headers=self.headers(self.user_a)
        )
        self.assertEqual(owner_delete.status_code, 204)

    def test_enqueue_failure_leaves_durable_outbox_job_queued(self):
        self.dispatch_patcher.stop()
        try:
            with patch("tasks.ingestion.ingest_document.apply_async", side_effect=RuntimeError("redis offline")):
                response = self.client.post(
                    "/api/v1/documents", headers=self.headers(self.user_a),
                    files={"file": ("deferred.txt", b"Persist the queued job.", "text/plain")},
                )
        finally:
            self.dispatch_patcher.start()
        self.assertEqual(response.status_code, 202, response.text)
        payload = response.json()
        with self.sessions() as db:
            from models.document import IngestionJob
            job = db.get(IngestionJob, UUID(payload["job_id"]))
            record = db.get(DocumentRecord, UUID(payload["document_id"]))
            self.assertEqual(job.status, "queued")
            self.assertIsNone(job.dispatched_at)
            self.assertEqual(record.status, "queued")

    def test_outbox_redispatches_a_stale_queued_task(self):
        response = self.client.post(
            "/api/v1/documents", headers=self.headers(self.user_a),
            files={"file": ("stale.txt", b"Retry a lost queued task.", "text/plain")},
        )
        self.assertEqual(response.status_code, 202, response.text)
        from models.document import IngestionJob
        with self.sessions() as db:
            job = db.get(IngestionJob, UUID(response.json()["job_id"]))
            job.dispatched_at = datetime.now(timezone.utc) - timedelta(minutes=2)
            db.commit()
        from services.worker_ingestion import dispatch_outbox
        with patch("tasks.ingestion.ingest_document.apply_async") as enqueue:
            self.assertEqual(dispatch_outbox(), 1)
            enqueue.assert_called_once()

    def test_worker_lifecycle_is_idempotent_and_api_refreshes_from_artifact(self):
        response = self.client.post(
            "/api/v1/documents", headers=self.headers(self.user_a),
            files={"file": ("lifecycle.txt", b"Revenue equals $37 million.", "text/plain")},
        )
        payload = response.json()
        self.assertEqual(response.status_code, 202)
        self.assertIsNone(state.get_vectorstore())
        self.assertEqual(process_ingestion_job(payload["job_id"]), "completed")
        self.assertEqual(process_ingestion_job(payload["job_id"]), "already_finished_or_deleted")
        with self.sessions() as db:
            from services.documents import ensure_index_current
            ensure_index_current(db)
        self.assertIn(payload["document_id"], state.indexed_document_ids)
        chunk = next(chunk for chunk in state.get_documents()
                     if chunk.metadata["document_id"] == payload["document_id"])
        self.assertEqual(chunk.metadata["owner_id"], str(self.user_a.id))
        with self.sessions() as db:
            from models.document import IngestionJob
            self.assertEqual(db.get(IngestionJob, UUID(payload["job_id"])).status, "completed")

    def test_transient_embedding_error_is_requeued_and_retry_can_complete(self):
        from types import SimpleNamespace

        class FakeTask:
            max_retries = 3
            request = SimpleNamespace(retries=0, id=None)

        response = self.client.post(
            "/api/v1/documents", headers=self.headers(self.user_a),
            files={"file": ("retry.txt", b"Retryable embeddings.", "text/plain")},
        )
        payload = response.json()
        task = FakeTask()
        with self.sessions() as db:
            from models.document import IngestionJob
            task.request.id = db.get(IngestionJob, UUID(payload["job_id"])).task_id
        with patch("services.worker_ingestion.get_embeddings", side_effect=RuntimeError("model unavailable")):
            result = process_ingestion_job(payload["job_id"], task=task)
        self.assertEqual(result, "retry_scheduled")
        with self.sessions() as db:
            from models.document import IngestionJob
            job = db.get(IngestionJob, UUID(payload["job_id"]))
            record = db.get(DocumentRecord, UUID(payload["document_id"]))
            self.assertEqual(job.status, "queued")
            self.assertEqual(record.status, "queued")
            self.assertEqual(job.attempt_count, 1)
            self.assertIsNotNone(job.next_attempt_at)
            job.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=30)
            db.commit()
        from services.worker_ingestion import dispatch_outbox
        with patch("tasks.ingestion.ingest_document.apply_async") as enqueue:
            self.assertEqual(dispatch_outbox(), 0)
            enqueue.assert_not_called()
            with self.sessions() as db:
                job = db.get(IngestionJob, UUID(payload["job_id"]))
                job.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                db.commit()
            self.assertEqual(dispatch_outbox(), 1)
            enqueue.assert_called_once()
        task.request.retries = 1
        with patch("services.worker_ingestion.get_embeddings", return_value=FakeEmbeddings()), \
             patch("services.rag_indexing.get_embeddings", return_value=FakeEmbeddings()):
            self.assertEqual(process_ingestion_job(payload["job_id"], task=task), "completed")

    def test_permanent_parse_failure_is_sanitized_in_job_status(self):
        response = self.client.post(
            "/api/v1/documents", headers=self.headers(self.user_a),
            files={"file": ("malformed.pdf", b"%PDF-not-a-real-pdf", "application/pdf")},
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(process_ingestion_job(payload["job_id"]), "failed")
        status_response = self.client.get(payload["status_url"].replace("/api/v1", "/api"),
                                          headers=self.headers(self.user_a))
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["status"], "failed")
        self.assertIn("Check the file", status_response.json()["error_message"])
        self.assertNotIn("malformed.pdf", status_response.json()["error_message"])

    def test_queued_document_deleted_before_worker_cannot_be_indexed(self):
        response = self.client.post(
            "/api/v1/documents", headers=self.headers(self.user_a),
            files={"file": ("cancel.txt", b"Do not retrieve after deletion.", "text/plain")},
        )
        payload = response.json()
        deleted = self.client.delete("/api/v1/documents/{}".format(payload["document_id"]),
                                     headers=self.headers(self.user_a))
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(process_ingestion_job(payload["job_id"]), "already_finished_or_deleted")
        self.assertNotIn(payload["document_id"], state.indexed_document_ids)

    def test_running_worker_cannot_republish_document_deleted_mid_processing(self):
        response = self.client.post(
            "/api/v1/documents", headers=self.headers(self.user_a),
            files={"file": ("race.txt", b"Deletion wins over running ingestion.", "text/plain")},
        )
        payload = response.json()
        from services.documents import delete_owned_document
        from services.worker_ingestion import chunk_record as original_chunk_record

        def delete_during_chunking(record, source_docs):
            with self.sessions() as db:
                delete_owned_document(db, self.user_a.id, record.id)
            return original_chunk_record(record, source_docs)

        with patch("services.worker_ingestion.chunk_record", side_effect=delete_during_chunking):
            outcome = process_ingestion_job(payload["job_id"])
        self.assertEqual(outcome, "deleted_or_superseded")
        with self.sessions() as db:
            self.assertIsNone(db.get(DocumentRecord, UUID(payload["document_id"])))
        self.assertEqual(self.client.get(
            "/api/v1/documents/{}".format(payload["document_id"]),
            headers=self.headers(self.user_a),
        ).status_code, 404)
        self.assertNotIn(payload["document_id"], state.indexed_document_ids)

    def test_user_without_completed_documents_does_not_call_llm(self):
        with patch.object(chat, "get_llm") as llm:
            response = self.client.post("/api/v1/chat/ask", headers=self.headers(self.user_a), json={
                "question": "Tell me anything.", "session_id": "empty",
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["sources"], [])
        llm.assert_not_called()

    def test_valid_txt_pdf_and_chunk_ownership_metadata(self):
        txt = self.client.post(
            "/api/v1/documents", headers=self.headers(self.user_a),
            data={"owner_id": str(self.user_b.id)},
            files={"file": ("report.txt", b"Revenue was $42 million, up 12%.", "text/plain")},
        )
        self.assertEqual(txt.status_code, 202, txt.text)
        process_ingestion_job(txt.json()["job_id"])
        with self.sessions() as db:
            from services.documents import ensure_index_current
            ensure_index_current(db)
        txt = self.client.get("/api/v1/documents/{}".format(txt.json()["document_id"]),
                              headers=self.headers(self.user_a))
        self.assertEqual(txt.json()["status"], "completed")
        self.assertNotIn("storage_path", txt.json())
        with self.sessions() as db:
            self.assertEqual(db.get(DocumentRecord, UUID(txt.json()["id"])).owner_id, self.user_a.id)
        pdf = self.client.post(
            "/api/v1/documents", headers=self.headers(self.user_a),
            files={"file": ("statement.pdf", make_pdf("Net income was $7 million."), "application/pdf")},
        )
        self.assertEqual(pdf.status_code, 202, pdf.text)
        process_ingestion_job(pdf.json()["job_id"])
        with self.sessions() as db:
            from services.documents import ensure_index_current
            ensure_index_current(db)
        pdf = self.client.get("/api/v1/documents/{}".format(pdf.json()["document_id"]),
                              headers=self.headers(self.user_a))
        for chunk in state.get_documents():
            self.assertEqual(chunk.metadata["owner_id"], str(self.user_a.id))
            self.assertIn(chunk.metadata["document_id"], state.indexed_document_ids)
            self.assertTrue(chunk.metadata["chunk_id"])
            self.assertTrue(chunk.metadata["source"])

    def test_legacy_url_ingestion_persists_owner_scoped_document(self):
        page = Document(page_content="Market outlook is positive for ALPHAFUND.",
                        metadata={"source": "https://example.test/report"})
        fake_loader = SimpleNamespace(load=lambda: [page])
        response = self.client.post("/api/ingest/urls", headers=self.headers(self.user_a),
                                    json={"urls": ["https://example.test/report"]})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["sources"], ["https://example.test/report"])
        class FakeResponse:
            status_code = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}
            encoding = "utf-8"

            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def iter_content(self, chunk_size):
                return iter([b"<html><body>Market outlook is positive for ALPHAFUND.</body></html>"])

        fake_response = FakeResponse()
        with patch("services.worker_ingestion.socket.getaddrinfo",
                   return_value=[(None, None, None, None, ("93.184.216.34", 443))]), \
             patch("services.worker_ingestion.requests.Session.get", return_value=fake_response) as fetch:
            self.assertEqual(process_ingestion_job(response.json()["jobs"][0]["job_id"]), "completed")
            self.assertTrue(fetch.call_args.args[0].startswith("https://93.184.216.34/"))
            self.assertFalse(fetch.call_args.kwargs["allow_redirects"])
        with self.sessions() as db:
            from services.documents import ensure_index_current
            ensure_index_current(db)
        self.assertTrue(all(chunk.metadata["owner_id"] == str(self.user_a.id)
                            for chunk in state.get_documents()))

    def test_url_ingestion_rejects_private_dns_before_connecting(self):
        response = self.client.post("/api/ingest/urls", headers=self.headers(self.user_a),
                                    json={"urls": ["http://internal.example.test/metadata"]})
        self.assertEqual(response.status_code, 202)
        with patch("services.worker_ingestion.socket.getaddrinfo",
                   return_value=[(None, None, None, None, ("127.0.0.1", 80))]), \
             patch("services.worker_ingestion.requests.Session.get") as fetch:
            outcome = process_ingestion_job(response.json()["jobs"][0]["job_id"])
        self.assertEqual(outcome, "failed")
        fetch.assert_not_called()
        with self.sessions() as db:
            from models.document import IngestionJob
            job = db.get(IngestionJob, UUID(response.json()["jobs"][0]["job_id"]))
            self.assertEqual(job.status, "failed")
            self.assertNotIn("127.0.0.1", job.error_message)

    def test_rejects_unsupported_mime_invalid_content_and_oversize(self):
        wrong_ext = self.client.post("/api/v1/documents", headers=self.headers(self.user_a),
                                     files={"file": ("notes.csv", b"a,b", "text/csv")})
        self.assertEqual(wrong_ext.status_code, 415)
        wrong_mime = self.client.post("/api/v1/documents", headers=self.headers(self.user_a),
                                      files={"file": ("notes.txt", b"hello", "application/pdf")})
        self.assertEqual(wrong_mime.status_code, 415)
        invalid_pdf = self.client.post("/api/v1/documents", headers=self.headers(self.user_a),
                                       files={"file": ("bad.pdf", b"not pdf", "application/pdf")})
        self.assertEqual(invalid_pdf.status_code, 400)
        with patch.object(settings, "max_upload_size_bytes", 8):
            too_big = self.upload_txt(self.user_a, "big.txt", "this content is too large")
        self.assertEqual(too_big.status_code, 413)

    def test_pagination_and_owner_only_metadata_and_delete(self):
        first = self.upload_txt(self.user_a, "first.txt", "Alpha report has revenue.").json()
        second = self.upload_txt(self.user_a, "second.txt", "Beta report has costs.").json()
        other = self.upload_txt(self.user_b, "private.txt", "Borealis confidential EBITDA.").json()
        page = self.client.get("/api/v1/documents?limit=1&offset=0", headers=self.headers(self.user_a))
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.json()["total"], 2)
        self.assertEqual(len(page.json()["items"]), 1)
        self.assertEqual(self.client.get("/api/v1/documents/{}".format(other["id"]),
                                         headers=self.headers(self.user_a)).status_code, 404)
        self.assertEqual(self.client.delete("/api/v1/documents/{}".format(other["id"]),
                                            headers=self.headers(self.user_a)).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/documents/{}".format(first["id"]),
                                         headers=self.headers(self.user_a)).status_code, 200)
        with self.sessions() as db:
            storage_name = db.get(DocumentRecord, UUID(second["id"])).storage_path
        response = self.client.delete("/api/v1/documents/{}".format(second["id"]),
                                      headers=self.headers(self.user_a))
        self.assertEqual(response.status_code, 204)
        with self.sessions() as db:
            self.assertIsNone(db.get(DocumentRecord, UUID(second["id"])))
        self.assertFalse((Path(settings.document_storage_dir) / storage_name).exists())

    def test_two_user_isolation_across_faiss_bm25_fusion_reranking_and_llm(self):
        a = self.upload_txt(self.user_a, "a.txt", "AURORAALPHA private annual revenue equals $731 million.").json()
        b = self.upload_txt(self.user_b, "b.txt", "BOREALISBETA confidential EBITDA equals $942 million.").json()
        scope_a = {a["id"]: str(self.user_a.id)}
        semantic = retrieval.semantic_search("BOREALISBETA EBITDA", scope_a, 10)
        lexical = retrieval.bm25_search("BOREALISBETA EBITDA", scope_a, 10)
        self.assertTrue(all(chunk_id in {d.metadata["chunk_id"] for d in state.get_documents()
                                         if d.metadata["document_id"] == a["id"]}
                            for chunk_id, _ in semantic + lexical))
        a_chunks = [d for d in state.get_documents() if d.metadata["document_id"] == a["id"]]
        allowed_a_ids = {d.metadata["chunk_id"] for d in a_chunks}
        scoped_scores = dict(retrieval.bm25_search("AURORAALPHA revenue", scope_a, 10))
        only_a_scores = dict(retrieval.BM25Index(a_chunks).search(
            "AURORAALPHA revenue", 10, allowed_a_ids
        ))
        self.assertEqual(scoped_scores, only_a_scores)
        self.assertFalse(any("BOREALISBETA" in d.page_content
                             for d in retrieval.retrieve_detailed("BOREALISBETA EBITDA", scope_a).documents))
        model = FakeChatModel()
        with patch.object(chat, "get_llm", return_value=model):
            response = self.client.post("/api/v1/chat/ask", headers=self.headers(self.user_a), json={
                "question": "What is AURORAALPHA annual revenue?", "session_id": "owner-a",
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(model.prompts), 1)
        self.assertIn("AURORAALPHA", model.prompts[0])
        self.assertNotIn("BOREALISBETA", model.prompts[0])
        self.assertEqual(b["status"], "completed")
        model_b = FakeChatModel()
        with patch.object(chat, "get_llm", return_value=model_b):
            response_b = self.client.post("/api/v1/chat/ask", headers=self.headers(self.user_b), json={
                "question": "What is BOREALISBETA EBITDA?", "session_id": "owner-b",
            })
        self.assertEqual(response_b.status_code, 200, response_b.text)
        self.assertIn("BOREALISBETA", model_b.prompts[0])
        self.assertNotIn("AURORAALPHA", model_b.prompts[0])

    def test_deleted_stale_faiss_and_bm25_chunks_are_not_retrievable(self):
        uploaded = self.upload_txt(self.user_a, "delete-me.txt", "ZEPHYRSECRET unique deletion token.").json()
        stale_vectorstore = state.get_vectorstore()
        stale_docs = list(state.get_documents())
        stale_bm25 = state.get_bm25_index()
        response = self.client.delete("/api/v1/documents/{}".format(uploaded["id"]),
                                      headers=self.headers(self.user_a))
        self.assertEqual(response.status_code, 204)
        # Simulate a stale process-local vector/lexical index; the DB active-document
        # set must force a rebuild before retrieval.
        state.set_vectorstore(stale_vectorstore, ["delete-me.txt"], stale_docs, stale_bm25, {uploaded["id"]})
        with self.sessions() as db:
            from services.documents import ensure_index_current, resolve_authorized_scope
            ensure_index_current(db)
            scope = resolve_authorized_scope(db, self.user_a.id)
        self.assertEqual(scope, {})
        self.assertEqual(retrieval.retrieve_detailed("ZEPHYRSECRET", scope).documents, [])

    def test_missing_or_mismatched_owner_metadata_fails_closed(self):
        authorized_doc_id = str(uuid4())
        wrong_owner = str(uuid4())
        doc = Document(page_content="SECRET METADATA MUST NOT LEAK", metadata={
            "chunk_id": "bad-owner-chunk", "document_id": authorized_doc_id,
            "owner_id": wrong_owner, "source": "fake.txt",
        })
        vs, docs, bm25 = build_indexes([doc], {authorized_doc_id})
        state.set_vectorstore(vs, ["fake.txt"], docs, bm25, {authorized_doc_id})
        scope = {authorized_doc_id: str(self.user_a.id)}
        self.assertEqual(retrieval.semantic_search("SECRET", scope), [])
        self.assertEqual(retrieval.bm25_search("SECRET", scope), [])
        self.assertEqual(retrieval.retrieve_detailed("SECRET", scope).documents, [])

    def test_missing_ownership_metadata_is_rejected_before_indexing(self):
        invalid = Document(page_content="unowned content", metadata={"chunk_id": "missing-owner", "source": "x.txt"})
        with self.assertRaises(ValueError):
            build_indexes([invalid], {str(uuid4())})

    def test_completed_documents_rebuild_after_in_memory_index_reset(self):
        uploaded = self.upload_txt(self.user_a, "restart.txt", "RESTARTABLE private result is $88 million.")
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        # Simulate a Phase 3 record that predates persistent worker artifacts.
        from services.rag_indexing import artifact_file
        with self.sessions() as db:
            artifact_file(db.get(DocumentRecord, UUID(uploaded.json()["id"]))).unlink()
        state.clear_state()
        model = FakeChatModel()
        with patch.object(chat, "get_llm", return_value=model):
            response = self.client.post("/api/v1/chat/ask", headers=self.headers(self.user_a), json={
                "question": "What is the RESTARTABLE private result?", "session_id": "restart",
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("RESTARTABLE", model.prompts[0])
        self.assertEqual(state.indexed_document_ids, {uploaded.json()["id"]})


if __name__ == "__main__":
    unittest.main()
