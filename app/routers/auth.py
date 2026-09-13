"""/auth - optional accounts so a user's data persists across sessions.

Register/login issue a signed JWT in an httpOnly cookie; /me reports the current
session; /logout clears it. Passwords are bcrypt-hashed (see app/auth.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import (
    COOKIE_NAME,
    clear_session_cookie,
    get_current_user_optional,
    hash_password,
    set_session_cookie,
    verify_password,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.models import User
from app.schemas import LoginIn, RegisterIn, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

# Mirrors the frontend rule (min 6, at least one number and one special char).
_SPECIALS = set("!@#$%^&*()-_=+[]{};:,.<>?/|`~'\"\\")


def _validate_password(password: str) -> None:
    if (
        len(password) < 6
        or not any(c.isdigit() for c in password)
        or not any(c in _SPECIALS for c in password)
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Password must be at least 6 characters and include "
                "a number and a special character."
            ),
        )


@router.post("/register", response_model=UserOut, status_code=201)
def register(
    payload: RegisterIn,
    response: Response,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    name = payload.name.strip()
    email = payload.email.strip().lower()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required.")
    if "@" not in email:
        raise HTTPException(status_code=422, detail="A valid email is required.")
    _validate_password(payload.password)

    exists = session.scalar(select(User).where(func.lower(User.email) == email))
    if exists is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")

    user = User(name=name, email=email, password_hash=hash_password(payload.password))
    session.add(user)
    session.commit()
    session.refresh(user)
    set_session_cookie(response, user.id, settings)
    return user


@router.post("/login", response_model=UserOut)
def login(
    payload: LoginIn,
    response: Response,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    email = payload.email.strip().lower()
    user = session.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    set_session_cookie(response, user.id, settings)
    return user


@router.get("/me", response_model=UserOut | None)
def me(
    request: Request,
    response: Response,
    user: User | None = Depends(get_current_user_optional),
    settings: Settings = Depends(get_settings),
) -> User | None:
    # Sliding session: each time an authenticated user loads the app, re-issue the
    # cookie so its expiry counts from last activity, not from login. An inactive
    # user still lapses after jwt_expire_days and must sign in again.
    if user is not None and request.cookies.get(COOKIE_NAME):
        set_session_cookie(response, user.id, settings)
    return user


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    clear_session_cookie(response)
