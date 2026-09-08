"""Dashboard API endpoint."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.workspace_context import WorkspaceContext
from app.core.workspace_deps import get_api_workspace, WorkspaceRoute
from app.database import get_db
from app.schemas.dashboard import DashboardOverviewResponse, DashboardYearResponse
from app.services.dashboard_service import (
    DashboardYearUnavailable,
    get_dashboard_overview,
    get_dashboard_year,
)


router = APIRouter(route_class=WorkspaceRoute, prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOverviewResponse)
async def get_dashboard(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[WorkspaceContext, Depends(get_api_workspace)],
) -> DashboardOverviewResponse:
    """Return this month and the earlier months of the current calendar year."""
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Vary"] = "Authorization, X-Workspace-ID"
    overview = await get_dashboard_overview(context, db)
    return DashboardOverviewResponse.model_validate(overview)


@router.get("/years/{year}", response_model=DashboardYearResponse)
async def get_dashboard_year_overview(
    year: Annotated[int, Path(ge=1, le=9999)],
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[WorkspaceContext, Depends(get_api_workspace)],
) -> DashboardYearResponse:
    """Return one historical calendar year and its next available predecessor."""
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Vary"] = "Authorization, X-Workspace-ID"
    try:
        overview = await get_dashboard_year(context, db, year=year)
    except DashboardYearUnavailable as exc:
        raise HTTPException(status_code=404, detail="Dashboard year is unavailable") from exc
    return DashboardYearResponse.model_validate(overview)
