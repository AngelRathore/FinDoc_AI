from fastapi import APIRouter

from routers import agent, auth, chat, conversations, documents, ingest, ingestion_jobs

router = APIRouter()
router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
router.include_router(ingest.router, prefix="/ingest", tags=["Ingest"])
router.include_router(documents.router, prefix="/documents", tags=["Documents"])
router.include_router(ingestion_jobs.router, prefix="/ingestion-jobs", tags=["Ingestion jobs"])
router.include_router(chat.router, prefix="/chat", tags=["Chat"])
router.include_router(conversations.router, prefix="/conversations", tags=["Conversations"])
router.include_router(agent.router, prefix="/agent", tags=["Agent"])
