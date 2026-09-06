"""Focused Dashboard API checks using disposable SQLite and ASGI."""
import unittest
from unittest.mock import patch

import httpx

from test_dashboard_service import DashboardDatabase, TODAY, User, get_dashboard_overview
from app.core.security import create_access_token
from app.database import get_db
from app.main import app


class DashboardApiTests(DashboardDatabase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        async with self.sessions() as db:
            db.add_all([
                User(id=1, username="api-active", email="api-active@example.test",
                     hashed_password="unused", is_active=True),
                User(id=2, username="api-inactive", email="api-inactive@example.test",
                     hashed_password="unused", is_active=False),
            ])
            await db.commit()

        async def override_db():
            async with self.sessions() as db:
                yield db

        async def fixed_overview(db):
            return await get_dashboard_overview(db, today=TODAY)

        app.dependency_overrides[get_db] = override_db
        self.overview_patch = patch(
            "app.api.v1.dashboard.get_dashboard_overview", side_effect=fixed_overview,
        )
        self.overview_patch.start()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        )

    async def asyncTearDown(self):
        self.overview_patch.stop()
        await self.client.aclose()
        app.dependency_overrides.clear()
        await super().asyncTearDown()

    @staticmethod
    def authorization(user_id=1):
        token = create_access_token({"sub": str(user_id)})
        return {"Authorization": f"Bearer {token}"}

    async def test_active_user_receives_page_equivalent_overview(self):
        response = await self.client.get(
            "/api/v1/dashboard", headers=self.authorization(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")
        self.assertEqual(response.headers["vary"], "Authorization")
        payload = response.json()
        self.assertEqual(set(payload), {"current", "previous", "comparison"})
        self.assertEqual(
            (payload["current"]["date_from"], payload["current"]["date_to"]),
            ("2026-03-01", "2026-03-06"),
        )
        self.assertEqual(len(payload["previous"]), 12)
        self.assertEqual(payload["previous"][-1]["date_from"], "2025-03-01")
        self.assertEqual(payload["previous"][-1]["date_to"], "2025-03-31")
        self.assertEqual(
            [(entry["currency"], entry["net_spending"], entry["count"],
              entry["comparison_percent"])
             for entry in payload["current"]["currencies"]],
            [("AED", "90.00", 7, "125"),
             ("EUR", "-25.00", 1, None),
             ("USD", "0.00", 2, None)],
        )
        self.assertEqual(
            payload["current"]["currencies"][0]["average"],
            "12.85714285714285714285714286",
        )
        self.assertEqual(
            payload["comparison"],
            {"date_from": "2026-02-01", "date_to": "2026-02-06"},
        )
        self.assertNotIn("total_spent", payload)
        self.assertNotIn("by_kind", payload)

    async def test_authentication_and_removed_summary_route(self):
        missing = await self.client.get("/api/v1/dashboard")
        self.assertEqual(missing.status_code, 401)
        inactive = await self.client.get(
            "/api/v1/dashboard", headers=self.authorization(2),
        )
        self.assertEqual(inactive.status_code, 400)
        removed = await self.client.get(
            "/api/v1/dashboard/summary?date_from=2026-03-01T00:00:00Z&date_to=2026-03-06T00:00:00Z",
            headers=self.authorization(),
        )
        self.assertEqual(removed.status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
