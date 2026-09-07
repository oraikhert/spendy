"""Read-only calendar-month aggregates shared by the Dashboard HTML and API."""
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import and_, case, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.card import Card
from app.models.transaction import Transaction
from app.utils.business_time import business_date, business_day_utc_bounds


@dataclass(frozen=True)
class LargestSpending:
    description: str
    amount: Decimal


@dataclass(frozen=True)
class CurrencySpending:
    currency: str
    net_spending: Decimal
    turnover: Decimal
    count: int
    average: Decimal | None
    comparison_percent: Decimal | None = None
    largest_expenses: tuple[LargestSpending, ...] = ()


@dataclass(frozen=True)
class SpendingPeriod:
    date_from: date
    date_to: date
    currencies: tuple[CurrencySpending, ...] = ()


@dataclass(frozen=True)
class ComparisonPeriod:
    date_from: date
    date_to: date


@dataclass(frozen=True)
class DashboardOverview:
    current: SpendingPeriod
    previous: tuple[SpendingPeriod, ...]
    comparison: ComparisonPeriod
    year: int
    previous_year: int | None


@dataclass(frozen=True)
class DashboardYear:
    year: int
    months: tuple[SpendingPeriod, ...]
    previous_year: int | None


class DashboardYearUnavailable(ValueError):
    """Raised when a requested historical dashboard year is unavailable."""


async def get_dashboard_overview(
    db: AsyncSession, *, today: date | None = None,
) -> DashboardOverview:
    """Aggregate the Dashboard periods without loading transaction ORM rows.

    All bounds are half-open UTC instants resolved from each effective card
    timezone. The caller owns the session; this operation never commits or mutates
    data. ``today`` is injectable so calendar behavior can be checked deterministically.
    """
    today = today if today is not None else date.today()
    current = SpendingPeriod(today.replace(day=1), today)
    display_year = today.year if today.month > 1 else today.year - 1
    previous = tuple(
        _month_period(display_year, month)
        for month in range(
            today.month - 1 if today.month > 1 else 12,
            0,
            -1,
        )
    )
    comparison_month_end = current.date_from - timedelta(days=1)
    comparison_period = SpendingPeriod(
        comparison_month_end.replace(day=1), comparison_month_end,
    )
    comparison = ComparisonPeriod(
        comparison_period.date_from,
        comparison_period.date_to.replace(
            day=min(today.day, comparison_period.date_to.day),
        ),
    )
    populated, earliest_year = await _aggregate_periods(
        db,
        (current, *previous),
        SpendingPeriod(comparison.date_from, comparison.date_to),
        include_largest_expenses=True,
    )
    return DashboardOverview(
        populated[0], tuple(populated[1:]), comparison, display_year,
        _previous_available_year(display_year, earliest_year),
    )


async def get_dashboard_year(
    db: AsyncSession, *, year: int, today: date | None = None,
) -> DashboardYear:
    """Return every month in an available completed calendar year."""
    today = today if today is not None else date.today()
    if year >= today.year:
        raise DashboardYearUnavailable("A historical year is required")
    months = tuple(_month_period(year, month) for month in range(12, 0, -1))
    populated, earliest_year = await _aggregate_periods(db, months)
    if earliest_year is None or year < earliest_year:
        raise DashboardYearUnavailable("No dashboard data exists for this year")
    return DashboardYear(
        year, tuple(populated), _previous_available_year(year, earliest_year),
    )


def _month_period(year: int, month: int) -> SpendingPeriod:
    date_from = date(year, month, 1)
    next_month = (
        date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    )
    return SpendingPeriod(date_from, next_month - timedelta(days=1))


def _previous_available_year(year: int, earliest_year: int | None) -> int | None:
    return year - 1 if earliest_year is not None and earliest_year < year else None


async def _aggregate_periods(
    db: AsyncSession,
    periods: tuple[SpendingPeriod, ...],
    comparison: SpendingPeriod | None = None,
    include_largest_expenses: bool = False,
) -> tuple[list[SpendingPeriod], int | None]:
    """Aggregate periods and find the first business-calendar year with data."""
    query_periods = [*periods, *([comparison] if comparison is not None else [])]

    zone = func.coalesce(Card.timezone, Account.timezone, "UTC")
    timezones = (await db.execute(
        select(zone).select_from(Card).join(Account).distinct()
    )).scalars().all()
    effective_date = func.coalesce(
        Transaction.transaction_datetime, Transaction.posting_datetime,
    )
    earliest_rows = (await db.execute(
        select(zone, func.min(effective_date))
        .select_from(Transaction).join(Card).join(Account)
        .where(
            Transaction.transaction_kind.in_(("purchase", "refund")),
            effective_date.is_not(None),
        )
        .group_by(zone)
    )).all()
    earliest_year = min((
        business_date(effective, timezone_name).year
        for timezone_name, effective in earliest_rows
        if effective is not None
    ), default=None)
    queries = []
    for index, period in enumerate(query_periods):
        conditions = []
        for timezone_name in timezones:
            start, _ = business_day_utc_bounds(period.date_from, timezone_name)
            _, end = business_day_utc_bounds(period.date_to, timezone_name)
            conditions.append(and_(
                zone == timezone_name, effective_date >= start, effective_date < end,
            ))
        queries.append(
            select(
                literal(index).label("period"),
                Transaction.currency,
                func.sum(case(
                    (Transaction.excluded_from_summary.is_(False), Transaction.amount),
                    else_=Decimal(0),
                )).label("included_signed_sum"),
                func.sum(Transaction.amount).label("total_signed_sum"),
                func.sum(case(
                    (Transaction.excluded_from_summary.is_(False), 1), else_=0,
                )).label("count"),
            )
            .select_from(Transaction).join(Card).join(Account)
            .where(Transaction.transaction_kind.in_(("purchase", "refund")),
                   or_(False, *conditions))
            .group_by(Transaction.currency)
        )
    rows = (await db.execute(union_all(*queries))).all()
    groups: list[list[CurrencySpending]] = [[] for _ in query_periods]
    for index, currency, included_signed_sum, total_signed_sum, count in rows:
        net = -included_signed_sum
        turnover = -total_signed_sum
        groups[index].append(CurrencySpending(
            currency, net, turnover, count, net / count if count else None,
        ))

    largest_expenses: dict[str, tuple[LargestSpending, ...]] = {}
    if include_largest_expenses:
        conditions = []
        for timezone_name in timezones:
            start, _ = business_day_utc_bounds(periods[0].date_from, timezone_name)
            _, end = business_day_utc_bounds(periods[0].date_to, timezone_name)
            conditions.append(and_(
                zone == timezone_name, effective_date >= start, effective_date < end,
            ))
        ranked_expenses = (
            select(
                Transaction.currency.label("currency"),
                Transaction.description.label("description"),
                (-Transaction.amount).label("amount"),
                func.row_number().over(
                    partition_by=Transaction.currency,
                    order_by=(
                        Transaction.amount.asc(), effective_date.desc(), Transaction.id.desc(),
                    ),
                ).label("expense_rank"),
            )
            .select_from(Transaction).join(Card).join(Account)
            .where(
                Transaction.transaction_kind == "purchase",
                Transaction.amount < 0,
                Transaction.excluded_from_summary.is_(False),
                or_(False, *conditions),
            )
            .subquery()
        )
        expense_rows = (await db.execute(
            select(
                ranked_expenses.c.currency,
                ranked_expenses.c.description,
                ranked_expenses.c.amount,
            )
            .where(ranked_expenses.c.expense_rank <= 3)
            .order_by(ranked_expenses.c.currency, ranked_expenses.c.expense_rank)
        )).all()
        expense_groups: dict[str, list[LargestSpending]] = {}
        for currency, description, amount in expense_rows:
            expense_groups.setdefault(currency, []).append(
                LargestSpending(description, amount),
            )
        largest_expenses = {
            currency: tuple(expenses)
            for currency, expenses in expense_groups.items()
        }

    if comparison is not None:
        baseline = {entry.currency: entry.net_spending for entry in groups[-1]}
        groups[0] = [replace(
            entry,
            comparison_percent=(
                ((entry.net_spending - baseline[entry.currency])
                 / abs(baseline[entry.currency]) * Decimal(100))
                .quantize(Decimal(1), rounding=ROUND_HALF_UP)
                if baseline.get(entry.currency) else None
            ),
            largest_expenses=largest_expenses.get(entry.currency, ()),
        ) for entry in groups[0]]
        groups = groups[:-1]
    populated = [replace(period, currencies=tuple(sorted(
        entries, key=lambda entry: entry.currency,
    ))) for period, entries in zip(periods, groups)]
    return populated, earliest_year
