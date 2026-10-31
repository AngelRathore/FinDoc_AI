"""Small JSON logging formatter for API and service logs."""
import json
import logging
import logging.config
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Only emit an explicit allowlist of operational metadata. Never serialize
        # arbitrary LogRecord extras, which may contain prompts or credentials.
        for key in ("request_id", "method", "path", "status_code", "duration_ms",
                    "job_id", "document_id", "conversation_id", "attempt",
                    "retry_delay_seconds", "error_type", "stage", "chunk_count",
                    "candidate_count", "selected_count", "rewrite_duration_ms",
                    "retrieval_duration_ms", "generation_duration_ms", "rerank_failed"):
            value = getattr(record, key, None)
            if value is not None:
                event[key] = value
        if record.exc_info:
            event["exception_type"] = record.exc_info[0].__name__
        return json.dumps(event, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
