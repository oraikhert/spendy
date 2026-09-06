"""Read-only calendar-month aggregates shared by the Dashboard HTML and API."""
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import and_, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.card import Card
from app.models.transaction import Transaction
from app.utils.business_time import business_day_utc_bounds


PREVIOUS_MONTH_COUNT = 12


@dataclass(frozen=True)
class CurrencySpending:
    currency: str
    net_spending: Decimal
    count: int
    average: Decimal
    comparison_percent: Decimal | None = None


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


async def get_dashboard_overview(
    db: AsyncSession, *, today: date | None = None,
) -> DashboardOverview:
    """Aggregate the Dashboard periods without loading transaction ORM rows.

    All bounds are half-open UTC instants resolved from each effective card
    timezone. The caller owns the session; this operation never commits or mutates
    data. ``today`` is injectable so calendar behavior can be checked deterministically.
    """
    today = today if today is not None else date.today()
    periods = [SpendingPeriod(today.replace(day=1), today)]
    for _ in range(PREVIOUS_MONTH_COUNT):
        end = periods[-1].date_from - timedelta(days=1)
        periods.append(SpendingPeriod(end.replace(day=1), end))
    previous = periods[1]
    comparison = ComparisonPeriod(
        previous.date_from,
        previous.date_to.replace(day=min(today.day, previous.date_to.day)),
    )
    query_periods = [*periods, SpendingPeriod(comparison.date_from, comparison.date_to)]

    zone = func.coalesce(Card.timezone, Account.timezone, "UTC")
    timezones = (await db.execute(
        select(zone).select_from(Card).join(Account).distinct()
    )).scalars().all()
    effective_date = func.coalesce(
        Transaction.transaction_datetime, Transaction.posting_datetime,
    )
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
            select(literal(index).label("period"), Transaction.currency,
                   func.sum(Transaction.amount).label("signed_sum"),
                   func.count(Transaction.id).label("count"))
            .select_from(Transaction).join(Card).join(Account)
            .where(Transaction.transaction_kind.in_(("purchase", "refund")),
                   or_(False, *conditions))
            .group_by(Transaction.currency)
        )
    rows = (await db.execute(union_all(*queries))).all()
    groups: list[list[CurrencySpending]] = [[] for _ in query_periods]
    for index, currency, signed_sum, count in rows:
        net = -signed_sum
        groups[index].append(CurrencySpending(currency, net, count, net / count))

    baseline = {entry.currency: entry.net_spending for entry in groups[-1]}
    groups[0] = [replace(
        entry,
        comparison_percent=(
            ((entry.net_spending - baseline[entry.currency])
             / abs(baseline[entry.currency]) * Decimal(100))
            .quantize(Decimal(1), rounding=ROUND_HALF_UP)
            if baseline.get(entry.currency) else None
        ),
    ) for entry in groups[0]]
    populated = [replace(period, currencies=tuple(sorted(
        entries, key=lambda entry: entry.currency,
    ))) for period, entries in zip(periods, groups[:-1])]
    return DashboardOverview(populated[0], tuple(populated[1:]), comparison)
