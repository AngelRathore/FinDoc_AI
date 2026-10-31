"""Compatibility endpoint retained while the experimental agent stays disabled."""
from fastapi import APIRouter, HTTPException
from schemas.agent import AgentRequest

router = APIRouter()


@router.post("/analyze")
async def analyze(req: AgentRequest):
    raise HTTPException(status_code=410, detail="AI Agent is disabled. Use /api/chat/ask for document-grounded RAG.")
