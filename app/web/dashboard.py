"""Server-rendered Dashboard route."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_from_cookie_required
from app.database import get_db
from app.models.user import User
from app.services.dashboard_service import get_dashboard_overview
from app.web.presentation import money
from app.web.transaction_helpers import ListFilters


router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")
templates.env.globals.update(
    money=money,
    period_url=lambda period: ListFilters(
        period="custom", date_from=period.date_from, date_to=period.date_to,
    ).url(),
)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Render the shared financial overview, or a complete recoverable error."""
    # Snapshot navigation before a failed read can expire session ORM state.
    context = {"user": {"username": user.username}, "overview": None}
    status_code = 200
    try:
        context["overview"] = await get_dashboard_overview(db)
    except (SQLAlchemyError, ValueError):
        status_code = 503
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=context,
        status_code=status_code,
        headers={"Cache-Control": "private, no-store", "Vary": "Cookie"},
    )
