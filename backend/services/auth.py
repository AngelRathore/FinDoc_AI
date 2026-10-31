"""Authentication operations; only refresh-token digests are stored in the DB."""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core.config import settings
from core.security import create_access_token, hash_password, verify_password, verify_password_for_missing_user
from models.user import RefreshToken, User, UserRole


class InvalidCredentials(Exception):
    pass


class InvalidRefreshToken(Exception):
    pass


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _new_refresh_token(db: Session, user_id: UUID, family_id: UUID) -> tuple[str, RefreshToken]:
    raw_token = secrets.token_urlsafe(48)
    token_hash = hash_refresh_token(raw_token)
    now = datetime.now(timezone.utc)
    row = RefreshToken(
        user_id=user_id,
        family_id=family_id,
        token_hash=token_hash,
        expires_at=now + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(row)
    return raw_token, row


def _issue_for_user(db: Session, user: User, family_id: UUID | None = None) -> IssuedTokens:
    access_token, expires_in = create_access_token(str(user.id))
    raw_refresh, _ = _new_refresh_token(db, user.id, family_id or uuid4())
    return IssuedTokens(access_token, raw_refresh, expires_in)


def register_user(db: Session, email: str, password: str) -> tuple[User, IssuedTokens]:
    user = User(email=normalize_email(email), hashed_password=hash_password(password), role=UserRole.USER.value)
    db.add(user)
    db.flush()
    tokens = _issue_for_user(db, user)
    db.commit()
    db.refresh(user)
    return user, tokens


def authenticate_user(db: Session, email: str, password: str) -> tuple[User, IssuedTokens]:
    normalized = normalize_email(email)
    user = db.scalar(select(User).where(User.email == normalized))
    if user is None:
        verify_password_for_missing_user(password)
        raise InvalidCredentials
    if not verify_password(password, user.hashed_password) or not user.is_active:
        raise InvalidCredentials
    tokens = _issue_for_user(db, user)
    db.commit()
    return user, tokens


def rotate_refresh_token(db: Session, raw_token: str) -> tuple[User, IssuedTokens]:
    token_hash = hash_refresh_token(raw_token)
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update())
    if row is None:
        raise InvalidRefreshToken

    now = datetime.now(timezone.utc)
    if row.revoked_at is not None:
        db.execute(update(RefreshToken).where(
            RefreshToken.family_id == row.family_id,
            RefreshToken.revoked_at.is_(None),
        ).values(revoked_at=now))
        db.commit()
        raise InvalidRefreshToken

    if _utc(row.expires_at) <= now:
        row.revoked_at = now
        db.execute(update(RefreshToken).where(
            RefreshToken.family_id == row.family_id,
            RefreshToken.revoked_at.is_(None),
        ).values(revoked_at=now))
        db.commit()
        raise InvalidRefreshToken

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        db.execute(update(RefreshToken).where(
            RefreshToken.family_id == row.family_id,
            RefreshToken.revoked_at.is_(None),
        ).values(revoked_at=now))
        db.commit()
        raise InvalidRefreshToken

    row.revoked_at = now
    raw_new_token, new_row = _new_refresh_token(db, user.id, row.family_id)
    row.replaced_by_hash = new_row.token_hash
    access_token, expires_in = create_access_token(str(user.id))
    db.commit()
    return user, IssuedTokens(access_token, raw_new_token, expires_in)


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token)))
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
