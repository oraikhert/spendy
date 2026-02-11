"""Dashboard API endpoints"""
from typing import Annotated
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.deps import get_current_active_user
from app.models.user import User
from app.schemas.dashboard import DashboardSummaryResponse
from app.services import dashboard_service


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    date_from: Annotated[datetime, Query()],
    date_to: Annotated[datetime, Query()],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    account_id: int | None = Query(None),
    card_id: int | None = Query(None),
    base_currency: str | None = Query(None)
):
    """Get dashboard summary with transaction statistics"""
    summary = await dashboard_service.get_dashboard_summary(
        db=db,
        date_from=date_from,
        date_to=date_to,
        account_id=account_id,
        card_id=card_id,
        base_currency=base_currency
    )
    
    return DashboardSummaryResponse(**summary)
