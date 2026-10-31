"""Typed application settings loaded from environment and backend/.env."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "FinDoc AI"
    app_version: str = "1.0.0"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str | None = None
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-20b"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    jwt_secret_key: SecretStr | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=15, ge=1, le=1440)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)
    auth_cookie_secure: bool = False

    document_storage_dir: Path = BACKEND_DIR / "storage" / "documents"
    max_upload_size_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    celery_broker_url: str = Field(default="redis://localhost:6379/0", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/1", alias="CELERY_RESULT_BACKEND")
    celery_task_max_retries: int = Field(default=3, alias="CELERY_TASK_MAX_RETRIES", ge=0, le=10)
    celery_task_soft_time_limit: int = Field(default=600, alias="CELERY_TASK_SOFT_TIME_LIMIT", ge=30)
    celery_task_time_limit: int = Field(default=660, alias="CELERY_TASK_TIME_LIMIT", ge=30)

    chunk_size: int = Field(default=1000, alias="FINDOC_CHUNK_SIZE", ge=1)
    chunk_overlap: int = Field(default=150, alias="FINDOC_CHUNK_OVERLAP", ge=0)
    retrieval_candidates: int = Field(default=12, alias="FINDOC_RETRIEVAL_CANDIDATES", ge=1)
    final_chunks: int = Field(default=4, alias="FINDOC_FINAL_CHUNKS", ge=1)
    rerank_threshold: float = Field(default=0.0, alias="FINDOC_RERANK_THRESHOLD")
    rerank_model: str = Field(default="cross-encoder/ms-marco-MiniLM-L-6-v2", alias="FINDOC_RERANK_MODEL")
    context_char_budget: int = Field(default=12000, alias="FINDOC_CONTEXT_CHAR_BUDGET", ge=1)
    chat_history_messages: int = Field(default=8, alias="CHAT_HISTORY_MESSAGES", ge=2, le=40)

    @model_validator(mode="after")
    def validate_production_settings(self):
        if self.environment.strip().lower() == "production":
            missing = []
            if not self.database_url:
                missing.append("DATABASE_URL")
            if not self.groq_api_key:
                missing.append("GROQ_API_KEY")
            secret = self.jwt_secret_key.get_secret_value() if self.jwt_secret_key else ""
            if len(secret.encode("utf-8")) < 32:
                missing.append("JWT_SECRET_KEY (at least 32 bytes)")
            if not self.auth_cookie_secure:
                missing.append("AUTH_COOKIE_SECURE=true")
            if not self.cors_origins or "*" in self.cors_origins:
                missing.append("CORS_ORIGINS (explicit origins)")
            if missing:
                raise ValueError("Production configuration is incomplete: " + ", ".join(missing))
        return self

    @field_validator("document_storage_dir", mode="before")
    @classmethod
    def resolve_document_storage_dir(cls, value):
        path = Path(value).expanduser()
        return path if path.is_absolute() else BACKEND_DIR / path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
