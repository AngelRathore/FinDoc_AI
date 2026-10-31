"""Owner-scoped persistent conversation CRUD and message submission."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from core.dependencies import get_current_user
from db.session import get_db
from models.conversation import Conversation, Message
from models.document import DocumentRecord
from models.user import User
from schemas.chat import (
    ConversationCreate, ConversationDetailResponse, ConversationListResponse,
    ChatResponse, ConversationRename, ConversationResponse, MessageSend,
)

router = APIRouter()


def _owned(db: Session, user_id: UUID, conversation_id: UUID) -> Conversation:
    item = db.scalar(select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id
    ))
    if item is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return item


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(payload: ConversationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = Conversation(user_id=user.id, title=payload.title.strip() if payload.title else None)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    base = select(Conversation).where(Conversation.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = db.scalars(base.order_by(Conversation.last_message_at.desc().nullslast(), Conversation.updated_at.desc())
                       .offset(offset).limit(limit)).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: UUID, limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    item = _owned(db, user.id, conversation_id)
    base = select(Message).where(Message.conversation_id == item.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.options(selectinload(Message.citations))
                      .order_by(Message.created_at.desc(), Message.id.desc()).offset(offset).limit(limit)).all()
    rows.reverse()
    # A historical citation is displayable only while its source document still exists.
    for message in rows:
        for citation in message.citations:
            citation.available = citation.document_id is None or db.scalar(select(DocumentRecord.id).where(
                DocumentRecord.id == citation.document_id,
                DocumentRecord.owner_id == user.id,
                DocumentRecord.status == "completed",
            )) is not None
            if not citation.available:
                citation.document_id = None
                citation.chunk_id = None
                citation.source = "Source unavailable"
    return {
        "id": item.id, "title": item.title, "created_at": item.created_at,
        "updated_at": item.updated_at, "last_message_at": item.last_message_at,
        "messages": rows, "message_total": total, "message_limit": limit, "message_offset": offset,
    }


@router.patch("/{conversation_id}", response_model=ConversationResponse)
def rename_conversation(
    conversation_id: UUID, payload: ConversationRename, user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    item = _owned(db, user.id, conversation_id)
    item.title = payload.title.strip()
    if not item.title:
        raise HTTPException(status_code=422, detail="Title cannot be empty")
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = _owned(db, user.id, conversation_id)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{conversation_id}/messages", response_model=ChatResponse, status_code=status.HTTP_200_OK)
def send_message(
    conversation_id: UUID, payload: MessageSend, user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    item = _owned(db, user.id, conversation_id)
    from routers.chat import answer_in_conversation
    return answer_in_conversation(db, user, item, payload.question, payload.request_id)
