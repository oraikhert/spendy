"""Focused cookie-authenticated dashboard HTML checks; no external server needed."""
import re
import unittest
from decimal import Decimal
from html import unescape
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from test_dashboard_service import DashboardDatabase, TODAY, User, get_dashboard_overview
import httpx
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from app.core.security import create_access_token
from app.database import get_db
from app.main import app
from app.models import Transaction
from app.web.presentation import money


class DashboardWebTests(DashboardDatabase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        async with self.sessions() as db:
            db.add_all([
                User(id=1, username="dashboard-user", email="dashboard@example.test", hashed_password="unused", is_active=True),
                User(id=2, username="inactive-user", email="inactive@example.test", hashed_password="unused", is_active=False),
                User(id=3, username="other-user", email="other@example.test", hashed_password="unused", is_active=True),
            ])
            await db.commit()
        async def override_db():
            async with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = override_db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        async def fixed_overview(db):
            return await get_dashboard_overview(db, today=TODAY)
        self.summary_patch = patch("app.web.pages.get_dashboard_overview", side_effect=fixed_overview)
        self.summary_patch.start()

    async def asyncTearDown(self):
        self.summary_patch.stop()
        await self.client.aclose()
        app.dependency_overrides.clear()
        await super().asyncTearDown()

    def login(self, user_id=1):
        self.client.cookies.set("access_token", create_access_token({"sub": str(user_id)}))

    async def test_protected_access(self):
        for user_id in (None, 2):
            if user_id:
                self.login(user_id)
            response = await self.client.get("/dashboard")
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/auth/login")
            self.assertNotIn("90.00 AED", response.text)

    async def test_rendered_totals_navigation_and_exact_drilldowns(self):
        self.login()
        response = await self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        body = response.text.split("<main", 1)[1].split("</main>", 1)[0]
        for text in ("90.00 AED", "−25.00 EUR", "0.00 USD", "12.86 AED", "+125%", "Net refund", "No comparable spending", "66.00 AED", "30.00 AED", "20.00 AED"):
            self.assertIn(text, body)
        for text in ("Welcome,", "Account info", "Administrator", "Quick actions", "Add transaction", "View transactions", "Log out", "<form"):
            self.assertNotIn(text, body)
        self.assertIn('href="/transactions"', response.text.split("<main", 1)[0])
        links = re.findall(r'<a href="([^"]+)"', body)
        expected_ranges = [("2026-03-01", "2026-03-06")] * 3 + [
            ("2026-02-01", "2026-02-28"), ("2026-01-01", "2026-01-31"), ("2025-12-01", "2025-12-31")]
        self.assertEqual(len(links), len(expected_ranges))
        for url, (start, end) in zip(links, expected_ranges):
            parts = urlsplit(unescape(url))
            self.assertEqual(parts.path, "/transactions")
            self.assertEqual(parse_qs(parts.query), {"period": ["custom"], "date_from": [start], "date_to": [end]})
        self.assertEqual(body.count('aria-label="'), 6)
        self.login(3)
        other = await self.client.get("/dashboard")
        self.assertEqual(body, other.text.split("<main", 1)[1].split("</main>", 1)[0])

    async def test_empty_and_failed_summary(self):
        self.login()
        async with self.sessions() as db:
            await db.execute(delete(Transaction))
            await db.commit()
        response = await self.client.get("/dashboard")
        self.assertIn("No purchase or refund transactions this month", response.text)
        self.assertEqual(response.text.count('role="status"'), 4)
        with patch("app.web.pages.get_dashboard_overview", new=AsyncMock(side_effect=SQLAlchemyError("private database detail"))):
            response = await self.client.get("/dashboard")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertIn('role="alert"', response.text)
        self.assertRegex(response.text, r'href="/dashboard"[^>]*>Retry</a>')
        self.assertNotIn("private database detail", response.text)
        self.assertNotIn("Previous months", response.text)

    def test_shared_formatter_preserves_transaction_signs(self):
        self.assertEqual(money(Decimal("12.34"), "AED"), "+12.34 AED")
        self.assertEqual(money(Decimal("-12.34"), "AED"), "−12.34 AED")
        self.assertEqual(money(Decimal("12.34"), "AED", show_plus=False), "12.34 AED")
        self.assertEqual(money(Decimal("0"), "AED", show_plus=False), "0.00 AED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
