import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import BACKEND_DIR, Settings, settings
from core.dependencies import get_current_user
from core.security import create_access_token, hash_password, verify_password
from db.base import Base
from db.session import get_db
from main import app
from models.user import RefreshToken, User, UserRole
from models.conversation import Conversation
from services.auth import hash_refresh_token


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

        def override_get_db():
            with self.sessions() as db:
                yield db

        self.previous_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = override_get_db
        self.secret_patcher = patch.object(settings, "jwt_secret_key", SecretStr("phase-two-test-secret-" * 3))
        self.secret_patcher.start()
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)
        self.secret_patcher.stop()
        self.engine.dispose()

    def register(self, email="Person@example.com", password="Correct-Horse-Battery-7"):
        return self.client.post("/api/v1/auth/register", json={"email": email, "password": password})

    def set_role(self, email, role):
        with self.sessions() as db:
            user = db.scalar(select(User).where(User.email == email.lower()))
            user.role = role
            db.commit()

    def test_registration_normalizes_email_and_hashes_password(self):
        response = self.register("  Person@Example.COM  ")
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["user"]["email"], "person@example.com")
        self.assertEqual(response.json()["user"]["role"], "user")
        raw_refresh = response.cookies.get("findocai_refresh")
        self.assertTrue(raw_refresh)
        self.assertNotIn("refresh_token", response.json())
        with self.sessions() as db:
            user = db.scalar(select(User).where(User.email == "person@example.com"))
            self.assertNotEqual(user.hashed_password, "Correct-Horse-Battery-7")
            self.assertTrue(user.hashed_password.startswith("$argon2id$"))
            refresh = db.scalar(select(RefreshToken).where(RefreshToken.user_id == user.id))
            self.assertEqual(len(refresh.token_hash), 64)
            self.assertEqual(refresh.token_hash, hash_refresh_token(raw_refresh))

    def test_duplicate_email_is_case_insensitive(self):
        self.assertEqual(self.register().status_code, 201)
        duplicate = self.register("PERSON@example.com")
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn("already exists", duplicate.json()["detail"])

    def test_registration_rejects_client_selected_role(self):
        response = self.client.post("/api/v1/auth/register", json={
            "email": "role@example.com", "password": "Correct-Horse-Battery-7", "role": "admin"
        })
        self.assertEqual(response.status_code, 422)

    def test_login_success_and_invalid_credentials(self):
        self.register()
        success = self.client.post("/api/v1/auth/login", json={
            "email": "PERSON@EXAMPLE.COM", "password": "Correct-Horse-Battery-7"
        })
        self.assertEqual(success.status_code, 200, success.text)
        self.assertEqual(success.json()["token_type"], "bearer")
        self.assertTrue(success.json()["access_token"])
        self.assertTrue(success.cookies.get("findocai_refresh"))
        failure = self.client.post("/api/v1/auth/login", json={
            "email": "person@example.com", "password": "incorrect-password"
        })
        self.assertEqual(failure.status_code, 401)
        self.assertEqual(failure.json()["detail"], "Invalid email or password")

    def test_password_hash_and_verify(self):
        encoded = hash_password("another-strong-password")
        self.assertTrue(verify_password("another-strong-password", encoded))
        self.assertFalse(verify_password("wrong-password", encoded))

    def test_auth_fails_closed_without_jwt_secret(self):
        with patch.object(settings, "jwt_secret_key", None):
            response = self.client.post("/api/v1/auth/register", json={
                "email": "disabled@example.com", "password": "Correct-Horse-Battery-7"
            })
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Authentication is not configured")

    def test_production_settings_fail_fast_without_required_values(self):
        with self.assertRaisesRegex(ValueError, "Production configuration is incomplete"):
            Settings(environment="production", jwt_secret_key=None, groq_api_key=None)

    def test_protected_routes_require_auth_and_valid_token_works(self):
        unauthenticated = self.client.get("/api/v1/auth/me")
        protected_legacy = self.client.get("/api/ingest/status")
        protected_conversations = self.client.get("/api/v1/conversations")
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(protected_legacy.status_code, 401)
        self.assertEqual(protected_conversations.status_code, 401)
        auth = self.register()
        me = self.client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {auth.json()['access_token']}"
        })
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["email"], "person@example.com")

    def test_chat_histories_are_scoped_to_authenticated_user(self):
        first = self.register("first@example.com").json()
        second = self.register("second@example.com").json()
        with self.sessions() as db:
            conversation = Conversation(user_id=UUID(first["user"]["id"]), title="private")
            db.add(conversation)
            db.commit()
            conversation_id = str(conversation.id)
        first_history = self.client.get(f"/api/v1/conversations/{conversation_id}", headers={
            "Authorization": f"Bearer {first['access_token']}"
        })
        second_history = self.client.get(f"/api/v1/conversations/{conversation_id}", headers={
            "Authorization": f"Bearer {second['access_token']}"
        })
        self.assertEqual(first_history.status_code, 200)
        self.assertEqual(first_history.json()["title"], "private")
        self.assertEqual(second_history.status_code, 404)

    def test_expired_and_invalid_access_tokens_are_rejected(self):
        response = self.register()
        expired, _ = create_access_token(response.json()["user"]["id"], timedelta(seconds=-2))
        now = datetime.now(timezone.utc)
        invalid_signature = jwt.encode({
            "sub": response.json()["user"]["id"],
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=1),
        }, "a-different-test-signing-key-that-is-long-enough-123", algorithm="HS256")
        for token in (expired, invalid_signature, "not.a.valid.jwt"):
            result = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(result.status_code, 401)

    def test_refresh_rotation_and_reuse_revokes_entire_family(self):
        initial_response = self.register()
        initial = initial_response.json()
        initial_refresh = initial_response.cookies.get("findocai_refresh")
        rotated_response = self.client.post("/api/v1/auth/refresh")
        self.assertEqual(rotated_response.status_code, 200, rotated_response.text)
        rotated = rotated_response.json()
        rotated_refresh = rotated_response.cookies.get("findocai_refresh")
        self.assertNotEqual(initial_refresh, rotated_refresh)
        self.assertIn(hash_refresh_token(initial_refresh), self._stored_hashes(initial["user"]["id"]))

        replay = self.client.post("/api/v1/auth/refresh", cookies={"findocai_refresh": initial_refresh})
        self.assertEqual(replay.status_code, 401)
        after_replay = self.client.post("/api/v1/auth/refresh", cookies={"findocai_refresh": rotated_refresh})
        self.assertEqual(after_replay.status_code, 401)

    def _stored_hashes(self, user_id):
        with self.sessions() as db:
            return {row.token_hash for row in db.scalars(select(RefreshToken).where(RefreshToken.user_id == UUID(user_id)))}

    def test_logout_revokes_refresh_token(self):
        response = self.register()
        refresh_cookie = response.cookies.get("findocai_refresh")
        logout = self.client.post("/api/v1/auth/logout")
        self.assertEqual(logout.status_code, 204)
        refresh = self.client.post("/api/v1/auth/refresh", cookies={"findocai_refresh": refresh_cookie})
        self.assertEqual(refresh.status_code, 401)

    def test_expired_refresh_token_is_rejected(self):
        response = self.register()
        tokens = response.json()
        refresh_cookie = response.cookies.get("findocai_refresh")
        token_hash = hash_refresh_token(refresh_cookie)
        with self.sessions() as db:
            row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        result = self.client.post("/api/v1/auth/refresh", cookies={"findocai_refresh": refresh_cookie})
        self.assertEqual(result.status_code, 401)

    def test_inactive_user_cannot_login_use_access_or_refresh(self):
        response = self.register()
        tokens = response.json()
        refresh_cookie = response.cookies.get("findocai_refresh")
        with self.sessions() as db:
            user = db.get(User, UUID(tokens["user"]["id"]))
            user.is_active = False
            db.commit()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/auth/login", json={
            "email": "person@example.com", "password": "Correct-Horse-Battery-7"
        }).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/auth/refresh", cookies={
            "findocai_refresh": refresh_cookie
        }).status_code, 401)

    def test_database_backed_admin_role_is_enforced(self):
        tokens = self.register().json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        self.assertEqual(self.client.get("/api/v1/auth/admin/users", headers=headers).status_code, 403)
        self.assertEqual(self.client.delete("/api/v1/ingest/clear", headers=headers).status_code, 403)
        self.set_role("person@example.com", UserRole.ADMIN.value)
        admin_users = self.client.get("/api/v1/auth/admin/users", headers=headers)
        self.assertEqual(admin_users.status_code, 200, admin_users.text)
        self.assertEqual(admin_users.json()[0]["role"], "admin")

    def test_database_enforces_unique_canonical_emails(self):
        with self.sessions() as db:
            db.add(User(email="unique@example.com", hashed_password="hash1"))
            db.commit()
            db.add(User(email="unique@example.com", hashed_password="hash2"))
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
            db.add(User(email="Unique@Example.com", hashed_password="hash3"))
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()


class MigrationTests(unittest.TestCase):
    def test_alembic_migrations_create_auth_tables_in_isolated_sqlite_db(self):
        with tempfile.TemporaryDirectory(prefix="findocai-auth-migration-") as directory:
            db_path = Path(directory) / "migration-test.sqlite"
            env = os.environ.copy()
            env["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=BACKEND_DIR, env=env, check=True, capture_output=True, text=True,
            )
            engine = create_engine(env["DATABASE_URL"])
            try:
                inspector = __import__("sqlalchemy").inspect(engine)
                names = set(inspector.get_table_names())
                job_columns = {column["name"] for column in inspector.get_columns("ingestion_jobs")}
            finally:
                engine.dispose()
            self.assertTrue({"users", "refresh_tokens", "documents", "ingestion_jobs", "alembic_version"}.issubset(names))
            self.assertIn("next_attempt_at", job_columns)
            subprocess.run(
                [sys.executable, "-m", "alembic", "downgrade", "-1"],
                cwd=BACKEND_DIR, env=env, check=True, capture_output=True, text=True,
            )
            engine = create_engine(env["DATABASE_URL"])
            try:
                self.assertNotIn("next_attempt_at", {column["name"] for column in
                                __import__("sqlalchemy").inspect(engine).get_columns("ingestion_jobs")})
            finally:
                engine.dispose()
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=BACKEND_DIR, env=env, check=True, capture_output=True, text=True,
            )


if __name__ == "__main__":
    unittest.main()
