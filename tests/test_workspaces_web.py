"""Workspace collaboration HTML flows, security, and role-aware presentation."""
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["DEBUG"] = "false"
os.environ["SECRET_KEY"] = "synthetic-workspace-web-test-secret"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.core.security import create_access_token, decode_access_token, get_password_hash
from app.database import Base, get_db
from app.main import app
from app.models import WorkspaceMember, User
from app.services import workspace_service


class WorkspaceWebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory(prefix="spendy-workspace-web-")
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "test.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.path}")

        @event.listens_for(self.engine.sync_engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        async def db_override():
            async with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = db_override
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        password = get_password_hash("synthetic-password")
        async with self.sessions() as db:
            db.add_all([
                User(id=1, email="owner@example.com", username="owner", hashed_password=password, is_active=True),
                User(id=2, email="editor@example.com", username="editor", hashed_password=password, is_active=True),
                User(id=3, email="viewer@example.com", username="viewer", hashed_password=password, is_active=True),
            ])
            await db.commit()

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        await self.engine.dispose()

    def bearer(self, user=1, workspace=None):
        headers = {"Authorization": f"Bearer {create_access_token({'sub': str(user)})}"}
        if workspace:
            headers["X-Workspace-ID"] = str(workspace)
        return headers

    def sign_in(self, user, workspace, sid="workspace-web-session-identifier"):
        self.client.cookies.clear()
        self.client.cookies.set("access_token", create_access_token({
            "sub": str(user), "username": {1:"owner", 2:"editor", 3:"viewer"}[user],
            "sid": sid, "workspace_id": workspace,
        }))

    async def create_financial_workspace(self, name, description):
        created = await self.client.post("/api/v1/workspaces", headers=self.bearer(), json={"name": name})
        workspace = created.json()["id"]
        headers = self.bearer(workspace=workspace)
        account = await self.client.post("/api/v1/accounts", headers=headers, json={"institution":"Synthetic", "name":name, "account_currency":"AED", "timezone":"Asia/Dubai"})
        card = await self.client.post(f"/api/v1/accounts/{account.json()['id']}/cards", headers=headers, json={"card_masked_number":"**** 4242", "card_type":"credit", "name":name})
        transaction = await self.client.post("/api/v1/transactions", headers=headers, json={"card_id":card.json()["id"], "amount":"-1.00", "currency":"AED", "description":description, "transaction_kind":"purchase"})
        self.assertEqual(transaction.status_code, 201, transaction.text)
        return workspace

    async def test_switching_changes_dataset_and_preserves_session(self):
        first = await self.create_financial_workspace("First", "FIRST DATASET")
        second = await self.create_financial_workspace("Second", "SECOND DATASET")
        sid = "stable-workspace-session-identifier"
        self.sign_in(1, first, sid)
        page = await self.client.get("/transactions")
        self.assertIn("FIRST DATASET", page.text)
        self.assertNotIn("SECOND DATASET", page.text)
        self.assertEqual(page.headers["referrer-policy"], "same-origin")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
        switched = await self.client.post(
            "/workspaces/select",
            data={"csrf_token":csrf, "workspace_id":second, "return_url":"/transactions"},
            headers={"Origin":"http://localhost:8000"},
        )
        self.assertEqual(switched.status_code, 303, switched.text)
        claims = decode_access_token(switched.cookies["access_token"])
        self.assertEqual((claims["sid"], claims["workspace_id"]), (sid, second))
        page = await self.client.get("/transactions")
        self.assertIn("SECOND DATASET", page.text)
        self.assertNotIn("FIRST DATASET", page.text)

    async def test_workspace_selection_and_rename_validation_use_standard_controls(self):
        self.sign_in(1, None)
        selection = await self.client.get("/workspaces/onboarding")
        self.assertEqual(selection.status_code, 200, selection.text)
        self.assertIn('max-w-6xl space-y-8', selection.text)
        self.assertIn('class="card bg-base-100 shadow-sm', selection.text)
        self.assertIn('for="workspace-name"', selection.text)
        self.assertIn('id="workspace-name-hint"', selection.text)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', selection.text)[1]
        invalid_create = await self.client.post("/workspaces", data={"csrf_token": csrf, "name": " "})
        self.assertEqual(invalid_create.status_code, 422, invalid_create.text)
        self.assertIn('aria-invalid="true"', invalid_create.text)
        self.assertIn('id="workspace-name-error"', invalid_create.text)

        workspace = await self.create_financial_workspace("Rename me", "RENAME DATA")
        self.sign_in(1, workspace)
        detail = await self.client.get(f"/workspaces/{workspace}")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', detail.text)[1]
        self.assertIn('id="workspace-rename-dialog"', detail.text)
        self.assertIn('data-workspace-rename-trigger', detail.text)
        invalid_rename = await self.client.post(
            f"/workspaces/{workspace}/rename", data={"csrf_token": csrf, "name": " "},
        )
        self.assertEqual(invalid_rename.status_code, 422, invalid_rename.text)
        self.assertIn('data-open-on-load="true"', invalid_rename.text)
        self.assertIn('id="workspace-rename-name-error"', invalid_rename.text)
        self.assertIn('value=" "', invalid_rename.text)

    async def test_invitation_registration_validation_has_field_feedback(self):
        workspace = await self.create_financial_workspace("Invite validation", "INVITE VALIDATION DATA")
        self.sign_in(1, workspace)
        detail = await self.client.get(f"/workspaces/{workspace}")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', detail.text)[1]
        captured = []

        async def delivered(_recipient, _workspace, _role, token):
            captured.append(token)

        with patch.object(workspace_service, "send_workspace_invitation", side_effect=delivered):
            created = await self.client.post(
                f"/workspaces/{workspace}/invitations",
                data={"csrf_token": csrf, "recipient_email": "validation@example.com", "role": "viewer"},
            )
        self.assertEqual(created.status_code, 303, created.text)
        self.client.cookies.clear()
        page = await self.client.get(f"/workspace-invitations/{captured[-1]}/register")
        self.assertIn('for="invitation-username"', page.text)
        self.assertIn('for="invitation-password-confirm"', page.text)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
        invalid = await self.client.post(
            f"/workspace-invitations/{captured[-1]}/register",
            data={"csrf_token": csrf, "username": "valid-name", "full_name": "Saved", "password": "one-password", "password_confirm": "other-password"},
        )
        self.assertEqual(invalid.status_code, 422, invalid.text)
        self.assertIn('id="invitation-password-confirm-error"', invalid.text)
        self.assertIn('aria-invalid="true"', invalid.text)
        self.assertIn('value="valid-name"', invalid.text)
        self.assertIn('value="Saved"', invalid.text)

    async def test_role_controls_security_and_immediate_access_loss(self):
        workspace = await self.create_financial_workspace("Shared", "SHARED DATASET")
        async with self.sessions() as db:
            db.add_all([
                WorkspaceMember(workspace_id=workspace, user_id=2, role="editor"),
                WorkspaceMember(workspace_id=workspace, user_id=3, role="viewer"),
            ])
            await db.commit()
        self.sign_in(1, workspace)
        owner_page = await self.client.get(f"/workspaces/{workspace}")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', owner_page.text)[1]
        self.assertIn("Send invitation", owner_page.text)
        self.assertEqual((await self.client.post(f"/workspaces/{workspace}/members/3/role", data={"csrf_token":"bad", "role":"editor"})).status_code, 403)
        self.assertEqual((await self.client.post(f"/workspaces/{workspace}/members/3/role", data={"csrf_token":csrf, "role":"editor"}, headers={"Origin":"https://foreign.example"})).status_code, 403)
        same_origin = await self.client.post(
            f"/workspaces/{workspace}/members/3/role",
            data={"csrf_token":csrf, "role":"viewer"},
            headers={"Origin":"http://test"},
        )
        self.assertEqual(same_origin.status_code, 303, same_origin.text)
        public_origin_behind_proxy = await self.client.post(
            f"/workspaces/{workspace}/members/3/role",
            data={"csrf_token":csrf, "role":"viewer"},
            headers={"Origin":"http://localhost:8000"},
        )
        self.assertEqual(public_origin_behind_proxy.status_code, 303, public_origin_behind_proxy.text)
        lookalike_origin = await self.client.post(
            f"/workspaces/{workspace}/members/3/role",
            data={"csrf_token":csrf, "role":"viewer"},
            headers={"Origin":"http://localhost:8000.evil.example"},
        )
        self.assertEqual(lookalike_origin.status_code, 403, lookalike_origin.text)
        null_origin = await self.client.post(
            f"/workspaces/{workspace}/members/3/role",
            data={"csrf_token":csrf, "role":"viewer"},
            headers={"Origin":"null"},
        )
        self.assertEqual(null_origin.status_code, 403, null_origin.text)

        self.sign_in(3, workspace)
        viewer_transactions = await self.client.get("/transactions")
        self.assertNotIn("Add transaction", viewer_transactions.text)
        viewer_workspace = await self.client.get(f"/workspaces/{workspace}")
        self.assertIn("Members", viewer_workspace.text)
        self.assertNotIn("Send invitation", viewer_workspace.text)
        self.assertNotIn(">Remove<", viewer_workspace.text)

        self.sign_in(2, workspace)
        editor_transactions = await self.client.get("/transactions")
        self.assertIn("Add transaction", editor_transactions.text)
        editor_workspace = await self.client.get(f"/workspaces/{workspace}")
        self.assertNotIn("Send invitation", editor_workspace.text)

        removed = await self.client.delete(f"/api/v1/workspaces/{workspace}/members/2", headers=self.bearer(1))
        self.assertEqual(removed.status_code, 204, removed.text)
        self.sign_in(2, workspace)
        denied = await self.client.get("/dashboard")
        self.assertEqual((denied.status_code, denied.headers["location"]), (303, "/workspaces"))

    async def test_final_owner_leave_returns_workspace_error(self):
        workspace = await self.create_financial_workspace("Only owner", "OWNER DATASET")
        self.sign_in(1, workspace)
        detail = await self.client.get(f"/workspaces/{workspace}")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', detail.text)[1]
        self.assertIn('id="leave-workspace-confirmation"', detail.text)
        self.assertIn('data-leave-workspace-form', detail.text)
        self.assertIn('src="/static/js/workspace_detail.js"', detail.text)

        response = await self.client.post(
            f"/workspaces/{workspace}/leave",
            data={"csrf_token": csrf},
            headers={"Origin": "http://test"},
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("The final owner cannot leave", response.text)
        self.assertIn("Only owner", response.text)
        members = await self.client.get(
            f"/api/v1/workspaces/{workspace}/members",
            headers=self.bearer(1),
        )
        self.assertEqual(members.status_code, 200, members.text)
        self.assertEqual(len(members.json()), 1)

    async def test_existing_user_is_added_and_receives_notification(self):
        workspace = await self.create_financial_workspace("Inviting", "INVITE DATA")
        self.sign_in(1, workspace)
        detail = await self.client.get(f"/workspaces/{workspace}")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', detail.text)[1]
        notifications = []

        async def notified(recipient, workspace_name, role):
            notifications.append((recipient, workspace_name, role))

        with patch.object(workspace_service, "send_workspace_added_notification", side_effect=notified):
            response = await self.client.post(f"/workspaces/{workspace}/invitations", data={"csrf_token":csrf, "recipient_email":"viewer@example.com", "role":"viewer"})
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(response.headers["location"], f"/workspaces/{workspace}?message=added")
        self.assertEqual(notifications, [("viewer@example.com", "Inviting", "viewer")])
        async with self.sessions() as db:
            member = await db.scalar(select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace, WorkspaceMember.user_id == 3))
            self.assertEqual(member.role, "viewer")

    async def test_invitation_registration_when_public_registration_is_disabled(self):
        workspace = await self.create_financial_workspace("Invite registration", "INVITE REGISTER DATA")
        self.sign_in(1, workspace)
        detail = await self.client.get(f"/workspaces/{workspace}")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', detail.text)[1]
        captured = []

        async def delivered(_recipient, _workspace, _role, token):
            captured.append(token)

        with patch.object(workspace_service, "send_workspace_invitation", side_effect=delivered):
            invited = await self.client.post(
                f"/workspaces/{workspace}/invitations",
                data={"csrf_token": csrf, "recipient_email": "new-invite@example.com", "role": "editor"},
            )
        self.assertEqual(invited.status_code, 303, invited.text)
        token = captured[-1]
        self.client.cookies.clear()
        with patch.object(settings, "REGISTRATION_ENABLED", False):
            self.assertEqual((await self.client.get("/auth/register")).headers["location"], "/auth/login")
            landing = await self.client.get(f"/workspace-invitations/{token}")
            self.assertIn("Create invited account", landing.text)
            self.assertNotIn("Log in to accept", landing.text)
            page = await self.client.get(f"/workspace-invitations/{token}/register")
            self.assertIn("Create your invited account", page.text)
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
            registered = await self.client.post(
                f"/workspace-invitations/{token}/register",
                data={
                    "csrf_token": csrf,
                    "username": "new-invite",
                    "full_name": "Invited User",
                    "password": "synthetic-password",
                    "password_confirm": "synthetic-password",
                },
            )
        self.assertEqual((registered.status_code, registered.headers["location"]), (303, "/dashboard"))
        claims = decode_access_token(registered.cookies["access_token"])
        self.assertEqual(claims["workspace_id"], workspace)
        dashboard = await self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        async with self.sessions() as db:
            user = await db.scalar(select(User).where(User.username == "new-invite"))
            memberships = (await db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id))).all()
            self.assertEqual([(member.workspace_id, member.role) for member in memberships], [(workspace, "editor")])

    async def test_archive_restore_and_permanent_delete_web_lifecycle(self):
        workspace = await self.create_financial_workspace("Lifecycle", "LIFECYCLE DATA")
        other_workspace = await self.create_financial_workspace("Other active", "OTHER DATA")
        async with self.sessions() as db:
            db.add_all([
                WorkspaceMember(workspace_id=workspace, user_id=2, role="editor"),
                WorkspaceMember(workspace_id=workspace, user_id=3, role="viewer"),
            ])
            await db.commit()

        self.sign_in(3, workspace)
        viewer_page = await self.client.get(f"/workspaces/{workspace}")
        self.assertNotIn("Archive workspace", viewer_page.text)
        self.assertNotIn("Permanently delete", viewer_page.text)

        self.sign_in(1, workspace)
        owner_page = await self.client.get(f"/workspaces/{workspace}")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', owner_page.text)[1]
        self.assertIn('id="archive-workspace-confirmation"', owner_page.text)
        self.assertIn("data-workspace-confirm-cancel", owner_page.text)
        self.assertEqual((await self.client.post(f"/workspaces/{workspace}/archive", data={"csrf_token":"bad"})).status_code, 403)
        self.assertEqual((await self.client.post(f"/workspaces/{workspace}/archive", data={"csrf_token":csrf}, headers={"Origin":"https://foreign.example"})).status_code, 403)
        self.sign_in(2, workspace)
        self.assertEqual((await self.client.post(f"/workspaces/{workspace}/archive", data={"csrf_token":csrf})).status_code, 403)

        self.sign_in(1, workspace)
        archived = await self.client.post(f"/workspaces/{workspace}/archive", data={"csrf_token":csrf})
        self.assertEqual((archived.status_code, archived.headers["location"]), (303, "/workspaces?message=archived"))
        self.assertIsNone(decode_access_token(archived.cookies["access_token"])["workspace_id"])
        self.assertTrue(decode_access_token(archived.cookies["access_token"])["workspace_invalidated"])
        no_fallback = await self.client.get("/dashboard")
        self.assertEqual((no_fallback.status_code, no_fallback.headers["location"]), (303, "/workspaces"))
        self.assertNotIn("OTHER DATA", no_fallback.text)
        listing = await self.client.get("/workspaces")
        self.assertIn("View archived workspace", listing.text)
        self.assertNotIn(f'action="/workspaces/{workspace}/select"', listing.text)
        archived_page = await self.client.get(f"/workspaces/{workspace}")
        self.assertIn("Archived workspace", archived_page.text)
        self.assertNotIn("Send invitation", archived_page.text)
        self.assertIn('id="delete-workspace-confirmation"', archived_page.text)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', archived_page.text)[1]

        stale_archive = await self.client.post(f"/workspaces/{workspace}/archive", data={"csrf_token":csrf})
        self.assertEqual(stale_archive.status_code, 409, stale_archive.text)
        mismatch = await self.client.post(
            f"/workspaces/{workspace}/delete",
            data={"csrf_token":csrf, "confirmation_name":"lifecycle"},
        )
        self.assertEqual(mismatch.status_code, 409, mismatch.text)
        self.assertIn('value="lifecycle"', mismatch.text)

        restored = await self.client.post(
            f"/workspaces/{workspace}/restore", data={"csrf_token":csrf},
            headers={"HX-Request":"true"},
        )
        self.assertEqual((restored.status_code, restored.headers["hx-redirect"]), (200, f"/workspaces/{workspace}?message=restored"))
        stale_restore = await self.client.post(f"/workspaces/{workspace}/restore", data={"csrf_token":csrf})
        self.assertEqual(stale_restore.status_code, 409, stale_restore.text)

        await self.client.post(f"/workspaces/{workspace}/archive", data={"csrf_token":csrf})
        deleted = await self.client.post(
            f"/workspaces/{workspace}/delete",
            data={"csrf_token":csrf, "confirmation_name":"Lifecycle"},
        )
        self.assertEqual((deleted.status_code, deleted.headers["location"]), (303, "/workspaces?message=deleted"))
        self.assertEqual((await self.client.get(f"/workspaces/{workspace}")).status_code, 404)
        self.assertEqual((await self.client.get(f"/workspaces/{other_workspace}")).status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
