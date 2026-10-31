"""Indexed hybrid retrieval with stable chunk identity and diagnostic reranking."""
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Mapping
from uuid import UUID

from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

import config
import state

logger = logging.getLogger(__name__)
_reranker = None


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class BM25Index:
    """BM25 corpus statistics and token frequencies computed once per ingestion."""
    def __init__(self, docs: list[Document], k1: float = 1.5, b: float = 0.75):
        self.chunk_ids = [doc.metadata["chunk_id"] for doc in docs]
        self.frequencies = [Counter(_tokens(doc.page_content)) for doc in docs]
        self.lengths = [sum(freq.values()) for freq in self.frequencies]
        self.avg_len = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        self.doc_freq = Counter(term for freq in self.frequencies for term in freq)
        self.k1 = k1
        self.b = b

    def search(self, query: str, limit: int, allowed_chunk_ids: set[str]) -> list[tuple[str, float]]:
        query_terms = set(_tokens(query))
        if not query_terms or not self.frequencies:
            return []
        eligible = [index for index, chunk_id in enumerate(self.chunk_ids) if chunk_id in allowed_chunk_ids]
        if not eligible:
            return []
        # Scope corpus size, document frequencies, and average length too. Other
        # users' documents must not affect even the authorized candidates' scores.
        scoped_doc_freq = Counter(term for index in eligible for term in self.frequencies[index])
        scoped_avg_len = sum(self.lengths[index] for index in eligible) / len(eligible)
        scored = []
        count = len(eligible)
        for index in eligible:
            freq = self.frequencies[index]
            score = 0.0
            length = self.lengths[index]
            for term in query_terms:
                tf = freq[term]
                if not tf:
                    continue
                df = scoped_doc_freq[term]
                idf = math.log(1 + (count - df + 0.5) / (df + 0.5))
                denominator = tf + self.k1 * (1 - self.b + self.b * length / (scoped_avg_len or 1))
                score += idf * tf * (self.k1 + 1) / denominator
            if score > 0:
                scored.append((self.chunk_ids[index], score))
        return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]


@dataclass
class RetrievalResult:
    documents: List[Document]
    rerank_scores: dict
    rerank_error: str = ""


class AuthorizationScopeError(RuntimeError):
    """Raised when the scoped FAISS candidate search cannot be verified safely."""


def build_bm25_index(docs: list[Document]) -> BM25Index:
    return BM25Index(docs)


def _materialize_model_tensors(model):
    """Copy checkpoint-backed tensors into owned memory before CPU inference."""
    for parameter in model.model.parameters():
        parameter.data = parameter.data.clone()
    for buffer in model.model.buffers():
        buffer.data = buffer.data.clone()
    return model


def _get_reranker():
    global _reranker
    if _reranker is None:
        model = CrossEncoder(config.RERANK_MODEL, device="cpu")
        # In this runtime, CPU ops over checkpoint-backed tensors returned NaNs;
        # owned copies produce finite scores and preserve the same trained weights.
        _reranker = _materialize_model_tensors(model)
    return _reranker


def _authorized_document(doc: Document, scope: Mapping[str, str]) -> bool:
    metadata = doc.metadata or {}
    document_id = metadata.get("document_id")
    owner_id = metadata.get("owner_id")
    if not isinstance(document_id, str) or not isinstance(owner_id, str):
        return False
    try:
        normalized_doc_id = str(UUID(document_id))
        normalized_owner_id = str(UUID(owner_id))
        normalized_scope_owner = scope.get(normalized_doc_id)
        return normalized_scope_owner is not None and normalized_owner_id == str(UUID(normalized_scope_owner))
    except (ValueError, TypeError, AttributeError):
        return False


def semantic_search(query: str, authorized_document_owners: Mapping[str, str],
                    candidate_k: int = None) -> list[tuple[str, float]]:
    vs = state.get_vectorstore()
    if vs is None:
        return []
    if not authorized_document_owners:
        return []
    # The installed LangChain FAISS wrapper applies metadata filters only after its
    # global top fetch_k. Construct a temporary exact IndexFlatL2 containing only
    # verified authorized vectors, then search that index. No unowned vector can
    # enter the semantic candidate set, and no relevant owned vector is missed by
    # a small global top-K followed by filtering.
    try:
        import numpy as np
        from langchain_community.vectorstores.faiss import dependable_faiss_import

        faiss = dependable_faiss_import()
        if vs.index.metric_type != faiss.METRIC_L2:
            raise AuthorizationScopeError("Unexpected FAISS metric for scoped search")
        by_id = {doc.metadata.get("chunk_id"): doc for doc in state.get_documents()
                 if isinstance(doc.metadata, dict) and doc.metadata.get("chunk_id")}
        verified = []
        for position, chunk_id in vs.index_to_docstore_id.items():
            doc = by_id.get(chunk_id)
            if doc is None or not _authorized_document(doc, authorized_document_owners):
                continue
            if position < 0 or position >= vs.index.ntotal:
                raise AuthorizationScopeError("FAISS index mapping is inconsistent")
            vector = vs.index.reconstruct(int(position))
            verified.append((chunk_id, vector))
        if not verified:
            return []
        dimension = len(verified[0][1])
        scoped_index = faiss.IndexFlatL2(dimension)
        scoped_index.add(np.asarray([vector for _, vector in verified], dtype=np.float32))
        query_vector = np.asarray([vs._embed_query(query)], dtype=np.float32)
        if vs._normalize_L2:
            faiss.normalize_L2(query_vector)
        count = min(candidate_k or config.RETRIEVAL_CANDIDATES, len(verified))
        scores, local_indices = scoped_index.search(query_vector, count)
        return [(verified[int(index)][0], -float(score))
                for score, index in zip(scores[0], local_indices[0]) if int(index) >= 0]
    except AuthorizationScopeError:
        raise
    except Exception as exc:
        logger.exception("Scoped FAISS search failed closed")
        raise AuthorizationScopeError("Authorized semantic search is unavailable") from exc


def bm25_search(query: str, authorized_document_owners: Mapping[str, str],
                candidate_k: int = None) -> list[tuple[str, float]]:
    index = state.get_bm25_index()
    if index is None or not authorized_document_owners:
        return []
    by_id = {doc.metadata.get("chunk_id"): doc for doc in state.get_documents()
             if isinstance(doc.metadata, dict) and doc.metadata.get("chunk_id")}
    allowed = {chunk_id for chunk_id, doc in by_id.items()
               if _authorized_document(doc, authorized_document_owners)}
    return index.search(query, candidate_k or config.RETRIEVAL_CANDIDATES, allowed)


def retrieve_detailed(query: str, authorized_document_owners: Mapping[str, str],
                      candidate_k: int = None, final_k: int = None) -> RetrievalResult:
    docs = state.get_documents()
    if not authorized_document_owners or state.get_vectorstore() is None or not docs:
        return RetrievalResult([],{})
    k = candidate_k or config.RETRIEVAL_CANDIDATES
    final_k = final_k or config.FINAL_CHUNKS
    by_id = {doc.metadata["chunk_id"]: doc for doc in docs
             if isinstance(doc.metadata, dict) and doc.metadata.get("chunk_id")
             and _authorized_document(doc, authorized_document_owners)}

    semantic = semantic_search(query, authorized_document_owners, k)
    lexical = bm25_search(query, authorized_document_owners, k)
    semantic_ranks = {chunk_id: rank for rank, (chunk_id, _) in enumerate(semantic, 1)}
    lexical_ranks = {chunk_id: rank for rank, (chunk_id, _) in enumerate(lexical, 1)}
    fused_ids = (set(semantic_ranks) | set(lexical_ranks)) & set(by_id)
    rrf = {
        chunk_id: 1 / (60 + semantic_ranks.get(chunk_id, 1_000_000))
        + 1 / (60 + lexical_ranks.get(chunk_id, 1_000_000))
        for chunk_id in fused_ids
    }
    candidates = [by_id[chunk_id] for chunk_id in sorted(fused_ids, key=lambda cid: rrf[cid], reverse=True)]
    if not candidates:
        return RetrievalResult([], {})

    try:
        candidates = [doc for doc in candidates if _authorized_document(doc, authorized_document_owners)]
        scores = _get_reranker().predict([(query, doc.page_content) for doc in candidates])
        if any(not math.isfinite(float(score)) for score in scores):
            raise ValueError("cross-encoder returned a non-finite relevance score")
        ranked = sorted(zip(scores, candidates), key=lambda pair: float(pair[0]), reverse=True)
        selected = [(float(score), doc) for score, doc in ranked
                    if float(score) >= config.RERANK_THRESHOLD
                    and _authorized_document(doc, authorized_document_owners)][:final_k]
        all_scores = {doc.metadata["chunk_id"]: float(score) for score, doc in ranked}
        return RetrievalResult([doc for _, doc in selected], all_scores)
    except Exception as exc:
        # Without a valid relevance score, do not send candidates to the answer model.
        error = "Cross-encoder reranking failed: {}".format(exc)
        logger.exception(error)
        return RetrievalResult([], {}, error)


def retrieve(query: str, authorized_document_owners: Mapping[str, str],
             candidate_k: int = None, final_k: int = None) -> list[Document]:
    """Compatibility helper used by the agent tools and existing callers."""
    return retrieve_detailed(query, authorized_document_owners, candidate_k, final_k).documents


def format_evidence(docs: list[Document], authorized_document_owners: Mapping[str, str],
                    max_chars: int = None) -> tuple[str, list[str]]:
    """Deduplicate exact repeated passages while retaining distinct source/page citations."""
    if not authorized_document_owners or any(not _authorized_document(doc, authorized_document_owners) for doc in docs):
        raise AuthorizationScopeError("Evidence contains a document outside the authorized scope")
    budget = max_chars or config.CONTEXT_CHAR_BUDGET
    blocks, citations, seen, used = [], [], set(), 0
    for doc in docs:
        chunk_id = doc.metadata.get("chunk_id")
        key = chunk_id or (doc.metadata.get("source"), doc.metadata.get("page"), doc.page_content)
        if key in seen:
            continue
        seen.add(key)
        source = str(doc.metadata.get("source", "Unknown source"))
        page = doc.metadata.get("page")
        label = source if page is None else "{} (page {})".format(source, int(page) + 1)
        citation = "[{}]".format(len(citations) + 1)
        body = doc.page_content.strip()
        remaining = budget - used
        if remaining <= len(citation) + len(label) + 4:
            break
        body = body[:remaining - len(citation) - len(label) - 5]
        block = "{} {}\n{}".format(citation, label, body)
        blocks.append(block)
        citations.append("{} {}".format(citation, label))
        used += len(block) + 2
    return "\n\n".join(blocks), citations
