from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.dependencies import get_current_user
from db.session import get_db
from models.user import User
from schemas.documents import IngestionJobResponse
from services.documents import get_owned_job, retry_owned_job

router = APIRouter()


def _response(job):
    data = IngestionJobResponse.model_validate(job).model_dump()
    data["status_url"] = f"/api/v1/ingestion-jobs/{job.id}"
    return data


@router.get("/{job_id}", response_model=IngestionJobResponse)
def ingestion_job_status(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _response(get_owned_job(db, current_user.id, job_id))


@router.post("/{job_id}/retry", response_model=IngestionJobResponse)
def retry_ingestion_job(
    job_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _response(retry_owned_job(db, current_user.id, job_id))
