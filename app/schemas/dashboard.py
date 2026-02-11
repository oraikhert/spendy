"""Dashboard schemas"""
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel


class TransactionKindSummary(BaseModel):
    """Summary by transaction kind"""
    kind: str
    total: Decimal
    count: int


class DashboardSummaryResponse(BaseModel):
    """Schema for dashboard summary response"""
    total_spent: Decimal
    total_income: Decimal
    by_kind: list[TransactionKindSummary]
    count_transactions: int
    last_updated_at: datetime | None = None
