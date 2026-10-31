"""Compatibility ingestion routes backed by owned, persistent document records."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session
from urllib.parse import urlsplit

from core.dependencies import get_current_user, require_roles
from db.session import get_db
from models.document import DocumentRecord, DocumentStatus
from models.user import User, UserRole
from schemas.ingest import URLPayload
from services.documents import clear_all_documents, queue_upload_document, queue_url_document

router = APIRouter()


@router.post("/urls", status_code=202)
async def ingest_urls(
    payload: URLPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    succeeded, failed = [], []
    for url in payload.urls:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            failed.append({"url": url, "error": "Only valid HTTP(S) URLs are supported"})
            continue
        try:
            record, job = queue_url_document(db, current_user.id, url)
            succeeded.append((record, job))
        except HTTPException as exc:
            failed.append({"url": url, "error": exc.detail})
    if not succeeded:
        raise HTTPException(status_code=400, detail="No valid URLs were queued")
    return {
        "status": "queued",
        "chunks": 0,
        "sources": [record.original_filename for record, _ in succeeded],
        "jobs": [
            {"document_id": str(record.id), "job_id": str(job.id),
             "status": job.status, "status_url": f"/api/v1/ingestion-jobs/{job.id}"}
            for record, job in succeeded
        ],
        "failed": failed,
    }


async def _ingest_legacy_files(files: list[UploadFile], user: User, db: Session):
    succeeded, failed = [], []
    for upload in files:
        try:
            record, job = await queue_upload_document(db, user.id, upload)
            succeeded.append((record, job))
        except HTTPException as exc:
            failed.append({"file": upload.filename or "upload", "error": exc.detail})
    if not succeeded:
        raise HTTPException(status_code=400, detail="No content extracted from uploaded files")
    return {
        "status": "queued",
        "chunks": 0,
        "sources": [record.original_filename for record, _ in succeeded],
        "jobs": [
            {"document_id": str(record.id), "job_id": str(job.id),
             "status": job.status, "status_url": f"/api/v1/ingestion-jobs/{job.id}"}
            for record, job in succeeded
        ],
        "failed": failed,
    }


@router.post("/pdf", status_code=202)
async def ingest_pdf(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if any((upload.filename or "").lower().endswith(".pdf") is False for upload in files):
        raise HTTPException(status_code=415, detail="Only PDF files are supported on this route")
    return await _ingest_legacy_files(files, current_user, db)


@router.post("/txt", status_code=202)
async def ingest_txt(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if any((upload.filename or "").lower().endswith(".txt") is False for upload in files):
        raise HTTPException(status_code=415, detail="Only TXT files are supported on this route")
    return await _ingest_legacy_files(files, current_user, db)


@router.get("/status")
def ingest_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    records = list(db.scalars(select(DocumentRecord).where(
        DocumentRecord.owner_id == current_user.id,
        DocumentRecord.status == DocumentStatus.COMPLETED.value,
    ).order_by(DocumentRecord.created_at, DocumentRecord.id)).all())
    return {
        "ready": bool(records),
        "sources": [record.original_filename for record in records],
        "source_count": len(records),
    }


@router.delete("/clear")
def clear_ingest(
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    cleared = clear_all_documents(db)
    return {"status": "cleared", "documents": cleared}
