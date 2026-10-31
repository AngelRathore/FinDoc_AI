from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    file_type: str
    content_type: str
    file_size: int
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    ingestion_job_id: UUID | None = None
    ingestion_job_status: str | None = None


class DocumentAcceptedResponse(BaseModel):
    id: UUID
    document_id: UUID
    job_id: UUID
    status: str
    status_url: str = ""


class IngestionJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    status: str
    attempt_count: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime
    status_url: str = ""


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    limit: int
    offset: int


class AdminDocumentResponse(BaseModel):
    """Upload metadata for admin oversight; never includes stored content or path."""
    id: UUID
    owner_id: UUID
    owner_email: str
    original_filename: str
    file_type: str
    file_size: int
    status: str
    ingestion_job_status: str | None = None
    created_at: datetime
    updated_at: datetime


class AdminDocumentListResponse(BaseModel):
    items: list[AdminDocumentResponse]
    total: int
    limit: int
    offset: int


class DocumentListParams(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
