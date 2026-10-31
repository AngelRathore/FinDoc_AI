"""Backward-compatible settings exports used by the existing RAG modules."""
from core.config import settings

CHUNK_SIZE = settings.chunk_size
CHUNK_OVERLAP = settings.chunk_overlap
RETRIEVAL_CANDIDATES = settings.retrieval_candidates
FINAL_CHUNKS = settings.final_chunks
RERANK_THRESHOLD = settings.rerank_threshold
RERANK_MODEL = settings.rerank_model
CONTEXT_CHAR_BUDGET = settings.context_char_budget
GROQ_MODEL = settings.groq_model
