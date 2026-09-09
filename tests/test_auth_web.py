"""Focused public authentication-page regression checks."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "synthetic-auth-web-regression-secret"
os.environ["DEBUG"] = "false"

import httpx
from pydantic_settings.sources import DotEnvSettingsSource
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

with patch.object(DotEnvSettingsSource, "_read_env_files", return_value={}):
    from app.config import settings
    from app.database import Base, get_db
    from app.main import app


class AuthenticationWebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        async def isolated_db():
            async with self.sessions() as db:
                yield db

        self.old_overrides = app.dependency_overrides.copy()
        app.dependency_overrides[get_db] = isolated_db
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )
        self.registration_enabled = patch.object(settings, "REGISTRATION_ENABLED", True)
        self.registration_enabled.start()

    async def asyncTearDown(self):
        self.registration_enabled.stop()
        await self.client.aclose()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.old_overrides)
        await self.engine.dispose()

    async def test_pages_use_labeled_controls_and_the_auth_form_script(self):
        for path, form_id, labels in (
            ("/auth/login", "login-form", ("login-username", "login-password")),
            (
                "/auth/register",
                "register-form",
                (
                    "register-email",
                    "register-username",
                    "register-full-name",
                    "register-password",
                    "register-password-confirm",
                ),
            ),
        ):
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('src="/static/js/auth_forms.js"', response.text)
                self.assertIn(f'id="{form_id}"', response.text)
                for field_id in labels:
                    self.assertIn(f'for="{field_id}"', response.text)

    async def test_login_errors_replace_the_form_and_preserve_only_username(self):
        response = await self.client.post(
            "/auth/login",
            data={"username": "remember-me", "password": ""},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("<html", response.text.lower())
        self.assertIn('id="login-form"', response.text)
        self.assertIn('value="remember-me"', response.text)
        self.assertIn('aria-invalid="true"', response.text)
        self.assertIn('role="alert"', response.text)
        self.assertNotIn('value="password"', response.text)

    async def test_registration_validation_retains_non_secret_fields_and_maps_errors(self):
        response = await self.client.post(
            "/auth/register",
            data={
                "email": "not-an-email",
                "username": "ab",
                "full_name": "Synthetic Name",
                "password": "secret-one",
                "password_confirm": "secret-two",
            },
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("<html", response.text.lower())
        self.assertIn('id="register-form"', response.text)
        self.assertIn('value="not-an-email"', response.text)
        self.assertIn('value="ab"', response.text)
        self.assertIn('value="Synthetic Name"', response.text)
        self.assertIn('id="register-email-error"', response.text)
        self.assertIn('id="register-username-error"', response.text)
        self.assertIn('id="register-password-confirm-error"', response.text)
        self.assertNotIn("secret-one", response.text)
        self.assertNotIn("secret-two", response.text)

    async def test_registration_success_keeps_the_existing_htmx_redirect(self):
        response = await self.client.post(
            "/auth/register",
            data={
                "email": "new-user@example.com",
                "username": "new-user",
                "full_name": "New User",
                "password": "synthetic-password",
                "password_confirm": "synthetic-password",
            },
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Redirect"), "/dashboard")
        self.assertIn("access_token", response.cookies)


if __name__ == "__main__":
    unittest.main(verbosity=2)
