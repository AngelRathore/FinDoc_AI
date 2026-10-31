"""FastAPI application entry point; RAG implementation stays in its modules."""
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from api.v1.router import router as v1_router
from core.config import settings
from core.errors import install_exception_handlers
from core.logging import configure_logging
from db.session import DatabaseNotConfigured
from schemas.health import HealthResponse, ReadinessResponse
from services.health import database_is_ready

configure_logging(settings.log_level)
logger = logging.getLogger("findocai.http")

app = FastAPI(title=settings.app_name,
              description="Financial document Q&A with hybrid retrieval and grounded citations",
              version=settings.app_version,
              docs_url="/docs" if settings.environment.lower() == "development" else None,
              redoc_url="/redoc" if settings.environment.lower() == "development" else None,
              openapi_url="/openapi.json" if settings.environment.lower() == "development" else None)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
install_exception_handlers(app)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info("Request completed", extra={
        "request_id": request_id, "method": request.method, "path": request.url.path,
        "status_code": response.status_code,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    })
    return response


# Versioned paths for new clients, plus legacy paths used by the current React app.
app.include_router(v1_router, prefix="/api/v1")
app.include_router(v1_router, prefix="/api", include_in_schema=False)


@app.get("/", tags=["Health"])
def root():
    return {"status": "FinDoc AI backend running"}


@app.get("/health", response_model=HealthResponse, tags=["Health"])
def health():
    return {"status": "ok"}


@app.get("/ready", response_model=ReadinessResponse, tags=["Health"])
def readiness():
    try:
        database_is_ready()
    except DatabaseNotConfigured:
        raise HTTPException(status_code=503, detail="Database is not configured")
    except Exception:
        logger.exception("Database readiness check failed")
        raise HTTPException(status_code=503, detail="Database is unavailable")
    return {"status": "ready", "database": "ok"}
