import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import torch
from fastapi.testclient import TestClient
from langchain_core.embeddings import Embeddings
from langchain_core.documents import Document
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
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
from models.conversation import Conversation, Message
from models.document import DocumentRecord, DocumentStatus
from models.user import User
from services.rag_indexing import build_indexes, chunk_record, write_index_artifact
from services.worker_ingestion import process_ingestion_job


OWNER_ID = UUID(int=1)


class FakeEmbeddings(Embeddings):
    def _embed(self, text):
        terms = retrieval._tokens(text)
        vector = [0.0] * 32
        for term in terms:
            index = sum(term.encode("utf-8")) % len(vector)
            vector[index] += 1.0
        return vector

    def embed_documents(self, texts):
        return [self._embed(text) for text in texts]

    def embed_query(self, text):
        return self._embed(text)


class FakeReranker:
    def predict(self, pairs):
        return [2.0 if set(retrieval._tokens(query)) & set(retrieval._tokens(text)) else -1.0
                for query, text in pairs]


class FakeChatModel:
    def __init__(self, answers):
        self.answers = iter(answers)

    def invoke(self, _prompt):
        return SimpleNamespace(content=next(self.answers))


def make_pdf(pages):
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    for lines in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
        })
        operators = ["BT", "/F1 12 Tf", "50 740 Td"]
        for index, line in enumerate(lines):
            if index:
                operators.append("0 -18 Td")
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            operators.append("({}) Tj".format(escaped))
        operators.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(operators).encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class RagPipelineTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:",
                                    connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.user = User(id=OWNER_ID, email="rag@example.test", hashed_password="test-hash", role="admin")
        with self.sessions() as db:
            db.add(self.user)
            db.commit()

        def override_db():
            with self.sessions() as db:
                yield db

        self.previous_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=OWNER_ID, role="admin")
        self.storage_temp = tempfile.TemporaryDirectory(prefix="findocai-rag-test-")
        self.storage_patcher = patch.object(settings, "document_storage_dir", Path(self.storage_temp.name))
        self.storage_patcher.start()
        self.worker_engine_patcher = patch("services.worker_ingestion.get_engine", return_value=self.engine)
        self.worker_engine_patcher.start()
        self.worker_embedding_patcher = patch("services.worker_ingestion.get_embeddings", return_value=FakeEmbeddings())
        self.worker_embedding_patcher.start()
        state.clear_state()

    def tearDown(self):
        state.clear_state()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)
        self.storage_patcher.stop()
        self.worker_engine_patcher.stop()
        self.worker_embedding_patcher.stop()
        self.storage_temp.cleanup()
        self.engine.dispose()

    def index_docs(self, docs):
        groups = {}
        for doc in docs:
            groups.setdefault(str(doc.metadata.get("source", "source.txt")), []).append(doc)
        chunks, owners = [], {}
        for source, source_docs in groups.items():
            document_id = uuid4()
            record = DocumentRecord(
                id=document_id, owner_id=OWNER_ID, filename="{}.txt".format(document_id.hex),
                original_filename=source, file_type="txt", content_type="text/plain", file_size=0,
                storage_path="{}.txt".format(document_id.hex), status=DocumentStatus.COMPLETED.value,
            )
            with self.sessions() as db:
                db.add(record)
                db.commit()
            owners[str(document_id)] = str(OWNER_ID)
            record_chunks = chunk_record(record, source_docs)
            chunks.extend(record_chunks)
            vectors = FakeEmbeddings().embed_documents([chunk.page_content for chunk in record_chunks])
            write_index_artifact(record, record_chunks, vectors)
        vs, chunks, bm25 = build_indexes(chunks, set(owners))
        with self.sessions() as db:
            records = list(db.query(DocumentRecord).filter(
                DocumentRecord.status == DocumentStatus.COMPLETED.value
            ).order_by(DocumentRecord.created_at, DocumentRecord.id).all())
        signature = tuple("{}:{}".format(record.id, record.updated_at.isoformat()) for record in records)
        state.set_vectorstore(vs, list(groups), chunks, bm25, set(owners), signature)
        return owners

    def test_unique_chunk_ids_preserve_duplicate_content_source_page_and_bm25(self):
        docs = [
            Document(page_content="Revenue was $1.2 million, up 12%.", metadata={"source": "annual.pdf", "page": 0}),
            Document(page_content="Revenue was $1.2 million, up 12%.", metadata={"source": "annual.pdf", "page": 1}),
            Document(page_content="Revenue was $1.2 million, up 12%.", metadata={"source": "annual.pdf", "page": 0}),
        ]
        with patch("services.rag_indexing.get_embeddings", return_value=FakeEmbeddings()):
            scope = self.index_docs(docs)
        chunks = state.get_documents()
        self.assertEqual(len(chunks), 3)
        self.assertEqual(len({doc.metadata["chunk_id"] for doc in chunks}), 3)
        self.assertEqual({doc.metadata["page"] for doc in chunks}, {0, 1})
        matches = retrieval.bm25_search("revenue $1.2 million 12%", scope)
        self.assertEqual({chunk_id for chunk_id, _ in matches}, {d.metadata["chunk_id"] for d in chunks})
        evidence, citations = retrieval.format_evidence(chunks, scope)
        self.assertIn("page 1", evidence)
        self.assertIn("page 2", evidence)
        self.assertEqual(len(citations), 3)

    def test_clear_resets_semantic_and_keyword_indexes(self):
        with patch("services.rag_indexing.get_embeddings", return_value=FakeEmbeddings()):
            self.index_docs([Document(page_content="Net income was $4.", metadata={"source": "x.txt"})])
        state.clear_state()
        self.assertIsNone(state.get_vectorstore())
        self.assertIsNone(state.get_bm25_index())
        self.assertEqual(state.get_documents(), [])

    def test_retrieval_reranking_handles_duplicates_by_id_and_reports_errors(self):
        with patch("services.rag_indexing.get_embeddings", return_value=FakeEmbeddings()):
            scope = self.index_docs([
                Document(page_content="2024 revenue grew to $20 million", metadata={"source": "a"}),
                Document(page_content="2024 revenue grew to $20 million", metadata={"source": "b"}),
            ])
        with patch.object(retrieval, "_get_reranker", return_value=FakeReranker()):
            result = retrieval.retrieve_detailed("2024 revenue", scope)
        self.assertEqual(len(result.documents), 2)
        self.assertEqual(len({d.metadata["chunk_id"] for d in result.documents}), 2)
        with patch.object(retrieval, "_get_reranker", side_effect=RuntimeError("offline")):
            fallback = retrieval.retrieve_detailed("2024 revenue", scope)
        self.assertIn("reranking failed", fallback.rerank_error.lower())
        self.assertEqual(fallback.documents, [])

    def test_financial_pdf_layout_keeps_table_values_and_page_citations(self):
        pdf = make_pdf([
            ["Income Statement", "Metric        2023        2024", "Revenue       $100        $125", "Growth        8%          25%"],
            ["Notes", "Net income increased to $18.5 million in 2024.", "Figure 1: Revenue growth was 25% in 2024."],
        ])
        with patch("services.rag_indexing.get_embeddings", return_value=FakeEmbeddings()):
            response = TestClient(app).post("/api/ingest/pdf", files=[("files", ("financial.pdf", pdf, "application/pdf"))])
            self.assertEqual(response.status_code, 202, response.text)
            process_ingestion_job(response.json()["jobs"][0]["job_id"])
            with self.sessions() as db:
                from services.documents import ensure_index_current
                ensure_index_current(db)
        docs = state.get_documents()
        all_text = "\n".join(d.page_content for d in docs)
        self.assertIn("$125", all_text)
        self.assertIn("25%", all_text)
        self.assertIn("2024", all_text)
        self.assertIn("Figure 1", all_text)
        self.assertTrue(any(d.metadata.get("page") == 1 for d in docs))
        with self.sessions() as db:
            from services.documents import resolve_authorized_scope
            scope = resolve_authorized_scope(db, OWNER_ID)
        context, sources = retrieval.format_evidence(docs, scope)
        self.assertIn("financial.pdf (page 2)", context)
        self.assertTrue(sources)

    def test_chat_followup_cites_evidence_and_abstains(self):
        with patch("services.rag_indexing.get_embeddings", return_value=FakeEmbeddings()):
            scope = self.index_docs([
                Document(page_content="Revenue increased to $125 million in 2024.", metadata={"source": "report.pdf", "page": 3}),
                Document(page_content="Operating margin was 18% in 2024.", metadata={"source": "report.pdf", "page": 4}),
            ])
        model = FakeChatModel([
            "Revenue reached $125 million [1].", "2024 operating margin",
            "Operating margin was 18% [1].", "weather forecast", "unsupported answer [99]",
        ])
        with patch.object(chat, "get_llm", return_value=model), patch.object(retrieval, "_get_reranker", return_value=FakeReranker()):
            client = TestClient(app)
            first = client.post("/api/chat/ask", json={"question": "What was revenue in 2024?", "session_id": "eval", "request_id": "req-1"})
            repeated = client.post("/api/chat/ask", json={"question": "What was revenue in 2024?", "session_id": "eval", "request_id": "req-1"})
            collision = client.post("/api/chat/ask", json={"question": "Different question", "session_id": "eval", "request_id": "req-1"})
            followup = client.post("/api/chat/ask", json={"question": "What about that year's margin?", "session_id": "eval", "request_id": "req-2"})
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(repeated.status_code, 200, repeated.text)
            self.assertEqual(first.json()["message_id"], repeated.json()["message_id"])
            self.assertEqual(collision.status_code, 409)
            self.assertEqual(followup.status_code, 200, followup.text)
            self.assertEqual(followup.json()["retrieval_query"], "2024 operating margin")
            self.assertIn("report.pdf (page", followup.json()["sources"][0])
            self.assertGreaterEqual(len(first.json()["sources"]), 2)
            self.assertTrue(first.json()["citations"])
            self.assertNotIn("[99]", followup.json()["answer"])
            detail = client.get("/api/v1/conversations/{}".format(first.json()["conversation_id"]))
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertEqual(len(detail.json()["messages"]), 4)
            self.assertEqual(detail.json()["messages"][1]["citations"][0]["source"], "report.pdf")
            page = client.get("/api/v1/conversations/{}?limit=2&offset=1".format(first.json()["conversation_id"]))
            self.assertEqual(len(page.json()["messages"]), 2)
            self.assertEqual(page.json()["message_total"], 4)
            cited_document_id = detail.json()["messages"][1]["citations"][0]["document_id"]
            deleted_document = client.delete("/api/v1/documents/{}".format(cited_document_id))
            self.assertEqual(deleted_document.status_code, 204, deleted_document.text)
            after_delete = client.get("/api/v1/conversations/{}".format(first.json()["conversation_id"]))
            old_citation = after_delete.json()["messages"][1]["citations"][0]
            self.assertEqual(old_citation["source"], "Source unavailable")
            self.assertIsNone(old_citation["document_id"])
            empty = client.post("/api/chat/ask", json={"question": "What is the weather?", "session_id": "new"})
        self.assertIn("couldn’t find sufficiently relevant evidence", empty.json()["answer"])
        self.assertEqual(empty.json()["sources"], [])

    def test_conversation_crud_and_owner_scoping(self):
        client = TestClient(app)
        created = client.post("/api/v1/conversations", json={"title": "Quarterly analysis"})
        self.assertEqual(created.status_code, 201, created.text)
        conversation_id = created.json()["id"]
        listed = client.get("/api/v1/conversations")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total"], 1)
        renamed = client.patch("/api/v1/conversations/{}".format(conversation_id), json={"title": "Annual analysis"})
        self.assertEqual(renamed.json()["title"], "Annual analysis")
        stranger = uuid4()
        with self.sessions() as db:
            other = User(id=stranger, email="other@example.test", hashed_password="test-hash")
            db.add(other)
            db.commit()
        # Exercise the dependency with a second authenticated principal.
        previous = app.dependency_overrides[get_current_user]
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=stranger, role="user")
        try:
            forbidden = client.get("/api/v1/conversations/{}".format(conversation_id))
            self.assertEqual(forbidden.status_code, 404)
        finally:
            app.dependency_overrides[get_current_user] = previous
        deleted = client.delete("/api/v1/conversations/{}".format(conversation_id))
        self.assertEqual(deleted.status_code, 204)

    def test_agent_compatibility_route_is_disabled(self):
        response = TestClient(app).post("/api/agent/analyze", json={"question": "analyze this"})
        self.assertEqual(response.status_code, 410)

    def test_chat_abstains_when_reranker_fails(self):
        with patch("services.rag_indexing.get_embeddings", return_value=FakeEmbeddings()):
            self.index_docs([Document(page_content="Revenue was $125 million in 2024.", metadata={"source": "report.pdf", "page": 0})])
        with patch.object(retrieval, "_get_reranker", side_effect=RuntimeError("offline")), patch.object(chat, "get_llm") as llm:
            response = TestClient(app).post("/api/chat/ask", json={"question": "What was revenue?"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["sources"], [])
        self.assertIn("couldn’t find sufficiently relevant evidence", response.json()["answer"])
        llm.assert_not_called()

    def test_provider_failure_preserves_user_message_and_records_failed_assistant(self):
        with patch("services.rag_indexing.get_embeddings", return_value=FakeEmbeddings()):
            self.index_docs([Document(page_content="Revenue was $125 million.", metadata={"source": "report.pdf", "page": 0})])
        with patch.object(chat, "get_llm", side_effect=RuntimeError("provider secret must not be returned")), \
                patch.object(retrieval, "_get_reranker", return_value=FakeReranker()):
            response = TestClient(app).post("/api/v1/chat/ask", json={
                "question": "What was revenue?", "session_id": "provider-failure", "request_id": "retryable-1"
            })
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("provider secret", response.text)
        with self.sessions() as db:
            conversation = db.query(Conversation).filter_by(legacy_session_id="provider-failure").one()
            rows = db.query(Message).filter_by(conversation_id=conversation.id).order_by("created_at").all()
        self.assertEqual([row.role for row in rows], ["user", "assistant"])
        self.assertEqual(rows[0].content, "What was revenue?")
        self.assertEqual(rows[1].status, "failed")
        self.assertNotIn("provider secret", rows[1].content)

    def test_reranker_loader_copies_checkpoint_tensors(self):
        class ModelWrapper:
            def __init__(self):
                self.model = torch.nn.Sequential(torch.nn.Linear(3, 2), torch.nn.LayerNorm(2))

        wrapper = ModelWrapper()
        parameter = next(wrapper.model.parameters())
        original_storage = parameter.data_ptr()
        returned = retrieval._materialize_model_tensors(wrapper)
        self.assertIs(returned, wrapper)
        self.assertNotEqual(next(wrapper.model.parameters()).data_ptr(), original_storage)


if __name__ == "__main__":
    unittest.main()
