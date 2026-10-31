"""
LangGraph-based Financial Analysis Agent.

Flow:
  START → retrieve → grade → (good) → generate → END
                          → (bad)  → web_search → generate → END
"""
from __future__ import annotations

import os
from typing import TypedDict, Annotated, Sequence
import operator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END

from tools.financial_tools import (
    search_documents,
    web_search,
    get_stock_price,
    financial_calculator,
    ALL_TOOLS,
)

# ── LLM ───────────────────────────────────────────────────────────────────────
def get_agent_llm():
    return ChatGroq(
        model_name=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.3,
        max_tokens=1200,
    ).bind_tools(ALL_TOOLS)


# ── Agent state ───────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    question: str
    retrieved_docs: str
    web_results: str
    stock_data: str
    calc_result: str
    final_answer: str
    steps: list[str]


# ── Node: Retrieve from vector store ─────────────────────────────────────────
def retrieve_node(state: AgentState) -> AgentState:
    question = state["question"]
    result = search_documents.invoke(question)
    steps = state.get("steps", [])
    steps.append("📚 Searched loaded documents")
    return {**state, "retrieved_docs": result, "steps": steps}


# ── Node: Grade retrieved docs ────────────────────────────────────────────────
def grade_node(state: AgentState) -> str:
    """Router: decides next node based on doc quality."""
    docs = state.get("retrieved_docs", "")
    question = state["question"].lower()

    # If no docs or placeholder message → go to web search
    if "no documents loaded" in docs or "no relevant information" in docs:
        return "web_search"

    # If question is about live/current data → always web search
    live_keywords = ["current", "today", "latest", "now", "live", "price", "stock"]
    if any(kw in question for kw in live_keywords):
        return "web_search"

    return "generate"


# ── Node: Web search ──────────────────────────────────────────────────────────
def web_search_node(state: AgentState) -> AgentState:
    question = state["question"]
    result = web_search.invoke(question)
    steps = state.get("steps", [])
    steps.append("🌐 Searched the web for latest data")
    return {**state, "web_results": result, "steps": steps}


# ── Node: Stock price lookup ──────────────────────────────────────────────────
def stock_node(state: AgentState) -> AgentState:
    """Automatically extracts ticker symbols from the question and fetches prices."""
    import re
    question = state["question"]
    # Match common ticker patterns: 1-5 uppercase letters, optionally .NS .BO etc.
    tickers = re.findall(r"\b([A-Z]{1,5}(?:\.[A-Z]{1,3})?)\b", question)
    stock_results = []
    for ticker in tickers[:3]:  # max 3 tickers
        res = get_stock_price.invoke(ticker)
        if "failed" not in res.lower():
            stock_results.append(res)
    steps = state.get("steps", [])
    if stock_results:
        steps.append(f"📈 Fetched stock data for: {', '.join(tickers[:3])}")
    return {**state, "stock_data": "\n\n".join(stock_results), "steps": steps}


# ── Node: Calculator ──────────────────────────────────────────────────────────
def calc_node(state: AgentState) -> AgentState:
    """Runs calculator if question has math keywords."""
    question = state["question"].lower()
    calc_keywords = ["calculate", "roi", "cagr", "interest", "ratio", "return", "compute", "%"]
    steps = state.get("steps", [])
    if any(kw in question for kw in calc_keywords):
        # Let LLM figure out what to compute — we just flag it
        steps.append("🧮 Calculator tool available for this query")
    return {**state, "steps": steps}


# ── Node: Generate final answer ───────────────────────────────────────────────
def generate_node(state: AgentState) -> AgentState:
    from langchain_groq import ChatGroq

    llm = ChatGroq(
        model_name=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.5,
        max_tokens=1200,
    )

    question  = state["question"]
    docs      = state.get("retrieved_docs", "")
    web       = state.get("web_results", "")
    stock     = state.get("stock_data", "")
    calc      = state.get("calc_result", "")

    context_parts = []
    if docs and "no documents" not in docs.lower():
        context_parts.append(f"=== LOADED DOCUMENTS ===\n{docs}")
    if web and "failed" not in web.lower():
        context_parts.append(f"=== WEB SEARCH RESULTS ===\n{web}")
    if stock:
        context_parts.append(f"=== STOCK DATA ===\n{stock}")
    if calc:
        context_parts.append(f"=== CALCULATION ===\n{calc}")

    context = "\n\n".join(context_parts) if context_parts else "No additional context available."

    system_prompt = """You are FinDoc AI, an expert financial analyst assistant.
Use the provided context to give accurate, well-structured financial analysis.
Always cite your sources. If data is insufficient, say so clearly.
Format numbers clearly. Use bullet points for lists. Be concise but thorough."""

    prompt = f"""{system_prompt}

QUESTION: {question}

CONTEXT:
{context}

Provide a comprehensive financial analysis answer:"""

    response = llm.invoke(prompt)
    answer   = response.content

    steps = state.get("steps", [])
    steps.append("✅ Generated final answer")

    return {**state, "final_answer": answer, "steps": steps}


# ── Build the graph ────────────────────────────────────────────────────────────
def build_agent_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("retrieve",   retrieve_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("stock",      stock_node)
    graph.add_node("calc",       calc_node)
    graph.add_node("generate",   generate_node)

    graph.set_entry_point("retrieve")

    graph.add_conditional_edges(
        "retrieve",
        grade_node,
        {
            "generate":   "stock",
            "web_search": "web_search",
        },
    )

    graph.add_edge("web_search", "stock")
    graph.add_edge("stock",      "calc")
    graph.add_edge("calc",       "generate")
    graph.add_edge("generate",   END)

    return graph.compile()


# Singleton compiled graph
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_agent_graph()
    return _graph


def run_agent(question: str) -> dict:
    graph = get_graph()
    initial_state: AgentState = {
        "messages":      [HumanMessage(content=question)],
        "question":      question,
        "retrieved_docs": "",
        "web_results":   "",
        "stock_data":    "",
        "calc_result":   "",
        "final_answer":  "",
        "steps":         [],
    }
    final_state = graph.invoke(initial_state)
    return {
        "answer": final_state["final_answer"],
        "steps":  final_state["steps"],
        "stock":  final_state.get("stock_data", ""),
    }
