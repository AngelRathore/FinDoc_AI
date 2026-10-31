"""Reusable synchronous SQLAlchemy engine and request-scoped sessions."""
from functools import lru_cache
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import settings


class DatabaseNotConfigured(RuntimeError):
    pass


def _driver_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@lru_cache(maxsize=4)
def _engine_for(url: str) -> Engine:
    return create_engine(_driver_url(url), pool_pre_ping=True, future=True)


def get_engine() -> Engine:
    if not settings.database_url:
        raise DatabaseNotConfigured("DATABASE_URL is not configured")
    return _engine_for(settings.database_url)


def get_db() -> Generator[Session, None, None]:
    session_factory = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
