"""Ownership foundation: explicit onboarding and cross-workspace financial isolation."""
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["DEBUG"] = "false"
os.environ["SECRET_KEY"] = "synthetic-workspace-test-secret"
os.environ["REGISTRATION_ENABLED"] = "true"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.config import settings
from app.core.security import create_access_token, decode_access_token
from app.core.workspace_context import WorkspaceAccessError, WorkspaceContext
from app.database import Base, get_db
from app.main import app
from app.models import Account, BankStatementDetail, Card, SourcePayload, Transaction, TransactionObservation, TransactionSourceLink, Workspace, WorkspaceInvitation, WorkspaceMember, User
from app.schemas.workspace import WorkspaceCreate, WorkspaceDelete
from app.services import transaction_service, workspace_service
from app.utils.canonicalization import canonicalize_transaction

SMS = "Purchase of AED 12.34 with Credit Card ending 1111 at SYNTHETIC SHOP, DUBAI. Avl Cr. Limit is AED 100.00"


class WorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="spendy-workspace-tests-")
        self.path = Path(self.directory.name) / "db.sqlite3"
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
        self.registration = patch.object(settings, "REGISTRATION_ENABLED", True)
        self.registration.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        async with self.sessions() as db:
            db.add_all([User(id=i, email=f"user{i}@example.com", username=f"user{i}", hashed_password="unused", is_active=True) for i in (1,2,3)])
            await db.commit()

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        self.registration.stop()
        await self.engine.dispose()
        self.directory.cleanup()

    def headers(self, user=1, workspace=None):
        headers = {"Authorization": f"Bearer {create_access_token({'sub': str(user)})}"}
        if workspace is not None:
            headers["X-Workspace-ID"] = str(workspace)
        return headers

    async def create(self, user=1, name="Family"):
        response = await self.client.post("/api/v1/workspaces", headers=self.headers(user), json={"name": name})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    async def financial_fixture(self, user):
        workspace = await self.create(user)
        headers = self.headers(user, workspace)
        response = await self.client.post("/api/v1/accounts", headers=headers, json={"institution":"Synthetic", "name":"Account", "account_currency":"AED", "timezone":"Asia/Dubai"})
        self.assertEqual(response.status_code, 201, response.text)
        account = response.json()["id"]
        response = await self.client.post(f"/api/v1/accounts/{account}/cards", headers=headers, json={"card_masked_number":"**** 1111", "card_type":"credit", "name":"Card"})
        self.assertEqual(response.status_code, 201, response.text)
        card = response.json()["id"]
        response = await self.client.post("/api/v1/transactions", headers=headers, json={"card_id":card,"amount":"-99.00", "currency":"AED", "description":f"Private user {user}", "transaction_kind":"purchase", "transaction_datetime":datetime.now(UTC).isoformat()})
        self.assertEqual(response.status_code, 201, response.text)
        return workspace, account, card, response.json()["id"]

    async def test_registration_api_web_and_cli_create_only_users(self):
        response = await self.client.post("/api/v1/auth/register", json={"email":"api@example.com", "username":"registered-api", "password":"synthetic-password"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(set(response.json()), {"id","email","username","full_name","is_active","created_at","updated_at"})
        response = await self.client.post("/auth/register", data={"email":"web@example.com","username":"registered-web","password":"synthetic-password","password_confirm":"synthetic-password"})
        self.assertEqual(response.status_code, 200, response.text)
        import asyncio
        process = await asyncio.create_subprocess_exec(sys.executable,"scripts/create_user.py","--email","cli@example.com","--username","registered-cli","--password","synthetic-password",
            env={**os.environ,"DATABASE_URL":f"sqlite+aiosqlite:///{self.path}"}, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        self.assertEqual(process.returncode, 0, stderr.decode())
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count(Workspace.id))), 0)
            self.assertEqual(await db.scalar(select(func.count(WorkspaceMember.id))), 0)
            self.assertEqual(await db.scalar(select(func.count(User.id))), 6)

    async def test_workspace_creation_resolution_and_read_access(self):
        response = await self.client.get("/api/v1/accounts", headers=self.headers())
        self.assertEqual((response.status_code,response.json()["detail"]), (409,"Workspace required"))
        first = await self.create(name="  Family  ")
        response = await self.client.get(f"/api/v1/workspaces/{first}", headers=self.headers())
        self.assertEqual((response.json()["name"],response.json()["role"]), ("Family","owner"))
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual((await self.client.get("/api/v1/accounts", headers=self.headers())).status_code, 200)
        second = await self.create()
        response = await self.client.get("/api/v1/accounts", headers=self.headers())
        self.assertEqual((response.status_code,response.json()["detail"]), (409,"Workspace selection required"))
        for selected in (first, second):
            self.assertEqual((await self.client.get("/api/v1/accounts", headers=self.headers(workspace=selected))).status_code, 200)
        other = await self.create(2)
        for selected in ("garbage", "", "-1", "0", "2147483648", "9"*5000, other, 99999):
            response = await self.client.get("/api/v1/accounts", headers=self.headers(workspace=selected))
            self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual((await self.client.get(f"/api/v1/workspaces/{first}",headers=self.headers(2))).status_code,404)
        async with self.sessions() as db:
            workspace = await db.get(Workspace, first)
            workspace.status = "archived"
            await db.commit()
        response = await self.client.get("/api/v1/accounts",headers=self.headers(workspace=first))
        self.assertEqual((response.status_code,response.json()["detail"]),(409,"Workspace archived"))
        self.assertEqual((await self.client.get("/api/v1/workspaces",headers=self.headers())).json()[0]["status"],"archived")
        for name in ("", "   ", "x"*101):
            self.assertEqual((await self.client.post("/api/v1/workspaces",headers=self.headers(),json={"name":name})).status_code,422)

    async def test_financial_isolation_references_dashboard_and_sources(self):
        one = await self.financial_fixture(1)
        two = await self.financial_fixture(2)
        headers = self.headers(1)
        response = await self.client.get("/api/v1/accounts",headers=headers)
        self.assertEqual([row["id"] for row in response.json()],[one[1]])
        for path in (f"accounts/{two[1]}", f"cards/{two[2]}", f"transactions/{two[3]}", f"accounts/{two[1]}/cards", f"transactions/{two[3]}/observations"):
            self.assertEqual((await self.client.get("/api/v1/"+path,headers=headers)).status_code,404,path)
        for path, body in ((f"accounts/{two[1]}",{"name":"Changed"}), (f"cards/{two[2]}",{"name":"Changed"}), (f"transactions/{two[3]}",{"description":"Changed"})):
            self.assertEqual((await self.client.patch("/api/v1/"+path,headers=headers,json=body)).status_code,404)
            self.assertEqual((await self.client.delete("/api/v1/"+path,headers=headers)).status_code,404)
        for key, foreign in (("account_id",two[1]),("card_id",two[2])):
            self.assertEqual((await self.client.get("/api/v1/transactions",headers=headers,params={key:foreign})).status_code,404)
        self.assertEqual((await self.client.post("/api/v1/transactions",headers=headers,json={"card_id":two[2],"amount":"1","currency":"AED","description":"foreign","transaction_kind":"refund"})).status_code,404)
        dashboard = (await self.client.get("/api/v1/dashboard",headers=headers)).json()
        self.assertEqual(dashboard["current"]["currencies"][0]["count"],1)
        self.assertNotIn("Private user 2",str(dashboard))
        async with self.sessions() as db:
            user = await db.get(User,1)
            context = await workspace_service.resolve_workspace(db,user,None)
            refs = await transaction_service.get_transaction_references(context,db)
            self.assertEqual([card["id"] for card in refs["cards"]],[one[2]])
            foreign = await db.get(Transaction,two[3])
            with self.assertRaises(WorkspaceAccessError):
                await canonicalize_transaction(context,db,foreign)
            with self.assertRaises(FrozenInstanceError):
                context.workspace_id = two[0]
        payloads=[]
        for user, values in ((1,one),(2,two)):
            response = await self.client.post("/api/v1/source-payloads/text",headers={**self.headers(user),"Idempotency-Key":"shared-key"},json={"source_kind":"sms","text":SMS,"card_id":values[2]})
            self.assertEqual(response.status_code,201,response.text)
            payloads.append(response.json())
        self.assertNotEqual(payloads[0]["id"],payloads[1]["id"])
        self.assertNotIn("possible_duplicate",str(payloads[1]))
        response = await self.client.post("/api/v1/source-payloads/text",headers={**headers,"Idempotency-Key":"shared-key"},json={"source_kind":"sms","text":SMS,"card_id":one[2]})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["id"],payloads[0]["id"])
        foreign_payload = payloads[1]["id"]
        foreign_observation = payloads[1]["observations"][0]["id"]
        own_observation = payloads[0]["observations"][0]["id"]
        for method,path,body in (("GET",f"source-payloads/{foreign_payload}",None),("POST",f"source-payloads/{foreign_payload}/reprocess",None),("GET",f"transaction-observations/{foreign_observation}",None),("POST",f"transaction-observations/{foreign_observation}/link",{"transaction_id":one[3]}),("POST",f"transaction-observations/{own_observation}/move",{"transaction_id":two[3]}),("POST",f"transaction-observations/{own_observation}/link",{"transaction_id":two[3]})):
            response = await self.client.request(method,"/api/v1/"+path,headers=headers,json=body)
            self.assertEqual(response.status_code,404,response.text)
        self.assertEqual((await self.client.get("/api/v1/source-payloads",headers=headers)).json()["total"],1)
        self.assertEqual((await self.client.get("/api/v1/transaction-observations",headers=headers,params={"source_payload_id":foreign_payload})).status_code,404)
        response = await self.client.post(f"/api/v1/source-payloads/{payloads[0]['id']}/reprocess",headers=headers)
        self.assertEqual(response.status_code,200,response.text)
        async with self.sessions() as db:
            self.assertIsNotNone(await db.get(SourcePayload,foreign_payload))
            self.assertEqual((await db.get(Transaction,two[3])).description,"Private user 2")

    async def test_viewer_denied_in_services_and_http(self):
        own = await self.financial_fixture(1)
        async with self.sessions() as db:
            db.add(WorkspaceMember(user_id=3,workspace_id=own[0],role="viewer"))
            await db.commit()
            context = await workspace_service.resolve_workspace(db,await db.get(User,3),None)
            with self.assertRaises(WorkspaceAccessError) as denied:
                await transaction_service.delete_transaction(context,db,own[3])
            self.assertEqual(denied.exception.status_code,403)
        self.assertEqual((await self.client.get("/api/v1/transactions",headers=self.headers(3))).status_code,200)
        self.assertEqual((await self.client.delete(f"/api/v1/transactions/{own[3]}",headers=self.headers(3))).status_code,403)
        self.assertEqual((await self.client.post("/api/v1/source-payloads/text",headers=self.headers(3),json={"source_kind":"sms","text":SMS})).status_code,403)

    async def test_web_onboarding_creation_selection_and_session_identity(self):
        sid = "synthetic-login-session-identifier"
        self.client.cookies.set("access_token",create_access_token({"sub":"1","sid":sid}))
        for path in ("/dashboard","/transactions"):
            response = await self.client.get(path)
            self.assertEqual(response.headers["location"],"/workspaces/onboarding")
        response = await self.client.get("/workspaces/onboarding")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"',response.text)[1]
        for data,origin in (({"name":"Explicit","csrf_token":"bad"},"http://test"),({"name":"Explicit","csrf_token":csrf},"https://foreign.example")):
            self.assertEqual((await self.client.post("/workspaces",data=data,headers={"Origin":origin})).status_code,403)
        response = await self.client.post("/workspaces",data={"name":"  ","csrf_token":csrf})
        self.assertEqual(response.status_code,422)
        self.assertIn('role="alert"',response.text)
        response = await self.client.post("/workspaces",data={"name":"Explicit","csrf_token":csrf})
        self.assertEqual(response.status_code,303,response.text)
        claims = decode_access_token(response.cookies["access_token"])
        self.assertEqual(claims["sid"],sid)
        first = claims["workspace_id"]
        second = await self.create()
        response = await self.client.post(f"/workspaces/{second}/select",data={"csrf_token":csrf})
        claims = decode_access_token(response.cookies["access_token"])
        self.assertEqual((claims["sid"],claims["workspace_id"]),(sid,second))
        response = await self.client.get("/dashboard")
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(decode_access_token(response.cookies["access_token"])["workspace_id"],second)
        async with self.sessions() as db:
            member = await db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id==second))
            await db.delete(member)
            await db.commit()
        self.assertEqual((await self.client.get("/dashboard")).headers["location"],"/workspaces")
        response = await self.client.post(f"/workspaces/{first}/select",data={"csrf_token":csrf})
        self.assertEqual(response.status_code,303)

    async def test_ownerless_legacy_requires_explicit_operator_assignment(self):
        async with self.sessions() as db:
            workspace = Workspace(name="Legacy Workspace")
            db.add(workspace)
            await db.commit()
            workspace_id = workspace.id
        response = await self.client.get("/api/v1/accounts",headers=self.headers(workspace=workspace_id))
        self.assertEqual(response.status_code,404)
        async with self.sessions() as db:
            await workspace_service.assign_legacy_owner(db,workspace_id,1)
            with self.assertRaises(ValueError):
                await workspace_service.assign_legacy_owner(db,workspace_id,2)
        self.assertEqual((await self.client.get("/api/v1/accounts",headers=self.headers())).status_code,200)

    async def test_unscoped_endpoints_and_ownership_input_rejection(self):
        for path in ("/health", "/api/v1/meta/transaction-kinds", "/api/v1/exchange-rates/rate?from_currency=AED&to_currency=AED"):
            self.assertEqual((await self.client.get(path)).status_code, 200)
        self.assertEqual((await self.client.get("/api/v1/auth/me", headers=self.headers())).status_code, 200)
        workspace, account, card, transaction = await self.financial_fixture(1)
        for method, path, body in (
            ("POST", "/api/v1/accounts", {"institution":"Synthetic", "name":"Rejected", "account_currency":"AED"}),
            ("PATCH", f"/api/v1/accounts/{account}", {"name":"Rejected"}),
            ("POST", f"/api/v1/accounts/{account}/cards", {"card_masked_number":"**** 2222", "card_type":"debit", "name":"Rejected"}),
            ("PATCH", f"/api/v1/cards/{card}", {"name":"Rejected"}),
            ("POST", "/api/v1/transactions", {"card_id":card, "amount":"-1", "currency":"AED", "description":"Rejected", "transaction_kind":"purchase"}),
            ("PATCH", f"/api/v1/transactions/{transaction}", {"description":"Rejected"}),
            ("POST", "/api/v1/source-payloads/text", {"source_kind":"sms", "text":SMS}),
        ):
            response = await self.client.request(method, path, headers=self.headers(), json={**body, "workspace_id":workspace})
            self.assertEqual(response.status_code, 422, response.text)

    async def test_creation_failure_rolls_back_workspace(self):
        async with self.sessions() as db:
            user = await db.get(User,1)
            with patch.object(db,"commit",side_effect=RuntimeError("synthetic commit failure")):
                with self.assertRaises(RuntimeError):
                    await workspace_service.create_workspace(db,user,WorkspaceCreate(name="Atomic"))
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count(Workspace.id))),0)
            self.assertEqual(await db.scalar(select(func.count(WorkspaceMember.id))),0)

    async def test_collaboration_roles_members_and_final_owner(self):
        workspace, account, _card, _transaction = await self.financial_fixture(1)
        async with self.sessions() as db:
            db.add_all([
                WorkspaceMember(user_id=2, workspace_id=workspace, role="editor"),
                WorkspaceMember(user_id=3, workspace_id=workspace, role="viewer"),
            ])
            await db.commit()
        for user in (1, 2, 3):
            self.assertEqual((await self.client.get("/api/v1/accounts", headers=self.headers(user, workspace))).status_code, 200)
        body = {"institution":"Synthetic", "name":"Role write", "account_currency":"AED", "timezone":"Asia/Dubai"}
        self.assertEqual((await self.client.post("/api/v1/accounts", headers=self.headers(1, workspace), json=body)).status_code, 201)
        self.assertEqual((await self.client.post("/api/v1/accounts", headers=self.headers(2, workspace), json=body)).status_code, 201)
        self.assertEqual((await self.client.post("/api/v1/accounts", headers=self.headers(3, workspace), json=body)).status_code, 403)
        self.assertEqual((await self.client.get(f"/api/v1/workspaces/{workspace}/members", headers=self.headers(3))).status_code, 200)
        self.assertEqual((await self.client.patch(f"/api/v1/workspaces/{workspace}/members/3", headers=self.headers(2), json={"role":"editor"})).status_code, 403)
        self.assertEqual((await self.client.patch(f"/api/v1/workspaces/{workspace}", headers=self.headers(2), json={"name":"Denied"})).status_code, 403)
        self.assertEqual((await self.client.patch(f"/api/v1/workspaces/{workspace}", headers=self.headers(1), json={"name":"Renamed"})).status_code, 200)
        self.assertEqual((await self.client.post(f"/api/v1/workspaces/{workspace}/invitations", headers=self.headers(2), json={"recipient_email":"nobody@example.com","role":"viewer"})).status_code, 403)
        for method, path, body in (
            ("PATCH", f"/api/v1/workspaces/{workspace}/members/1", {"role":"editor"}),
            ("DELETE", f"/api/v1/workspaces/{workspace}/members/1", None),
            ("POST", f"/api/v1/workspaces/{workspace}/leave", None),
        ):
            response = await self.client.request(method, path, headers=self.headers(1), json=body)
            self.assertEqual(response.status_code, 409, response.text)
        response = await self.client.patch(f"/api/v1/workspaces/{workspace}/members/2", headers=self.headers(1), json={"role":"owner"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.client.patch(f"/api/v1/workspaces/{workspace}/members/1", headers=self.headers(1), json={"role":"viewer"})).status_code, 200)
        async with self.sessions() as db:
            owners = await db.scalar(select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace, WorkspaceMember.role == "owner"))
            self.assertEqual(owners, 1)

    async def test_concurrent_owner_changes_preserve_an_owner(self):
        import asyncio
        workspace = await self.create(1)
        async with self.sessions() as db:
            db.add(WorkspaceMember(user_id=2, workspace_id=workspace, role="owner"))
            await db.commit()

        async def demote(actor, target):
            return await self.client.patch(
                f"/api/v1/workspaces/{workspace}/members/{target}",
                headers=self.headers(actor), json={"role":"editor"})

        responses = await asyncio.gather(demote(1, 2), demote(2, 1))
        self.assertIn(200, [response.status_code for response in responses])
        self.assertTrue(any(response.status_code in {403, 409} for response in responses))
        async with self.sessions() as db:
            owners = await db.scalar(select(func.count()).select_from(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace, WorkspaceMember.role == "owner"))
            self.assertEqual(owners, 1)

    async def test_invitation_delivery_rotation_validation_and_acceptance(self):
        workspace = await self.create(1)
        sent_tokens = []

        async def delivered(_recipient, _workspace, _role, token):
            sent_tokens.append(token)

        with patch.object(workspace_service, "send_workspace_invitation", side_effect=delivered):
            response = await self.client.post(f"/api/v1/workspaces/{workspace}/invitations", headers=self.headers(1), json={"recipient_email":"User2@Example.com", "role":"editor"})
        self.assertEqual(response.status_code, 201, response.text)
        invitation_id = response.json()["id"]
        token = sent_tokens[-1]
        duplicate = await self.client.post(
            f"/api/v1/workspaces/{workspace}/invitations",
            headers=self.headers(1),
            json={"recipient_email": "user2@example.com", "role": "viewer"},
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        async with self.sessions() as db:
            invitation = await db.get(WorkspaceInvitation, invitation_id)
            self.assertNotEqual(invitation.token_hash, token)
            self.assertEqual(invitation.recipient_email, "user2@example.com")
        public = await self.client.get(f"/api/v1/workspace-invitations/{token}")
        self.assertEqual(public.status_code, 200, public.text)
        self.assertEqual(public.json()["masked_recipient_email"], "u***@example.com")
        mismatch = await self.client.post(f"/api/v1/workspace-invitations/{token}/accept", headers=self.headers(3))
        self.assertEqual(mismatch.status_code, 403, mismatch.text)
        accepted = await self.client.post(f"/api/v1/workspace-invitations/{token}/accept", headers=self.headers(2))
        self.assertEqual((accepted.status_code, accepted.json()["role"]), (201, "editor"))
        self.assertEqual((await self.client.post(f"/api/v1/workspace-invitations/{token}/accept", headers=self.headers(2))).status_code, 409)

        failed_tokens = []

        async def delivery_failed(_recipient, _workspace, _role, raw_token):
            failed_tokens.append(raw_token)
            raise RuntimeError("synthetic smtp failure")

        with patch.object(workspace_service, "send_workspace_invitation", side_effect=delivery_failed):
            failed = await self.client.post(f"/api/v1/workspaces/{workspace}/invitations", headers=self.headers(1), json={"recipient_email":"user3@example.com", "role":"viewer"})
        self.assertEqual(failed.status_code, 502, failed.text)
        invitations = (await self.client.get(f"/api/v1/workspaces/{workspace}/invitations", headers=self.headers(1))).json()
        failed_invitation = next(item for item in invitations if item["recipient_email"] == "user3@example.com")
        self.assertEqual(failed_invitation["delivery_state"], "failed")
        with patch.object(workspace_service, "send_workspace_invitation", side_effect=delivered):
            resent = await self.client.post(f"/api/v1/workspaces/{workspace}/invitations/{failed_invitation['id']}/resend", headers=self.headers(1))
        self.assertEqual(resent.status_code, 200, resent.text)
        rotated = sent_tokens[-1]
        self.assertNotEqual(rotated, failed_tokens[-1])
        self.assertEqual((await self.client.get(f"/api/v1/workspace-invitations/{failed_tokens[-1]}")).status_code, 404)
        self.assertEqual((await self.client.get(f"/api/v1/workspace-invitations/{rotated}")).status_code, 200)
        await self.client.delete(f"/api/v1/workspaces/{workspace}/invitations/{failed_invitation['id']}", headers=self.headers(1))
        self.assertEqual((await self.client.get(f"/api/v1/workspace-invitations/{rotated}")).status_code, 409)

        with patch.object(workspace_service, "send_workspace_invitation", side_effect=delivered):
            expiring = await self.client.post(f"/api/v1/workspaces/{workspace}/invitations", headers=self.headers(1), json={"recipient_email":"expired@example.com", "role":"viewer"})
        expiring_token = sent_tokens[-1]
        async with self.sessions() as db:
            invitation = await db.get(WorkspaceInvitation, expiring.json()["id"])
            invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await db.commit()
        self.assertEqual((await self.client.get(f"/api/v1/workspace-invitations/{expiring_token}")).status_code, 410)

    async def test_invite_registration_bypasses_public_registration_atomically(self):
        workspace = await self.create(1)
        captured = []

        async def delivered(_recipient, _workspace, _role, token):
            captured.append(token)

        with patch.object(workspace_service, "send_workspace_invitation", side_effect=delivered):
            created = await self.client.post(f"/api/v1/workspaces/{workspace}/invitations", headers=self.headers(1), json={"recipient_email":"invited@example.com", "role":"viewer"})
        self.assertEqual(created.status_code, 201, created.text)
        with patch.object(settings, "REGISTRATION_ENABLED", False):
            self.assertEqual((await self.client.post("/api/v1/auth/register", json={"email":"blocked@example.com","username":"blocked-user","password":"synthetic-password"})).status_code, 403)
            registered = await self.client.post(f"/api/v1/workspace-invitations/{captured[-1]}/register", json={"username":"invited-user", "password":"synthetic-password", "full_name":"Invited User"})
        self.assertEqual(registered.status_code, 201, registered.text)
        self.assertEqual(registered.json()["email"], "invited@example.com")
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count(Workspace.id))), 1)
            invited = await db.scalar(select(User).where(User.email == "invited@example.com"))
            member = await db.scalar(select(WorkspaceMember).where(WorkspaceMember.user_id == invited.id))
            self.assertEqual((member.workspace_id, member.role), (workspace, "viewer"))

    async def test_owner_only_archive_restore_and_delete_guards(self):
        workspace = await self.create(1, "Case Sensitive")
        async with self.sessions() as db:
            db.add(WorkspaceMember(user_id=2, workspace_id=workspace, role="editor"))
            await db.commit()
        active_delete = await self.client.request(
            "DELETE", f"/api/v1/workspaces/{workspace}", headers=self.headers(1),
            json={"confirmation_name":"Case Sensitive"},
        )
        self.assertEqual(active_delete.status_code, 409, active_delete.text)
        self.assertEqual((await self.client.post(f"/api/v1/workspaces/{workspace}/archive", headers=self.headers(2))).status_code, 403)
        archived = await self.client.post(f"/api/v1/workspaces/{workspace}/archive", headers=self.headers(1))
        self.assertEqual((archived.status_code, archived.json()["status"]), (200, "archived"))
        for method, path in (("GET", "accounts"), ("POST", f"workspaces/{workspace}/leave"), ("GET", f"workspaces/{workspace}/members")):
            response = await self.client.request(method, f"/api/v1/{path}", headers=self.headers(1, workspace))
            self.assertEqual(response.status_code, 409, response.text)
        non_owner_delete = await self.client.request(
            "DELETE", f"/api/v1/workspaces/{workspace}", headers=self.headers(2),
            json={"confirmation_name":"Case Sensitive"},
        )
        self.assertEqual(non_owner_delete.status_code, 403, non_owner_delete.text)
        mismatch = await self.client.request(
            "DELETE", f"/api/v1/workspaces/{workspace}", headers=self.headers(1),
            json={"confirmation_name":"case sensitive"},
        )
        self.assertEqual(mismatch.status_code, 409, mismatch.text)
        self.assertEqual((await self.client.post(f"/api/v1/workspaces/{workspace}/restore", headers=self.headers(2))).status_code, 403)
        restored = await self.client.post(f"/api/v1/workspaces/{workspace}/restore", headers=self.headers(1))
        self.assertEqual((restored.status_code, restored.json()["status"]), (200, "active"))

    async def test_delete_complete_graph_and_private_upload(self):
        workspace, account, card, _transaction = await self.financial_fixture(1)
        response = await self.client.post(
            "/api/v1/source-payloads/text", headers=self.headers(1, workspace),
            json={"source_kind":"sms", "text":SMS, "card_id":card},
        )
        self.assertEqual(response.status_code, 201, response.text)
        payload_id = response.json()["id"]
        upload_dir = Path(self.directory.name) / "uploads"
        upload_dir.mkdir()
        upload = upload_dir / "synthetic.payload"
        upload.write_bytes(b"synthetic private upload")
        async with self.sessions() as db:
            payload = await db.get(SourcePayload, payload_id)
            payload.file_path = str(upload.resolve())
            db.add_all([
                WorkspaceMember(user_id=2, workspace_id=workspace, role="viewer"),
                WorkspaceInvitation(
                    workspace_id=workspace, recipient_email="pending@example.com", role="viewer",
                    token_hash="a" * 64, expires_at=datetime.now(UTC) + timedelta(days=1),
                    inviter_user_id=1, delivery_state="sent",
                ),
                BankStatementDetail(source_payload_id=payload_id, workspace_id=workspace, account_id=account, card_id=card),
            ])
            await db.commit()
        with patch.object(settings, "UPLOAD_DIR", str(upload_dir)):
            self.assertEqual((await self.client.post(f"/api/v1/workspaces/{workspace}/archive", headers=self.headers(1))).status_code, 200)
            deleted = await self.client.request(
                "DELETE", f"/api/v1/workspaces/{workspace}", headers=self.headers(1),
                json={"confirmation_name":"Family"},
            )
        self.assertEqual(deleted.status_code, 204, deleted.text)
        stale = await self.client.request(
            "DELETE", f"/api/v1/workspaces/{workspace}", headers=self.headers(1),
            json={"confirmation_name":"Family"},
        )
        self.assertEqual(stale.status_code, 404, stale.text)
        self.assertFalse(upload.exists())
        async with self.sessions() as db:
            self.assertIsNone(await db.get(Workspace, workspace))
            for model in (WorkspaceMember, WorkspaceInvitation, Account, Card, Transaction, SourcePayload, TransactionObservation, TransactionSourceLink, BankStatementDetail):
                self.assertEqual(await db.scalar(select(func.count()).select_from(model).where(model.workspace_id == workspace)), 0)

    async def test_delete_restores_files_on_database_failure(self):
        workspace = await self.create(1, "Rollback")
        upload_dir = Path(self.directory.name) / "rollback-uploads"
        upload_dir.mkdir()
        upload = upload_dir / "synthetic.payload"
        upload.write_bytes(b"synthetic")
        async with self.sessions() as db:
            db.add(SourcePayload(
                workspace_id=workspace, source_kind="other", media_type="application/octet-stream",
                ingestion_method="manual_upload", file_path=str(upload.resolve()), content_hash="b" * 64,
                processing_status="pending", ingestion_metadata={},
            ))
            await db.commit()
        await self.client.post(f"/api/v1/workspaces/{workspace}/archive", headers=self.headers(1))
        with patch.object(settings, "UPLOAD_DIR", str(upload_dir)):
            async with self.sessions() as db:
                user = await db.get(User, 1)
                with patch.object(db, "commit", side_effect=RuntimeError("synthetic database failure")):
                    with self.assertRaises(RuntimeError):
                        await workspace_service.delete_workspace(db, user, workspace, WorkspaceDelete(confirmation_name="Rollback"))
        self.assertTrue(upload.exists())
        async with self.sessions() as db:
            self.assertIsNotNone(await db.get(Workspace, workspace))

    async def test_post_commit_cleanup_failure_is_safe(self):
        workspace = await self.create(1, "Cleanup")
        upload_dir = Path(self.directory.name) / "cleanup-uploads"
        upload_dir.mkdir()
        upload = upload_dir / "synthetic.payload"
        upload.write_bytes(b"synthetic")
        async with self.sessions() as db:
            db.add(SourcePayload(
                workspace_id=workspace, source_kind="other", media_type="application/octet-stream",
                ingestion_method="manual_upload", file_path=str(upload.resolve()), content_hash="c" * 64,
                processing_status="pending", ingestion_metadata={},
            ))
            await db.commit()
        await self.client.post(f"/api/v1/workspaces/{workspace}/archive", headers=self.headers(1))
        with patch.object(settings, "UPLOAD_DIR", str(upload_dir)):
            async with self.sessions() as db:
                user = await db.get(User, 1)
                with patch.object(workspace_service, "_cleanup_private_uploads", side_effect=OSError("synthetic cleanup failure")):
                    with self.assertLogs("app.services.workspace_service", level="ERROR") as captured:
                        await workspace_service.delete_workspace(db, user, workspace, WorkspaceDelete(confirmation_name="Cleanup"))
        self.assertFalse(upload.exists())
        self.assertNotIn(str(upload), "\n".join(captured.output))
        async with self.sessions() as db:
            self.assertIsNone(await db.get(Workspace, workspace))

    async def test_delete_rejects_private_path_outside_upload_dir(self):
        workspace = await self.create(1, "Unsafe path")
        upload_dir = Path(self.directory.name) / "safe-uploads"
        upload_dir.mkdir()
        outside = Path(self.directory.name) / "outside.payload"
        outside.write_bytes(b"synthetic")
        async with self.sessions() as db:
            db.add(SourcePayload(
                workspace_id=workspace, source_kind="other", media_type="application/octet-stream",
                ingestion_method="manual_upload", file_path=str(outside.resolve()), content_hash="d" * 64,
                processing_status="pending", ingestion_metadata={},
            ))
            await db.commit()
        await self.client.post(f"/api/v1/workspaces/{workspace}/archive", headers=self.headers(1))
        with patch.object(settings, "UPLOAD_DIR", str(upload_dir)):
            response = await self.client.request(
                "DELETE", f"/api/v1/workspaces/{workspace}", headers=self.headers(1),
                json={"confirmation_name":"Unsafe path"},
            )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertTrue(outside.exists())
        async with self.sessions() as db:
            self.assertIsNotNone(await db.get(Workspace, workspace))


if __name__ == "__main__":
    unittest.main(verbosity=2)
