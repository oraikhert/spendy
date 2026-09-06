"""Public response models for the Dashboard overview."""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class DashboardModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CurrencySpendingResponse(DashboardModel):
    currency: str
    net_spending: Decimal
    count: int
    average: Decimal
    comparison_percent: Decimal | None = None


class SpendingPeriodResponse(DashboardModel):
    date_from: date
    date_to: date
    currencies: list[CurrencySpendingResponse]


class ComparisonPeriodResponse(DashboardModel):
    date_from: date
    date_to: date


class DashboardOverviewResponse(DashboardModel):
    current: SpendingPeriodResponse
    previous: list[SpendingPeriodResponse]
    comparison: ComparisonPeriodResponse
