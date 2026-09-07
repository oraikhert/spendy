"""Public response models for the Dashboard overview."""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class DashboardModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LargestSpendingResponse(DashboardModel):
    description: str
    amount: Decimal


class CurrencySpendingResponse(DashboardModel):
    currency: str
    net_spending: Decimal
    turnover: Decimal
    count: int
    average: Decimal | None
    comparison_percent: Decimal | None = None
    largest_expenses: list[LargestSpendingResponse]


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
    year: int
    previous_year: int | None


class DashboardYearResponse(DashboardModel):
    year: int
    months: list[SpendingPeriodResponse]
    previous_year: int | None
