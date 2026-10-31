"""Deterministic retrieval benchmark. Run with: python -m evaluation.phase6_eval"""
import json
import math
import re
from pathlib import Path
from uuid import UUID

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

import retrieval
import state
import config
from routers.chat import validate_citations


class HashEmbeddings(Embeddings):
    def _embed(self, text):
        vector = [0.0] * 256
        for token in retrieval._tokens(text):
            vector[sum(token.encode("utf-8")) % len(vector)] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_documents(self, texts):
        return [self._embed(text) for text in texts]

    def embed_query(self, text):
        return self._embed(text)


class FixedReranker:
    """Deterministic scorer for pipeline comparison; not a model-quality proxy."""
    def predict(self, pairs):
        return [float(len(set(retrieval._tokens(query)) & set(retrieval._tokens(text))))
                for query, text in pairs]


def _metrics(ranked, relevant, k=3):
    relevant = set(relevant)
    hits = [1 if item in relevant else 0 for item in ranked[:k]]
    recall = sum(hits) / len(relevant) if relevant else 1.0
    reciprocal = next((1 / (index + 1) for index, hit in enumerate(hits) if hit), 0.0)
    dcg = sum(hit / math.log2(index + 2) for index, hit in enumerate(hits))
    ideal_n = min(k, len(relevant))
    ideal = sum(1 / math.log2(index + 2) for index in range(ideal_n))
    return recall, reciprocal, dcg / ideal if ideal else 1.0


def run():
    dataset = json.loads((Path(__file__).parent / "phase6_eval.json").read_text())
    docs, owners, ids = [], {}, {}
    for row in dataset["documents"]:
        owner = UUID(int=1 if row["owner"] == "a" else 2)
        document_id = UUID(int=len(docs) + 10)
        chunk_id = "eval-" + row["id"]
        doc = Document(page_content=row["text"], metadata={
            "owner_id": str(owner), "document_id": str(document_id), "chunk_id": chunk_id,
            "source": row["source"], "page": row["page"],
        })
        docs.append(doc)
        owners[row["id"]] = (str(document_id), str(owner))
        ids[chunk_id] = row["id"]
    embeddings = HashEmbeddings()
    vectors = embeddings.embed_documents([doc.page_content for doc in docs])
    vs = FAISS.from_embeddings([(doc.page_content, vector) for doc, vector in zip(docs, vectors)],
                                embeddings, metadatas=[doc.metadata for doc in docs],
                                ids=[doc.metadata["chunk_id"] for doc in docs])
    state.set_vectorstore(vs, [], docs, retrieval.build_bm25_index(docs),
                          {doc.metadata["document_id"] for doc in docs})
    old_reranker = retrieval._get_reranker
    old_threshold = config.RERANK_THRESHOLD
    retrieval._get_reranker = lambda: FixedReranker()
    # Calibrated only for this deterministic token-overlap scorer; production
    # cross-encoder scores are not modified by this benchmark.
    config.RERANK_THRESHOLD = 3.0
    totals = {name: [0.0, 0.0, 0.0] for name in ("semantic", "bm25", "hybrid", "reranked")}
    citations_valid = grounded = abstentions = answerable = 0
    try:
        for case in dataset["cases"]:
            scope = {doc_id: owner for doc_id, owner in owners.values()
                     if owner == str(UUID(int=1 if case["owner"] == "a" else 2))
                     and doc_id not in {owners[x][0] for x in case.get("exclude", [])}}
            query = case["standalone"]
            semantic = retrieval.semantic_search(query, scope, 10)
            bm25 = retrieval.bm25_search(query, scope, 10)
            sem_rank = [ids[item] for item, _ in semantic]
            bm_rank = [ids[item] for item, _ in bm25]
            fused_score = {}
            for rank, (chunk_id, _) in enumerate(semantic, 1):
                fused_score[chunk_id] = fused_score.get(chunk_id, 0) + 1 / (60 + rank)
            for rank, (chunk_id, _) in enumerate(bm25, 1):
                fused_score[chunk_id] = fused_score.get(chunk_id, 0) + 1 / (60 + rank)
            hybrid = [ids[key] for key in sorted(fused_score, key=fused_score.get, reverse=True)]
            result = retrieval.retrieve_detailed(query, scope, candidate_k=10, final_k=10)
            reranked = [doc.metadata["chunk_id"] for doc in result.documents]
            rerank_ids = [ids[item] for item in reranked]
            if case["answerable"]:
                for label, ranking in (("semantic", sem_rank), ("bm25", bm_rank),
                                       ("hybrid", hybrid), ("reranked", rerank_ids)):
                    values = _metrics(ranking, case["relevant"])
                    totals[label] = [a + b for a, b in zip(totals[label], values)]
            expected_ids = set(case["relevant"])
            if case["answerable"]:
                answerable += 1
                context, citation_labels = retrieval.format_evidence(result.documents, scope) if result.documents else ("", [])
                cite_index = next((index for index, doc in enumerate(result.documents)
                                   if ids[doc.metadata["chunk_id"]] in expected_ids), None)
                has_evidence = cite_index is not None
                simulated = "{} [{}]".format(case["expected"], cite_index + 1) if has_evidence else ""
                checked = validate_citations(simulated, citation_labels)
                citations_valid += int(has_evidence and checked == simulated and bool(context))
                grounded += int(has_evidence and case["expected"] in result.documents[cite_index].page_content)
            else:
                abstentions += int(not result.documents)
    finally:
        retrieval._get_reranker = old_reranker
        config.RERANK_THRESHOLD = old_threshold
        state.clear_state()
    count = answerable
    print("case_count={}; answerable_cases={}; fixed_k=3; reranker=token-overlap test double".format(
        len(dataset["cases"]), answerable))
    for name, values in totals.items():
        print("{} Recall@3={:.3f} MRR={:.3f} nDCG@3={:.3f}".format(
            name, *(value / count for value in values)))
    print("Citation evidence validity={:.3f}; deterministic numeric/text grounding={:.3f}; unanswerable abstention={:.3f}".format(
        citations_valid / answerable, grounded / answerable,
        abstentions / sum(not row["answerable"] for row in dataset["cases"])))


if __name__ == "__main__":
    run()
