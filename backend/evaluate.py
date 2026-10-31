"""Evaluate retrieval strategies with Recall@K, MRR, and nDCG@K."""
import argparse
import json
import math
from pathlib import Path
from uuid import UUID, uuid5, NAMESPACE_URL

from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

import config
import state
import retrieval


def reciprocal_rank_fusion(semantic, lexical):
    ranks = {}
    for ranked in (semantic, lexical):
        for rank, (chunk_id, _) in enumerate(ranked, 1):
            ranks[chunk_id] = ranks.get(chunk_id, 0.0) + 1.0 / (60 + rank)
    return [chunk_id for chunk_id, _ in sorted(ranks.items(), key=lambda pair: pair[1], reverse=True)]


def metrics(ranked_ids, relevant_ids, k):
    relevant = set(relevant_ids)
    if not relevant:
        return None
    top = ranked_ids[:k]
    hits = [1 if chunk_id in relevant else 0 for chunk_id in top]
    recall = sum(hits) / len(relevant)
    mrr = next((1.0 / index for index, hit in enumerate(hits, 1) if hit), 0.0)
    dcg = sum(hit / math.log2(index + 1) for index, hit in enumerate(hits, 1))
    ideal = sum(1.0 / math.log2(index + 1) for index in range(1, min(k, len(relevant)) + 1))
    return recall, mrr, dcg / ideal if ideal else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evaluation/financial_qa.json")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    dataset_path = Path(args.dataset)
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    source_documents = {}
    owner_id = str(UUID(int=1))
    docs = []
    for item in payload["documents"]:
        document_id = source_documents.setdefault(item["source"], str(uuid5(NAMESPACE_URL, item["source"])))
        docs.append(Document(page_content=item["text"], metadata={
            "chunk_id": item["id"], "source": item["source"], "page": item["page"],
            "owner_id": owner_id, "document_id": document_id,
        }))
    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
    ids = [doc.metadata["chunk_id"] for doc in docs]
    vs = FAISS.from_documents(docs, embeddings, ids=ids)
    authorized_scope = {doc.metadata["document_id"]: owner_id for doc in docs}
    state.set_vectorstore(vs, list({doc.metadata["source"] for doc in docs}), docs,
                          retrieval.build_bm25_index(docs), set(authorized_scope))

    names = ("semantic", "bm25", "hybrid", "reranked")
    totals = {name: [0.0, 0.0, 0.0] for name in names}
    counts = {name: 0 for name in names}
    rerank_warnings = 0
    for query in payload["queries"]:
        question = query["question"]
        relevant = query["relevant_ids"]
        semantic = retrieval.semantic_search(question, authorized_scope, max(args.k, config.RETRIEVAL_CANDIDATES))
        lexical = retrieval.bm25_search(question, authorized_scope, max(args.k, config.RETRIEVAL_CANDIDATES))
        hybrid = reciprocal_rank_fusion(semantic, lexical)
        result = retrieval.retrieve_detailed(question, authorized_scope,
                                             max(args.k, config.RETRIEVAL_CANDIDATES), args.k)
        if args.debug:
            print("DEBUG {!r}: semantic={} bm25={} reranked={} scores={} warning={}".format(
                question, len(semantic), len(lexical), [d.metadata["chunk_id"] for d in result.documents],
                result.rerank_scores, result.rerank_error,
            ))
        ranked = {
            "semantic": [item[0] for item in semantic],
            "bm25": [item[0] for item in lexical],
            "hybrid": hybrid,
            "reranked": [doc.metadata["chunk_id"] for doc in result.documents],
        }
        rerank_warnings += bool(result.rerank_error)
        for name, ids_ranked in ranked.items():
            values = metrics(ids_ranked, relevant, args.k)
            if values is not None:
                totals[name] = [a + b for a, b in zip(totals[name], values)]
                counts[name] += 1
    for name in names:
        denom = counts[name] or 1
        recall, mrr, ndcg = (value / denom for value in totals[name])
        print("{}: Recall@{}={:.3f} MRR={:.3f} nDCG@{}={:.3f} ({} queries)".format(name, args.k, recall, mrr, args.k, ndcg, counts[name]))
    if rerank_warnings:
        print("Reranker failed on {} query(s); fail-closed empty results were scored for reranked retrieval.".format(rerank_warnings))
    state.clear_state()


if __name__ == "__main__":
    main()
