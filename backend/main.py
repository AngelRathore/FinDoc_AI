import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from routers import ingest, chat, agent

load_dotenv()

app = FastAPI(
    title="FinDoc AI",
    description="Financial Document Analysis with LangGraph Agent",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router, prefix="/api/ingest", tags=["Ingest"])
app.include_router(chat.router,   prefix="/api/chat",   tags=["Chat"])
app.include_router(agent.router,  prefix="/api/agent",  tags=["Agent"])


@app.get("/")
def root():
    return {"status": "FinDoc AI backend running"}


@app.get("/health")
def health():
    return {"status": "ok"}