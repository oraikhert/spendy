"""Helpers for sliding, cookie-authenticated browser sessions."""
from dataclasses import dataclass
import hashlib
import secrets
from typing import Any
from urllib.parse import urlsplit

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
    workspace_id: int | str | None = None


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


def _normalized_origin(value: str) -> tuple[str, str, int] | None:
    """Parse an HTTP origin without trusting string formatting or default ports."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError:
        return None
    return parsed.scheme.lower(), parsed.hostname.casefold(), port


def same_browser_origin(request: Request, origin: str | None) -> bool:
    """Accept the request-facing or configured public origin.

    Reverse proxies may expose an internal Host to ASGI while the browser uses the
    deployment's PUBLIC_BASE_URL. The configured origin is therefore authoritative
    alongside the request-derived origin.
    """
    if origin is None:
        return False
    supplied = _normalized_origin(origin)
    if supplied is None:
        return False
    return supplied in {
        _normalized_origin(browser_origin(request)),
        _normalized_origin(settings.PUBLIC_BASE_URL),
    }


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
        "workspace_id": session.workspace_id,
    })
    set_auth_cookie(response, token, request)
