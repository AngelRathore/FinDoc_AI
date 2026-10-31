"""Celery entry points; only UUID identifiers are sent in task messages."""
from celery_app import celery_app
from core.config import settings
from services.worker_ingestion import dispatch_outbox, process_ingestion_job


@celery_app.task(
    bind=True,
    name="tasks.ingestion.ingest_document",
    max_retries=settings.celery_task_max_retries,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def ingest_document(self, job_id: str):
    return process_ingestion_job(job_id, task=self)


@celery_app.task(name="tasks.ingestion.dispatch_pending_jobs", ignore_result=True)
def dispatch_pending_jobs():
    return dispatch_outbox()
