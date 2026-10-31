import unittest
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import Settings
from main import app
from core.dependencies import get_current_user
from db.session import DatabaseNotConfigured
from db.base import Base
from db.session import get_db
import main


def _check_engine(engine):
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.previous_overrides = dict(app.dependency_overrides)

        def override_get_db():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)
        self.engine.dispose()

    def test_settings_accept_environment_overrides(self):
        configured = Settings(
            _env_file=None,
            FINDOC_CHUNK_SIZE="640",
            groq_model="test-model",
            CELERY_BROKER_URL="redis://localhost:6379/4",
            CELERY_RESULT_BACKEND="redis://localhost:6379/5",
            CELERY_TASK_MAX_RETRIES="2",
        )
        self.assertEqual(configured.chunk_size, 640)
        self.assertEqual(configured.groq_model, "test-model")
        self.assertEqual(configured.celery_broker_url, "redis://localhost:6379/4")
        self.assertEqual(configured.celery_result_backend, "redis://localhost:6379/5")
        self.assertEqual(configured.celery_task_max_retries, 2)

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertTrue(response.headers.get("X-Request-ID"))

    def test_ready_checks_database_connectivity(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        original = main.database_is_ready
        main.database_is_ready = lambda: _check_engine(engine)
        try:
            response = self.client.get("/ready")
        finally:
            main.database_is_ready = original
            engine.dispose()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready", "database": "ok"})

    def test_ready_reports_unconfigured_database(self):
        original = main.database_is_ready
        main.database_is_ready = lambda: (_ for _ in ()).throw(DatabaseNotConfigured("missing"))
        try:
            response = self.client.get("/ready")
        finally:
            main.database_is_ready = original
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Database is not configured")
        self.assertIn("error", response.json())

    def test_legacy_and_versioned_ingestion_routes(self):
        previous = app.dependency_overrides.get(get_current_user)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=UUID(int=1), role="user")
        try:
            legacy = self.client.get("/api/ingest/status")
            versioned = self.client.get("/api/v1/ingest/status")
        finally:
            if previous is None:
                app.dependency_overrides.pop(get_current_user, None)
            else:
                app.dependency_overrides[get_current_user] = previous
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(versioned.status_code, 200)
        self.assertEqual(legacy.json(), versioned.json())


if __name__ == "__main__":
    unittest.main()
