"""Web pages routes (dashboard, etc.)"""
from typing import Annotated
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.models.user import User
from app.core.deps import get_current_user_from_cookie_required

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)]
):
    """Display dashboard page (protected - requires authentication)."""
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "user": user}
    )
