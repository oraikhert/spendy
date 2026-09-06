"""Helpers for sliding, cookie-authenticated browser sessions."""
from dataclasses import dataclass
import hashlib
import secrets
from typing import Any

from fastapi import Request, Response

from app.config import settings
from app.core.security import create_access_token


ACCESS_TOKEN_COOKIE = "access_token"


@dataclass(frozen=True)
class WebSession:
    """The signed identity needed to renew one browser login session."""

    user_id: int
    username: str
    session_id: str


def new_session_id() -> str:
    """Return an unpredictable identifier shared by tokens from one login."""
    return secrets.token_urlsafe(32)


def session_id_from_token(token: str, payload: dict[str, Any]) -> str:
    """Read a session ID, upgrading pre-sliding-session tokens deterministically."""
    session_id = payload.get("sid")
    if isinstance(session_id, str) and 16 <= len(session_id) <= 128 and session_id.isascii():
        return session_id
    return hashlib.sha256(token.encode()).hexdigest()


def browser_origin(request: Request) -> str:
    """Return the browser-facing origin when the app is behind a TLS proxy."""
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    scheme = forwarded_proto if forwarded_proto in {"http", "https"} else request.url.scheme
    return f"{scheme}://{request.url.netloc}"


def set_auth_cookie(response: Response, token_value: str, request: Request) -> None:
    """Set the browser token with the same lifetime as its signed JWT."""
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=token_value,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )


def renew_auth_cookie(response: Response, request: Request, session: WebSession) -> None:
    """Advance the expiry while retaining the login-bound session identity."""
    token = create_access_token({
        "sub": str(session.user_id),
        "username": session.username,
        "sid": session.session_id,
    })
    set_auth_cookie(response, token, request)
