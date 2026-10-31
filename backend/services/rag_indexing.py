"""Document extraction and shared FAISS/BM25 index construction."""
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from uuid import UUID, uuid4

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from pypdf import PdfReader

import config
from core.config import settings
from models.document import DocumentRecord
from retrieval import build_bm25_index


@lru_cache(maxsize=1)
def get_embeddings():
    return HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def storage_file(record: DocumentRecord) -> Path:
    """Resolve a stored, server-generated relative file name beneath the storage root."""
    root = Path(settings.document_storage_dir).expanduser().resolve()
    candidate = (root / record.storage_path).resolve()
    if candidate.parent != root or Path(record.storage_path).name != record.storage_path:
        raise ValueError("Invalid stored document path")
    return candidate


def extract_record(record: DocumentRecord) -> list[Document]:
    path = storage_file(record)
    if not path.is_file():
        raise FileNotFoundError("Stored document file is missing")

    source = record.original_filename
    if record.file_type == "pdf":
        pages = []
        reader = PdfReader(str(path))
        for page_number, page in enumerate(reader.pages):
            text = page.extract_text(extraction_mode="layout") or ""
            if text.strip():
                pages.append(Document(page_content=text, metadata={"source": source, "page": page_number}))
        return pages

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("Document contains no text")
    if record.file_type == "url":
        # URL text is retained locally so it can be re-indexed after a backend restart.
        return [Document(page_content=text, metadata={"source": source})]
    return [Document(page_content=text, metadata={"source": source})]


def chunk_record(record: DocumentRecord, source_docs: list[Document]) -> list[Document]:
    """Create chunks carrying trusted owner/document identities from the DB row."""
    document_id = str(record.id)
    owner_id = str(record.owner_id)
    if not document_id or not owner_id or record.status not in {"processing", "completed"}:
        raise ValueError("Document identity or state is invalid")

    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "heading_1"), ("##", "heading_2"), ("###", "heading_3")],
        strip_headers=False,
    )
    splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ". ", " "],
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )
    result: list[Document] = []
    ordinal = 0
    for page_number, source_doc in enumerate(source_docs):
        cleaned = "\n".join(line.rstrip() for line in source_doc.page_content.splitlines()).strip()
        if not cleaned:
            continue
        base_metadata = dict(source_doc.metadata)
        base_metadata["source"] = str(base_metadata.get("source") or record.original_filename)
        structured = header_splitter.split_text(cleaned) or [Document(page_content=cleaned)]
        for section_index, section in enumerate(structured):
            section.page_content = "\n".join(line.rstrip() for line in section.page_content.splitlines()).strip()
            section.metadata = {**base_metadata, **section.metadata}
            for chunk in splitter.split_documents([section]):
                chunk.page_content = chunk.page_content.strip()
                if not chunk.page_content:
                    continue
                page = base_metadata.get("page")
                identity = "\0".join((document_id, owner_id, str(page if page is not None else page_number),
                                       str(section_index), str(ordinal), chunk.page_content))
                chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                chunk.metadata = {
                    **base_metadata,
                    **chunk.metadata,
                    "owner_id": owner_id,
                    "document_id": document_id,
                    "chunk_id": chunk_id,
                }
                result.append(chunk)
                ordinal += 1
    return result


def build_indexes(chunks: list[Document], document_ids: set[str]):
    if not chunks:
        return None, [], None
    for chunk in chunks:
        metadata = chunk.metadata
        if not all(metadata.get(key) for key in ("owner_id", "document_id", "chunk_id", "source")):
            raise ValueError("Chunk is missing required ownership metadata")
        try:
            UUID(metadata["owner_id"])
            UUID(metadata["document_id"])
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Chunk ownership metadata is invalid") from exc
        if metadata["document_id"] not in document_ids:
            raise ValueError("Chunk document is outside the active index set")
    ids = [chunk.metadata["chunk_id"] for chunk in chunks]
    if len(set(ids)) != len(ids):
        raise ValueError("Chunk IDs must be unique")
    embeddings = get_embeddings()
    vectorstore = FAISS.from_documents(chunks, embeddings, ids=ids)
    return vectorstore, chunks, build_bm25_index(chunks)


def build_index_from_vectors(chunks: list[Document], vectors: list[list[float]], document_ids: set[str]):
    """Construct process-local FAISS/BM25 views from durable worker vectors."""
    if not chunks:
        return None, [], None
    if len(chunks) != len(vectors):
        raise ValueError("Index artifact has a mismatched vector count")
    seen: set[str] = set()
    for chunk, vector in zip(chunks, vectors):
        metadata = chunk.metadata
        if not all(metadata.get(key) for key in ("owner_id", "document_id", "chunk_id", "source")):
            raise ValueError("Chunk is missing required ownership metadata")
        try:
            UUID(metadata["owner_id"])
            UUID(metadata["document_id"])
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Chunk ownership metadata is invalid") from exc
        if metadata["document_id"] not in document_ids or metadata["chunk_id"] in seen:
            raise ValueError("Index artifact contains an invalid or duplicate chunk identity")
        if not vector or not all(isinstance(value, (int, float)) for value in vector):
            raise ValueError("Index artifact contains an invalid embedding vector")
        seen.add(metadata["chunk_id"])
    embeddings = get_embeddings()
    pairs = [(chunk.page_content, vector) for chunk, vector in zip(chunks, vectors)]
    vectorstore = FAISS.from_embeddings(
        pairs, embeddings, metadatas=[chunk.metadata for chunk in chunks],
        ids=[chunk.metadata["chunk_id"] for chunk in chunks],
    )
    return vectorstore, chunks, build_bm25_index(chunks)


def artifact_file(record: DocumentRecord) -> Path:
    root = Path(settings.document_storage_dir).expanduser().resolve()
    folder = root / ".indexes"
    if folder.parent != root:
        raise ValueError("Invalid index artifact directory")
    return folder / (str(record.id) + ".json")


def write_index_artifact(record: DocumentRecord, chunks: list[Document], vectors: list[list[float]]) -> None:
    """Atomically persist non-PostgreSQL chunks/vectors for API-process rebuilds."""
    if len(chunks) != len(vectors):
        raise ValueError("Cannot persist an incomplete index artifact")
    build_index_from_vectors(chunks, vectors, {str(record.id)})
    destination = artifact_file(record)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        destination.parent.chmod(0o700)
    except OSError:
        pass
    payload = {
        "format": 1,
        "document_id": str(record.id),
        "owner_id": str(record.owner_id),
        "chunks": [
            {"text": chunk.page_content, "metadata": chunk.metadata, "vector": vector}
            for chunk, vector in zip(chunks, vectors)
        ],
    }
    temporary = destination.parent / ("." + destination.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def load_index_artifact(record: DocumentRecord) -> tuple[list[Document], list[list[float]]]:
    path = artifact_file(record)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != 1 or data.get("document_id") != str(record.id) or data.get("owner_id") != str(record.owner_id):
        raise ValueError("Index artifact identity does not match its database record")
    chunks: list[Document] = []
    vectors: list[list[float]] = []
    for entry in data.get("chunks", []):
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("document_id") != str(record.id) or metadata.get("owner_id") != str(record.owner_id):
            raise ValueError("Index artifact chunk ownership does not match its database record")
        chunks.append(Document(page_content=entry["text"], metadata=metadata))
        vectors.append(entry["vector"])
    if not chunks:
        raise ValueError("Index artifact contains no searchable chunks")
    return chunks, vectors
