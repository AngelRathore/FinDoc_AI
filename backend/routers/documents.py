from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from core.dependencies import get_current_user, require_roles
from db.session import get_db
from models.user import User, UserRole
from schemas.documents import (
    AdminDocumentListResponse, DocumentAcceptedResponse, DocumentListResponse, DocumentResponse,
)
from services.documents import (
    delete_owned_document,
    get_owned_document,
    list_all_documents_for_admin,
    list_owned_documents,
    queue_upload_document,
)

router = APIRouter()


@router.post("", response_model=DocumentAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document, job = await queue_upload_document(db, current_user.id, file)
    return {
        "id": document.id,
        "document_id": document.id,
        "job_id": job.id,
        "status": job.status,
        "status_url": f"/api/v1/ingestion-jobs/{job.id}",
    }


@router.get("", response_model=DocumentListResponse)
def list_documents(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = list_owned_documents(db, current_user.id, limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/admin", response_model=AdminDocumentListResponse)
def list_all_documents_admin(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    rows, total = list_all_documents_for_admin(db, limit, offset)
    return {
        "items": [{
            "id": record.id,
            "owner_id": record.owner_id,
            "owner_email": email,
            "original_filename": record.original_filename,
            "file_type": record.file_type,
            "file_size": record.file_size,
            "status": record.status,
            "ingestion_job_status": record.ingestion_job.status if record.ingestion_job else None,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        } for record, email in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{document_id}", response_model=DocumentResponse)
def document_detail(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_owned_document(db, current_user.id, document_id)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    delete_owned_document(db, current_user.id, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
