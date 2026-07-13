from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from agents.financial_agent import run_agent

router = APIRouter()


class AgentRequest(BaseModel):
    question: str


@router.post("/analyze")
async def analyze(req: AgentRequest):
    """
    Run the LangGraph Financial Analysis Agent.
    Returns answer + reasoning steps + stock data if applicable.
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    try:
        result = run_agent(req.question)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))