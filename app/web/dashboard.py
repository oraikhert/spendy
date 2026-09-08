"""Server-rendered Dashboard route."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.workspace_context import WorkspaceContext
from app.core.workspace_deps import get_web_workspace, WorkspaceRoute
from app.core.deps import get_current_user_from_cookie_required
from app.database import get_db
from app.models.user import User
from app.services.dashboard_service import (
    DashboardYearUnavailable,
    get_dashboard_overview,
    get_dashboard_year,
)
from app.web.presentation import money
from app.web.transaction_helpers import ListFilters


router = APIRouter(route_class=WorkspaceRoute, tags=["web-dashboard"])
templates = Jinja2Templates(directory="app/templates")
templates.env.globals.update(
    money=money,
    period_url=lambda period: ListFilters(
        period="custom", date_from=period.date_from, date_to=period.date_to,
    ).url(),
)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    context: Annotated[WorkspaceContext, Depends(get_web_workspace)],
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Render the workspace financial overview, or a complete recoverable error."""
    # Snapshot navigation before a failed read can expire session ORM state.
    view_context = {"user": {"username": user.username}, "overview": None}
    status_code = 200
    try:
        view_context["overview"] = await get_dashboard_overview(context, db)
    except (SQLAlchemyError, ValueError):
        status_code = 503
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=view_context,
        status_code=status_code,
        headers={"Cache-Control": "private, no-store", "Vary": "Cookie"},
    )


@router.get("/dashboard/years/{year}", response_class=HTMLResponse)
async def dashboard_year(
    context: Annotated[WorkspaceContext, Depends(get_web_workspace)],
    request: Request,
    year: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Render the next historical year for the Dashboard HTMX expander."""
    try:
        overview = await get_dashboard_year(context, db, year=year)
    except DashboardYearUnavailable as exc:
        raise HTTPException(status_code=404, detail="Dashboard year is unavailable") from exc
    return templates.TemplateResponse(
        request=request,
        name="partials/dashboard_year.html",
        context={"user": {"username": user.username}, "year_summary": overview},
        headers={"Cache-Control": "private, no-store", "Vary": "Cookie, HX-Request"},
    )
