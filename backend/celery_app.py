"""Celery app for local background ingestion."""
from celery import Celery

from core.config import settings

celery_app = Celery(
    "findocai",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["tasks.ingestion"],
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    worker_max_tasks_per_child=50,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 7200},
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_soft_time_limit=settings.celery_task_soft_time_limit,
    task_time_limit=settings.celery_task_time_limit,
    # Keep Beat's scheduler as an import path. An app object here is not callable
    # as a scheduler class and causes embedded Beat to exit at startup.
    beat_scheduler="celery.beat:PersistentScheduler",
    result_expires=3600,
    beat_schedule={
        "dispatch-durable-ingestion-outbox": {
            "task": "tasks.ingestion.dispatch_pending_jobs",
            "schedule": 10.0,
        },
    },
)
