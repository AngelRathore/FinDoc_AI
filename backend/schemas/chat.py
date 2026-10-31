from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    # Kept for old clients; new clients send conversation_id.
    session_id: str | None = Field(default="default", min_length=1, max_length=128)
    conversation_id: UUID | None = None
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class MessageSend(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class CitationResponse(BaseModel):
    id: UUID
    position: int
    reference: str
    document_id: UUID | None
    chunk_id: str | None
    source: str
    page: int | None
    available: bool = True

    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    status: str
    created_at: datetime
    citations: list[CitationResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ConversationResponse(BaseModel):
    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    total: int
    limit: int
    offset: int


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse]
    message_total: int
    message_limit: int
    message_offset: int


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    session_id: str | None = None
    conversation_id: UUID
    message_id: UUID
    user_message_id: UUID
    citations: list[CitationResponse] = Field(default_factory=list)
    retrieval_query: str | None = None
    rerank_warning: str | None = None


class ClearRequest(BaseModel):
    session_id: str = "default"
