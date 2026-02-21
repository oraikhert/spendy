"""Web authentication routes for Jinja2 + HTMX."""
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import escape
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate
from app.core.deps import get_current_user_from_cookie
from app.services import auth_service, user_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ACCESS_TOKEN_COOKIE = "access_token"
ACCESS_TOKEN_MAX_AGE_SECONDS = 1800  # TODO: take from auth settings / token TTL

def _render_alert(request: Request, message: str, kind: str = "error") -> HTMLResponse:
    return templates.TemplateResponse(
        "partials/_alert.html",
        {"request": request, "kind": kind, "message": message},
        status_code=200,
    )


def _set_auth_cookie(response: Response, token_value: str, request: Request) -> None:
    # Secure cookies only over HTTPS; in local dev (http) it must be False.
    secure = request.url.scheme == "https"
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=token_value,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=ACCESS_TOKEN_MAX_AGE_SECONDS,
        path="/",
    )


def _htmx_redirect(url: str, token_value: str, request: Request) -> Response:
    response = Response(status_code=200)
    response.headers["HX-Redirect"] = url
    _set_auth_cookie(response, token_value, request)
    return response


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    user: Annotated[User | None, Depends(get_current_user_from_cookie)],
):
    """Display login page. Redirects to dashboard if already authenticated."""
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "registration_enabled": settings.REGISTRATION_ENABLED},
    )


@router.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Process login form submission (HTMX)."""
    try:
        user = await auth_service.authenticate_user(username, password, db)
        token = await auth_service.create_user_access_token(user)
        return _htmx_redirect("/dashboard", token.access_token, request)
    except ValueError as e:
        return _render_alert(request, str(e), kind="error")


@router.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request,
    user: Annotated[User | None, Depends(get_current_user_from_cookie)],
):
    """Display registration page. Redirects to dashboard if already authenticated."""
    if not settings.REGISTRATION_ENABLED:
        return RedirectResponse(url="/auth/login", status_code=303)
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse("auth/register.html", {"request": request})


@router.post("/register")
async def register_post(
    request: Request,
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    full_name: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Process registration form submission (HTMX)."""
    if not settings.REGISTRATION_ENABLED:
        return _render_alert(request, "Registration is disabled.", kind="error")
    try:
        if password != password_confirm:
            raise ValueError("Passwords do not match")

        user_data = UserCreate(
            email=email,
            username=username,
            password=password,
            full_name=full_name or None,
        )
        user = await user_service.create_user(user_data, db)
        token = await auth_service.create_user_access_token(user)
        return _htmx_redirect("/dashboard", token.access_token, request)
    except ValueError as e:
        return _render_alert(request, str(e), kind="error")


@router.get("/logout")
async def logout() -> RedirectResponse:
    """Logout user by clearing the cookie and redirecting to login page."""
    response = RedirectResponse(url="/auth/login", status_code=303)
    response.delete_cookie(key=ACCESS_TOKEN_COOKIE, path="/")
    return response