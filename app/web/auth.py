"""Web authentication routes for Jinja2 + HTMX."""
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import escape
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate
from app.core.deps import get_current_user_from_cookie, get_current_user_from_cookie_required
from app.core.web_session import ACCESS_TOKEN_COOKIE, browser_origin, set_auth_cookie
from app.services import auth_service, user_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

def _render_alert(request: Request, message: str, kind: str = "error") -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="partials/_alert.html",
        context={"kind": kind, "message": message},
        status_code=200,
    )


def _htmx_redirect(url: str, token_value: str, request: Request) -> Response:
    response = Response(status_code=200)
    response.headers["HX-Redirect"] = url
    set_auth_cookie(response, token_value, request)
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
        request=request,
        name="auth/login.html",
        context={"registration_enabled": settings.REGISTRATION_ENABLED},
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
    return templates.TemplateResponse(
        request=request,
        name="auth/register.html",
        context={},
    )


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


@router.post("/session/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def refresh_session(
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
) -> Response:
    """Record same-origin browser activity; middleware advances the idle deadline."""
    origin = request.headers.get("origin")
    activity_header = request.headers.get("x-spendy-session-activity")
    if origin != browser_origin(request) or activity_header != "true":
        request.state.suppress_session_refresh = True
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid session activity request")
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "private, no-store"})
