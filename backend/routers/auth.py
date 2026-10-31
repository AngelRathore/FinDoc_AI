import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.config import settings
from core.dependencies import get_current_user, require_roles
from core.security import AuthConfigurationError, _jwt_key
from db.session import get_db
from models.user import User, UserRole
from schemas.auth import (
    AdminUserResponse,
    LoginRequest,
    RegistrationRequest,
    TokenResponse,
    UserResponse,
)
from services.auth import (
    InvalidCredentials,
    InvalidRefreshToken,
    authenticate_user,
    register_user,
    revoke_refresh_token,
    rotate_refresh_token,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _ensure_auth_configured() -> None:
    try:
        _jwt_key()
    except AuthConfigurationError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Authentication is not configured")


def _token_response(user: User, tokens) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        user=UserResponse.model_validate(user),
    )


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key="findocai_refresh",
        value=raw_token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        path="/api",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegistrationRequest, response: Response, db: Session = Depends(get_db)):
    _ensure_auth_configured()
    try:
        user, tokens = register_user(db, str(payload.email), payload.password)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")
    _set_refresh_cookie(response, tokens.refresh_token)
    return _token_response(user, tokens)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    _ensure_auth_configured()
    try:
        user, tokens = authenticate_user(db, str(payload.email), payload.password)
    except InvalidCredentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password",
                            headers={"WWW-Authenticate": "Bearer"})
    _set_refresh_cookie(response, tokens.refresh_token)
    return _token_response(user, tokens)


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    _ensure_auth_configured()
    raw_token = request.cookies.get("findocai_refresh")
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked refresh token",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        user, tokens = rotate_refresh_token(db, raw_token)
    except InvalidRefreshToken:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked refresh token",
                            headers={"WWW-Authenticate": "Bearer"})
    _set_refresh_cookie(response, tokens.refresh_token)
    return _token_response(user, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    # Idempotent logout avoids revealing whether a supplied refresh token exists.
    raw_token = request.cookies.get("findocai_refresh")
    if raw_token:
        revoke_refresh_token(db, raw_token)
    response.delete_cookie(key="findocai_refresh", path="/api", secure=settings.auth_cookie_secure,
                           httponly=True, samesite="strict")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/admin/users", response_model=list[AdminUserResponse])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    return db.scalars(select(User).order_by(User.created_at, User.id)).all()
