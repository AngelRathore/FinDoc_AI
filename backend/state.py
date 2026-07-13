"""
Shared in-memory state for the app.
In production, swap vectorstore for Pinecone/Qdrant and sessions for Redis.
"""
from typing import Optional
from langchain_community.vectorstores import FAISS

# Global vectorstore (one per server instance)
vectorstore: Optional[FAISS] = None
sources_loaded: list[str] = []


def set_vectorstore(vs: FAISS, sources: list[str]):
    global vectorstore, sources_loaded
    vectorstore = vs
    sources_loaded = sources


def get_vectorstore() -> Optional[FAISS]:
    return vectorstore


def get_sources() -> list[str]:
    return sources_loaded


def clear_state():
    global vectorstore, sources_loaded
    vectorstore = None
    sources_loaded = []