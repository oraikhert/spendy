"""Focused dashboard checks on disposable SQLite; run this module directly."""
import os
import sys
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "synthetic-dashboard-check-secret"
os.environ["DEBUG"] = "false"

from pydantic_settings.sources import DotEnvSettingsSource
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

with patch.object(DotEnvSettingsSource, "_read_env_files", return_value={}):
    from app.database import Base
    from app.models import Account, Card, Transaction, User
    from app.services.dashboard_overview_service import get_dashboard_overview

TODAY = date(2026, 3, 6)


async def seed_dashboard(db):
    account = Account(institution="Synthetic Bank", name="Family", account_currency="GBP", timezone="Asia/Dubai")
    db.add(account)
    await db.flush()
    card = Card(account_id=account.id, name="Everyday", card_type="debit", card_masked_number="**** 1000")
    utc_card = Card(account_id=account.id, name="Travel", card_type="debit", card_masked_number="**** 2000", timezone="UTC")
    db.add_all([card, utc_card])
    await db.flush()

    def add(amount, currency="AED", kind="purchase", when="2026-03-02T12:00:00", **kwargs):
        db.add(Transaction(card_id=kwargs.pop("card_id", card.id), amount=Decimal(amount), currency=currency,
                           transaction_kind=kind, description="Synthetic dashboard fixture",
                           transaction_datetime=datetime.fromisoformat(when) if when else None, **kwargs))

    add("-100", original_amount=Decimal("-999"), original_currency="GBP", fx_fee=Decimal("10"))
    add("20", kind="refund")
    add("5")  # Anomalous sign still contributes as stored.
    add("-3", kind="refund")
    add("-10", "USD")
    add("10", "USD", "refund")
    add("25", "EUR", "refund")
    add("-500", kind="other")
    add("-500", kind="topup")
    add("-500", when=None)
    add("-2", when=None, posting_datetime=datetime(2026, 3, 3))
    add("-4", when="2026-02-28T20:00:00")  # March 1 in account timezone.
    add("-7", when="2026-02-28T19:59:59")
    add("-9", when="2026-02-28T20:00:00", card_id=utc_card.id)  # Card overrides account.
    add("-6", when="2026-03-06T19:59:59")  # Last included local instant.
    add("-500", when="2026-03-06T20:00:00")  # Tomorrow locally.
    add("-40", when="2026-02-02T12:00:00", posting_datetime=datetime(2026, 3, 2))
    add("-10", when="2026-02-20T12:00:00")
    add("-30", when="2026-01-15T12:00:00")
    add("-20", when="2025-12-15T12:00:00")
    add("-500", when="2025-11-30T19:59:59")
    await db.commit()


class DashboardDatabase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        @event.listens_for(self.engine.sync_engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as db:
            await seed_dashboard(db)

    async def asyncTearDown(self):
        await self.engine.dispose()


class DashboardServiceTests(DashboardDatabase):
    async def test_four_periods_membership_currencies_and_timezone_bounds(self):
        statements = []
        @event.listens_for(self.engine.sync_engine, "before_cursor_execute")
        def count_queries(connection, cursor, statement, parameters, context, many):
            statements.append(statement)
        async with self.sessions() as db:
            overview = await get_dashboard_overview(db, today=TODAY)
        self.assertEqual(len(statements), 2)
        current = overview.current
        self.assertEqual((current.date_from, current.date_to), (date(2026, 3, 1), TODAY))
        self.assertEqual([entry.currency for entry in current.currencies], ["AED", "EUR", "USD"])
        aed, eur, usd = current.currencies
        self.assertEqual((aed.net_spending, aed.count, aed.average), (Decimal("90"), 7, Decimal(90) / 7))
        self.assertEqual(aed.comparison_percent, Decimal("125"))
        self.assertEqual((eur.net_spending, eur.count), (Decimal("-25"), 1))
        self.assertEqual((usd.net_spending, usd.count, usd.average), (Decimal(0), 2, Decimal(0)))
        self.assertIsNone(usd.comparison_percent)
        self.assertIsNone(eur.comparison_percent)
        self.assertEqual([(period.date_from, period.date_to) for period in overview.previous], [
            (date(2026, 2, 1), date(2026, 2, 28)),
            (date(2026, 1, 1), date(2026, 1, 31)),
            (date(2025, 12, 1), date(2025, 12, 31)),
        ])
        self.assertEqual([p.currencies[0].net_spending for p in overview.previous], [Decimal(66), Decimal(30), Decimal(20)])
        self.assertEqual([p.currencies[0].count for p in overview.previous], [4, 1, 1])
        self.assertEqual(overview.comparison.date_to, date(2026, 2, 6))

    async def test_short_month_comparison_and_negative_baseline(self):
        async with self.sessions() as db:
            overview = await get_dashboard_overview(db, today=date(2026, 3, 31))
            self.assertEqual(overview.comparison.date_to, date(2026, 2, 28))
            # Negative prior net spending uses abs(previous) as denominator.
            db.add(Transaction(card_id=1, amount=Decimal("50"), currency="EUR", transaction_kind="refund",
                               description="Synthetic prior refund", transaction_datetime=datetime(2026, 2, 2)))
            for amount, kind in (("-10", "purchase"), ("10", "refund")):
                db.add(Transaction(card_id=1, amount=Decimal(amount), currency="USD", transaction_kind=kind,
                                   description="Synthetic zero baseline", transaction_datetime=datetime(2026, 2, 2)))
            await db.commit()
            overview = await get_dashboard_overview(db, today=TODAY)
            self.assertEqual(overview.current.currencies[1].comparison_percent, Decimal(50))
            self.assertIsNone(overview.current.currencies[2].comparison_percent)

    async def test_empty_dataset_has_all_periods(self):
        async with self.sessions() as db:
            overview = await get_dashboard_overview(db, today=date(2028, 1, 1))
        self.assertFalse(overview.current.currencies)
        self.assertEqual(len(overview.previous), 3)
        self.assertTrue(all(not p.currencies for p in overview.previous))


if __name__ == "__main__":
    unittest.main(verbosity=2)
