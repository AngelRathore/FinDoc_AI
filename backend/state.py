"""
Shared in-memory state for the app.
In production, swap vectorstore for Pinecone/Qdrant and sessions for Redis.
"""
from typing import Optional, List
from threading import RLock
from langchain_community.vectorstores import FAISS

# Global vectorstore (one per server instance)
vectorstore: Optional[FAISS] = None
sources_loaded: list[str] = []
documents: list = []
bm25_index = None
indexed_document_ids: set[str] = set()
index_signature: tuple[str, ...] = ()
index_loaded = False
index_lock = RLock()


def set_vectorstore(vs: Optional[FAISS], sources: list[str], docs: Optional[List] = None,
                    keyword_index=None, document_ids: Optional[set[str]] = None,
                    signature: Optional[tuple[str, ...]] = None):
    global vectorstore, sources_loaded, documents, bm25_index, indexed_document_ids, index_loaded, index_signature
    with index_lock:
        vectorstore = vs
        sources_loaded = list(sources)
        documents = docs or []
        bm25_index = keyword_index
        indexed_document_ids = set(document_ids or ())
        index_signature = tuple(signature or ())
        index_loaded = True


def get_vectorstore() -> Optional[FAISS]:
    return vectorstore


def get_sources() -> list[str]:
    return sources_loaded


def get_documents() -> list:
    return documents


def get_bm25_index():
    return bm25_index


def clear_state():
    global vectorstore, sources_loaded, documents, bm25_index, indexed_document_ids, index_loaded, index_signature
    with index_lock:
        vectorstore = None
        sources_loaded = []
        documents = []
        bm25_index = None
        indexed_document_ids = set()
        index_signature = ()
        index_loaded = False
