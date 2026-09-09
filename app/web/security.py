"""Shared browser mutation and private-response protections."""
import hashlib
import hmac

from fastapi import HTTPException, Request

from app.config import settings
from app.core.web_session import same_browser_origin


def csrf_token(request: Request) -> str:
    session_id = getattr(request.state, "web_session_id", None) or request.cookies.get("access_token") or request.url.path
    return hmac.new(settings.SECRET_KEY.encode(), ("forms:" + session_id).encode(), hashlib.sha256).hexdigest()


def valid_csrf(request: Request, value: object) -> bool:
    return isinstance(value, str) and value.isascii() and hmac.compare_digest(csrf_token(request), value)


async def protected_form(request: Request):
    posted = await request.form()
    origin = request.headers.get("origin")
    if (origin and not same_browser_origin(request, origin)) or not valid_csrf(request, posted.get("csrf_token")):
        raise HTTPException(403, "Invalid form token")
    return posted


PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "Pragma": "no-cache",
}
