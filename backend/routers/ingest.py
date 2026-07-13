import os
import tempfile
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from langchain_community.document_loaders import (
    WebBaseLoader,
    PyPDFLoader,
    
    TextLoader,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

import state

router = APIRouter()


def get_embeddings():
    return HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def build_vectorstore(docs: list, sources: list[str]):
    # Clear old state first
    state.clear_state()
    
    splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ". ", " "],
        chunk_size=1000,
        chunk_overlap=150,
    )
    chunks = splitter.split_documents(docs)
    embeddings = get_embeddings()
    vs = FAISS.from_documents(chunks, embeddings)
    state.set_vectorstore(vs, sources)
    return len(chunks)


# ── URL ingestion ──────────────────────────────────────────────────────────────
class URLPayload(BaseModel):
    urls: list[str]


@router.post("/urls")
async def ingest_urls(payload: URLPayload):
    docs = []
    failed = []
    for url in payload.urls:
        try:
            loader = WebBaseLoader([url])
            loader.requests_kwargs = {"timeout": 15}
            docs.extend(loader.load())
        except Exception as e:
            failed.append({"url": url, "error": str(e)})

    if not docs:
        raise HTTPException(status_code=400, detail="No content extracted from URLs")

    chunks = build_vectorstore(docs, payload.urls)
    return {
        "status": "success",
        "chunks": chunks,
        "sources": payload.urls,
        "failed": failed,
    }




# ── PDF ingestion ──────────────────────────────────────────────────────────────
@router.post("/pdf")
async def ingest_pdf(files: list[UploadFile] = File(...)):
    docs = []
    labels = []
    failed = []
    for f in files:
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                content = await f.read()
                tmp.write(content)
                tmp_path = tmp.name
            
            # Load AFTER file is closed and written
            loader = PyPDFLoader(tmp_path)
            loaded = loader.load()
            
            # Add filename as metadata source
            for doc in loaded:
                doc.metadata["source"] = f.filename
            
            docs.extend(loaded)
            labels.append(f"PDF: {f.filename}")
            os.unlink(tmp_path)
        except Exception as e:
            failed.append({"file": f.filename, "error": str(e)})

    if not docs:
        raise HTTPException(status_code=400, detail="No content extracted from PDFs")

    chunks = build_vectorstore(docs, labels)
    return {"status": "success", "chunks": chunks, "sources": labels, "failed": failed}


# ── TXT ingestion ──────────────────────────────────────────────────────────────
@router.post("/txt")
async def ingest_txt(files: list[UploadFile] = File(...)):
    docs = []
    labels = []
    failed = []
    for f in files:
        try:
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".txt", mode="wb"
            ) as tmp:
                tmp.write(await f.read())
                tmp_path = tmp.name
            loader = TextLoader(tmp_path, encoding="utf-8")
            docs.extend(loader.load())
            labels.append(f"TXT: {f.filename}")
            os.unlink(tmp_path)
        except Exception as e:
            failed.append({"file": f.filename, "error": str(e)})

    if not docs:
        raise HTTPException(status_code=400, detail="No content extracted from TXT files")

    chunks = build_vectorstore(docs, labels)
    return {"status": "success", "chunks": chunks, "sources": labels, "failed": failed}


# ── Status ─────────────────────────────────────────────────────────────────────
@router.get("/status")
def ingest_status():
    vs = state.get_vectorstore()
    return {
        "ready": vs is not None,
        "sources": state.get_sources(),
        "source_count": len(state.get_sources()),
    }


@router.delete("/clear")
def clear_ingest():
    state.clear_state()
    return {"status": "cleared"}