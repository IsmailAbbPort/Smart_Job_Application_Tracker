"""Authentication: password hashing, session JWTs, and current-user dependencies.

Accounts are optional. When no valid session cookie is present the dependencies
return None ("guest"), and the data routers fall back to the NULL-owner scope so
the app behaves exactly as it did before accounts existed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import User

COOKIE_NAME = "session"
_ALGO = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def _issue_token(user_id: int, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(days=settings.jwt_expire_days),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGO)


def set_session_cookie(response: Response, user_id: int, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        _issue_token(user_id, settings),
        max_age=settings.jwt_expire_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def get_current_user_optional(
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User | None:
    """Resolve the signed-in user from the session cookie, or None for a guest."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGO])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    return session.get(User, user_id)


def get_current_user(user: User | None = Depends(get_current_user_optional)) -> User:
    """Require an authenticated user (401 otherwise)."""
    if user is None:
        raise HTTPException(status_code=401, detail="not signed in")
    return user
