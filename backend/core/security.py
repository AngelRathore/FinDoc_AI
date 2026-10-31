"""Password hashing and JWT access-token helpers."""
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from core.config import settings

_password_hasher = PasswordHasher()
_dummy_password_hash = _password_hasher.hash(secrets.token_urlsafe(32))
_SUPPORTED_JWT_ALGORITHMS = {"HS256", "HS384", "HS512"}


class AuthConfigurationError(RuntimeError):
    pass


def _jwt_key() -> str:
    secret = settings.jwt_secret_key
    if secret is None or not secret.get_secret_value():
        raise AuthConfigurationError("JWT_SECRET_KEY is not configured")
    value = secret.get_secret_value()
    if len(value.encode("utf-8")) < 32:
        raise AuthConfigurationError("JWT_SECRET_KEY must contain at least 32 bytes")
    if settings.jwt_algorithm not in _SUPPORTED_JWT_ALGORITHMS:
        raise AuthConfigurationError("JWT_ALGORITHM is unsupported")
    return value


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def verify_password_for_missing_user(password: str) -> None:
    """Perform a password verification for missing users to reduce timing leaks."""
    verify_password(password, _dummy_password_hash)


def create_access_token(user_id: str, expires_delta: timedelta | None = None) -> tuple[str, int]:
    key = _jwt_key()
    lifetime = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    now = datetime.now(timezone.utc)
    expires_at = now + lifetime
    token = jwt.encode(
        {"sub": user_id, "type": "access", "iat": now, "exp": expires_at, "jti": secrets.token_urlsafe(16)},
        key,
        algorithm=settings.jwt_algorithm,
    )
    return token, max(0, int(lifetime.total_seconds()))


def decode_access_token(token: str) -> str:
    key = _jwt_key()
    try:
        payload = jwt.decode(token, key, algorithms=[settings.jwt_algorithm], options={"require": ["sub", "exp", "iat"]})
    except jwt.PyJWTError as exc:
        raise ValueError("Invalid access token") from exc
    if payload.get("type") != "access" or not isinstance(payload.get("sub"), str):
        raise ValueError("Invalid access token")
    return payload["sub"]
