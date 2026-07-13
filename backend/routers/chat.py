from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferMemory
from langchain_groq import ChatGroq
import os
import state

router = APIRouter()

# In-memory chat histories keyed by session_id
_sessions: dict[str, dict] = {}


def get_llm():
    return ChatGroq(
        model_name="llama-3.1-8b-instant",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.7,
        max_tokens=800,
    )


def get_or_create_chain(session_id: str):
    vs = state.get_vectorstore()
    if vs is None:
        raise HTTPException(status_code=400, detail="No sources loaded. Please ingest first.")

    memory = ConversationBufferMemory(
        memory_key="chat_history",
        return_messages=True,
        output_key="answer",
    )
    chain = ConversationalRetrievalChain.from_llm(
        llm=get_llm(),
        retriever=vs.as_retriever(search_kwargs={"k": 3}),
        memory=memory,
        return_source_documents=True,
        verbose=False,
    )
    _sessions[session_id] = {"chain": chain, "memory": memory, "history": []}

    return _sessions[session_id]

class ChatRequest(BaseModel):
    question: str
    session_id: str = "default"


class ClearRequest(BaseModel):
    session_id: str = "default"


@router.post("/ask")
async def ask(req: ChatRequest):
    session = get_or_create_chain(req.session_id)
    chain = session["chain"]

    try:
        result = chain({"question": req.question})
        answer = result.get("answer", "No answer found.")
        source_docs = result.get("source_documents", [])

        seen = set()
        sources = []
        for doc in source_docs:
            src = doc.metadata.get("source", "")
            if src and src not in seen:
                seen.add(src)
                sources.append(src)

        session["history"].append({"role": "user", "content": req.question})
        session["history"].append({"role": "ai", "content": answer, "sources": sources})

        return {"answer": answer, "sources": sources, "session_id": req.session_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{session_id}")
def get_history(session_id: str):
    if session_id not in _sessions:
        return {"history": []}
    return {"history": _sessions[session_id]["history"]}


@router.post("/clear")
def clear_chat(req: ClearRequest):
    if req.session_id in _sessions:
        del _sessions[req.session_id]
    return {"status": "cleared", "session_id": req.session_id}