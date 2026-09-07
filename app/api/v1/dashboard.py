"""Dashboard API endpoint."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.user import User
from app.schemas.dashboard import DashboardOverviewResponse, DashboardYearResponse
from app.services.dashboard_service import (
    DashboardYearUnavailable,
    get_dashboard_overview,
    get_dashboard_year,
)


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOverviewResponse)
async def get_dashboard(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
) -> DashboardOverviewResponse:
    """Return this month and the earlier months of the current calendar year."""
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Vary"] = "Authorization"
    overview = await get_dashboard_overview(db)
    return DashboardOverviewResponse.model_validate(overview)


@router.get("/years/{year}", response_model=DashboardYearResponse)
async def get_dashboard_year_overview(
    year: Annotated[int, Path(ge=1, le=9999)],
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
) -> DashboardYearResponse:
    """Return one historical calendar year and its next available predecessor."""
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Vary"] = "Authorization"
    try:
        overview = await get_dashboard_year(db, year=year)
    except DashboardYearUnavailable as exc:
        raise HTTPException(status_code=404, detail="Dashboard year is unavailable") from exc
    return DashboardYearResponse.model_validate(overview)
