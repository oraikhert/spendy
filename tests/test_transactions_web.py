"""Executable transaction HTML regression checks using disposable SQLite and ASGI.

Run from the repository root: python tests/test_transactions_web.py
No server, personal database, external network, or dotenv configuration is used.
"""
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "synthetic-transactions-web-regression-secret"
os.environ["DEBUG"] = "false"

import httpx
from pydantic_settings.sources import DotEnvSettingsSource
from sqlalchemy import delete, event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Suppress dotenv reads rather than merely overriding its sensitive values.
with patch.object(DotEnvSettingsSource, "_read_env_files", return_value={}):
    from app.core.security import create_access_token
    from app.database import Base, get_db
    from app.main import app
    from app.models import (
        Account,
        Card,
        SourcePayload,
        Transaction,
        TransactionObservation,
        TransactionSourceLink,
        User,
    )


class Forms(HTMLParser):
    """Read successful controls as a browser does, including untouched edit values."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self.current = None
        self.select = None
        self.option = None
        self.textarea = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = {"action": attrs.get("action", ""), "fields": {}}
            self.forms.append(self.current)
        elif self.current is not None and "disabled" not in attrs:
            if tag == "input" and attrs.get("name"):
                kind = attrs.get("type", "text")
                if kind not in {"submit", "button", "reset", "file"} and (
                    kind not in {"checkbox", "radio"} or "checked" in attrs
                ):
                    self.current["fields"][attrs["name"]] = attrs.get("value", "")
            elif tag == "select" and attrs.get("name"):
                self.select = {"name": attrs["name"], "options": []}
            elif tag == "option" and self.select is not None:
                self.option = {"value": attrs.get("value"), "selected": "selected" in attrs, "text": ""}
            elif tag == "textarea" and attrs.get("name"):
                self.textarea = attrs["name"]
                self.current["fields"][self.textarea] = ""

    def handle_data(self, data):
        if self.option is not None:
            self.option["text"] += data
        if self.textarea is not None and self.current is not None:
            self.current["fields"][self.textarea] += data

    def handle_endtag(self, tag):
        if tag == "option" and self.option is not None:
            self.select["options"].append(self.option)
            self.option = None
        elif tag == "select" and self.select is not None:
            options = self.select["options"]
            if options:
                selected = next((item for item in options if item["selected"]), options[0])
                self.current["fields"][self.select["name"]] = (
                    selected["value"] if selected["value"] is not None else selected["text"]
                )
            self.select = None
        elif tag == "textarea":
            self.textarea = None
        elif tag == "form":
            self.current = None

    def for_action(self, path):
        matches = [form for form in self.forms if urlsplit(form["action"]).path == path]
        if not matches:
            raise AssertionError(f"No HTML form for {path}; available: {[f['action'] for f in self.forms]}")
        return matches[0]["fields"].copy()

    def csrf(self):
        for form in self.forms:
            token = form["fields"].get("csrf_token")
            if token:
                return token
        raise AssertionError("No CSRF token found in HTML forms")


async def seed_web_fixtures(db, upload_dir):
    """Create synthetic users and linked records; also usable by browser fixtures."""
    active = User(username="web-active", email="web-active@example.test", hashed_password="unused", is_active=True)
    other = User(username="web-other", email="web-other@example.test", hashed_password="unused", is_active=True)
    inactive = User(username="web-inactive", email="web-inactive@example.test", hashed_password="unused", is_active=False)
    account = Account(institution="Synthetic Bank", name="Everyday account", account_currency="AED")
    foreign_account = Account(institution="Example Bank", name="Travel account", account_currency="USD")
    db.add_all([active, other, inactive, account, foreign_account])
    await db.flush()
    card = Card(account_id=account.id, name="Everyday card", card_masked_number="**** 1234", card_type="debit")
    foreign_card = Card(account_id=foreign_account.id, name="Travel card", card_masked_number="**** 9876", card_type="credit")
    db.add_all([card, foreign_card])
    await db.flush()
    precise = datetime(2026, 2, 16, 12, 34, 56, 123456)
    transaction = Transaction(
        card_id=card.id, amount=Decimal("-12.34"), currency="AED", description="Synthetic legacy transaction",
        transaction_kind="purchase", transaction_datetime=precise, posting_datetime=precise + timedelta(hours=1),
        location="Synthetic location", original_amount=Decimal("-3.36"), original_currency=None,
        fx_rate=Decimal("3.672500"), fx_fee=Decimal("0.25"),
    )
    other_transaction = Transaction(card_id=foreign_card.id, amount=Decimal("4.00"), currency="USD",
                                    description="Other linked transaction", transaction_kind="refund")
    upload_dir.mkdir(parents=True, exist_ok=True)
    fixture_file = upload_dir / "synthetic.txt"
    fixture_file.write_text("Synthetic attachment only", encoding="utf-8")
    payload = SourcePayload(
        source_kind="sms", media_type="text/plain", ingestion_method="phone_api",
        raw_text="Synthetic original source <script>alert('unsafe')</script>",
        file_path=str(fixture_file), original_filename="statement <unsafe>.txt",
        content_hash="a" * 64, received_at=datetime(2026, 4, 1),
        processing_status="processed", parser_name="synthetic_parser", parser_version="1-test",
        ingestion_metadata={
            "account_id": account.id, "card_id": card.id, "sender": "Synthetic sender",
            "recipients": "Synthetic recipients", "private_unknown": "must not render",
        },
    )
    other_payload = SourcePayload(
        source_kind="bank_statement", media_type="application/pdf", ingestion_method="manual_upload",
        file_path=str(fixture_file), original_filename="other-statement.pdf", content_hash="b" * 64,
        received_at=datetime(2026, 3, 1), processing_status="processed",
        ingestion_metadata={},
    )
    db.add_all([transaction, other_transaction, payload, other_payload])
    await db.flush()
    observation = TransactionObservation(
        source_payload_id=payload.id, source_item_key="sms-0", amount=Decimal("-12.34"),
        currency="AED", original_amount=Decimal("-3.36"), original_currency="USD",
        transaction_datetime=precise, posting_datetime=precise + timedelta(hours=1),
        description="Source extraction", transaction_kind="purchase", location="Observed location",
        account_id=account.id, card_id=card.id, card_last_four="1234",
        raw_fragment="Synthetic observation fragment <b>unsafe</b>",
        extraction_confidence=Decimal("0.8750"), extraction_metadata={},
    )
    other_observation = TransactionObservation(
        source_payload_id=other_payload.id, source_item_key="statement-0", amount=Decimal("4.00"),
        currency="USD", description="Other source extraction", transaction_kind="refund",
        card_id=foreign_card.id, card_last_four="9876", extraction_metadata={},
    )
    db.add_all([observation, other_observation])
    await db.flush()
    db.add_all([
        TransactionSourceLink(
            transaction_id=transaction.id, observation_id=observation.id,
            match_method="automatic", match_confidence=Decimal("0.9000"),
            matcher_name="synthetic_matcher", matcher_version="1-test",
        ),
        TransactionSourceLink(
            transaction_id=other_transaction.id, observation_id=other_observation.id,
            match_method="manual",
        ),
    ])
    await db.commit()
    return {"active": active.id, "other": other.id, "inactive": inactive.id, "account": account.id,
            "foreign_account": foreign_account.id, "card": card.id, "foreign_card": foreign_card.id,
            "transaction": transaction.id, "other_transaction": other_transaction.id,
            "source": observation.id, "other_source": other_observation.id,
            "payload": payload.id, "other_payload": other_payload.id,
            "file": fixture_file, "precise": precise}


class TransactionsWebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="spendy-web-tests-")
        self.upload_dir = Path(self.tempdir.name) / "uploads"
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(self.engine.sync_engine, "connect")
        def enable_foreign_keys(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as db:
            self.data = await seed_web_fixtures(db, self.upload_dir)

        async def isolated_db():
            async with self.sessions() as db:
                yield db

        self.old_overrides = app.dependency_overrides.copy()
        app.dependency_overrides[get_db] = isolated_db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
        self.login(self.data["active"])

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.old_overrides)
        await self.engine.dispose()
        self.tempdir.cleanup()

    def login(self, user_id, *, expired=False):
        self.client.cookies.clear()
        token = create_access_token({"sub": str(user_id)}, expires_delta=timedelta(minutes=-1 if expired else 10))
        self.client.cookies.set("access_token", token)

    async def form(self, path, *, params=None):
        response = await self.client.get(path, params=params)
        self.assertEqual(response.status_code, 200, response.text[:800])
        return Forms(response.text).for_action(path)

    async def csrf(self):
        response = await self.client.get("/transactions/new")
        self.assertEqual(response.status_code, 200, response.text[:800])
        return Forms(response.text).csrf()

    def valid_fields(self, csrf):
        return {"csrf_token": csrf, "card_id": str(self.data["card"]), "amount": "-7.50", "currency": "AED",
                "transaction_kind": "purchase", "description": "Created synthetic transaction"}

    async def snapshot(self):
        async with self.sessions() as db:
            return tuple([await db.scalar(select(func.count()).select_from(model))
                          for model in (Transaction, SourcePayload, TransactionObservation,
                                        TransactionSourceLink, Card, Account)])

    async def add_transactions(self, entries):
        async with self.sessions() as db:
            defaults = dict(card_id=self.data["card"], amount=Decimal("-1.00"), currency="AED", transaction_kind="purchase")
            objects = [Transaction(**{**defaults, **entry}) for entry in entries]
            db.add_all(objects)
            await db.commit()
            return [item.id for item in objects]

    async def add_sources(self, count):
        async with self.sessions() as db:
            payloads = []
            states = ["pending", "processing", "processed", "ignored", "failed", "future-state"]
            kinds = ["sms", "bank_statement", "bank_app", "other"]
            for number in range(count):
                payloads.append(SourcePayload(
                    source_kind=kinds[number % len(kinds)], media_type="text/plain",
                    ingestion_method="migration", raw_text=f"Synthetic raw payload {number:02d}",
                    file_path=str(self.upload_dir / f"private-{number}.payload") if number == 0 else None,
                    original_filename=f"source-{number:02d}.txt", content_hash=f"{number + 100:064x}",
                    received_at=datetime(2026, 3, 1) + timedelta(minutes=number),
                    processing_status=states[number % len(states)],
                    processing_error="Synthetic parse error <img src=x onerror=alert(1)>",
                    parser_name="synthetic", parser_version="1",
                    ingestion_metadata={"sender": f"Sender {number:02d}", "unsafe": "hidden metadata"},
                ))
            db.add_all(payloads)
            await db.flush()
            observations = [TransactionObservation(
                source_payload_id=payload.id, source_item_key="0",
                amount=Decimal("-2.00") if number % 2 else None,
                currency="AED" if number % 2 else None,
                description="Source extraction" if number == 0 else None,
                raw_fragment=f"Synthetic source {number:02d} <script>alert('unsafe')</script>",
                extraction_metadata={},
            ) for number, payload in enumerate(payloads)]
            db.add_all(observations)
            await db.flush()
            db.add_all([TransactionSourceLink(
                transaction_id=self.data["transaction"], observation_id=observation.id,
                match_method="migration",
            ) for observation in observations])
            await db.commit()
            return [observation.id for observation in observations]

    def listed_ids(self, html):
        # Responsive table/card views may repeat the same record link.
        return list(dict.fromkeys(int(value) for value in re.findall(r'href="/transactions/(\d+)(?:[?"#])', html)))

    async def test_full_pages_fragments_history_and_private_caching(self):
        transaction = self.data["transaction"]
        for path in ["/transactions", "/transactions/new", f"/transactions/{transaction}", f"/transactions/{transaction}/edit"]:
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("<html", response.text.lower())
                self.assertIn("no-store", response.headers.get("cache-control", ""))
                self.assertIn('hx-history="false"', response.text)
        fragment = await self.client.get("/transactions", headers={"HX-Request": "true", "HX-Target": "transactions-results"})
        self.assertEqual(fragment.status_code, 200)
        self.assertNotIn("<html", fragment.text.lower())
        history = await self.client.get("/transactions", headers={"HX-Request": "true", "HX-History-Restore-Request": "true"})
        self.assertEqual(history.status_code, 200)
        self.assertIn("<html", history.text.lower())

    async def test_all_surfaces_require_an_active_cookie_session(self):
        transaction, source = self.data["transaction"], self.data["source"]
        paths = ["/transactions", "/transactions/new", f"/transactions/{transaction}",
                 f"/transactions/{transaction}/edit", f"/transactions/{transaction}/sources"]
        before = await self.snapshot()
        for identity in ["anonymous", "inactive", "expired"]:
            if identity == "anonymous":
                self.client.cookies.clear()
            else:
                self.login(self.data["inactive" if identity == "inactive" else "active"], expired=identity == "expired")
            for path in paths:
                with self.subTest(identity=identity, path=path):
                    ordinary = await self.client.get(path)
                    self.assertEqual(ordinary.status_code, 303)
                    self.assertEqual(ordinary.headers.get("location"), "/auth/login")
                    enhanced = await self.client.get(path, headers={"HX-Request": "true"})
                    self.assertEqual(enhanced.headers.get("hx-redirect"), "/auth/login")
                    self.assertNotIn("Synthetic original source", enhanced.text)
            for path in ["/transactions/new", f"/transactions/{transaction}/edit", f"/transactions/{transaction}/delete",
                         f"/transactions/{transaction}/sources/{source}/unlink",
                         f"/transactions/{transaction}/sources/move"]:
                response = await self.client.post(path, data={"confirmed": "yes"}, headers={"HX-Request": "true"})
                self.assertEqual(response.headers.get("hx-redirect"), "/auth/login")
        self.assertEqual(await self.snapshot(), before)

    async def test_shared_dataset_remains_visible_to_another_active_user(self):
        self.login(self.data["other"])
        response = await self.client.get(f"/transactions/{self.data['transaction']}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Synthetic legacy transaction", response.text)

    async def test_csrf_required_for_every_mutation_and_bound_to_session(self):
        transaction, source = self.data["transaction"], self.data["source"]
        before = await self.snapshot()
        for token in [None, "invalid-csrf", "несуществующий-токен"]:
            fields = {"confirmed": "yes"}
            if token is not None:
                fields["csrf_token"] = token
            for path in ["/transactions/new", f"/transactions/{transaction}/edit", f"/transactions/{transaction}/delete",
                         f"/transactions/{transaction}/sources/{source}/unlink",
                         f"/transactions/{transaction}/sources/move"]:
                with self.subTest(token=token, path=path):
                    response = await self.client.post(path, data=fields)
                    self.assertEqual(response.status_code, 403, response.text[:300])
        token = await self.csrf()
        self.login(self.data["other"])
        response = await self.client.post("/transactions/new", data=self.valid_fields(token))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(await self.snapshot(), before)

    async def test_cross_origin_cookie_reads_and_writes_cannot_expose_csrf_or_data(self):
        token = await self.csrf()
        before = await self.snapshot()
        transaction, source = self.data["transaction"], self.data["source"]
        for origin in ["http://testserver:9999", "https://evil.example", "null"]:
            for path in ["/transactions", "/transactions/new", f"/transactions/{transaction}"]:
                with self.subTest(origin=origin, path=path):
                    response = await self.client.get(path, headers={"Origin": origin})
                    self.assertEqual(response.status_code, 403)
                    self.assertIn("no-store", response.headers.get("cache-control", ""))
                    self.assertNotIn(token, response.text)
                    self.assertNotIn("Synthetic", response.text)
            denied = await self.client.post("/transactions/new", data=self.valid_fields(token), headers={"Origin": origin})
            self.assertEqual(denied.status_code, 403)
        self.assertEqual(await self.snapshot(), before)
        allowed = await self.client.get("/transactions/new", headers={"Origin": "http://testserver"})
        self.assertEqual(allowed.status_code, 200)
        created = await self.client.post("/transactions/new", data=self.valid_fields(token), headers={"Origin": "http://testserver"})
        self.assertEqual(created.status_code, 303)
        self.assertEqual(await self.snapshot(), (before[0] + 1, *before[1:]))

    async def test_create_normalizes_values_and_has_no_ingestion_side_effects(self):
        before = await self.snapshot()
        fields = self.valid_fields(await self.csrf())
        fields.update(amount="0", currency=" usd ", description="  Synthetic zero  ", location="  Test place  ",
                      transaction_kind="refund")
        response = await self.client.post("/transactions/new", data=fields)
        self.assertEqual(response.status_code, 303, response.text[:500])
        location = response.headers["location"]
        self.assertTrue(urlsplit(location).path.startswith("/transactions/"))
        created_id = int(urlsplit(location).path.rsplit("/", 1)[1])
        async with self.sessions() as db:
            transaction = await db.get(Transaction, created_id)
            self.assertEqual(transaction.amount, Decimal("0.00"))
            self.assertEqual(transaction.currency, "USD")
            self.assertEqual(transaction.description, "Synthetic zero")
            self.assertEqual(transaction.location, "Test place")
            self.assertEqual(transaction.transaction_kind, "refund")
            self.assertIsNone(transaction.transaction_datetime)
            self.assertIsNone(transaction.posting_datetime)
        after = await self.snapshot()
        self.assertEqual(after, (before[0] + 1, *before[1:]))
        fields["description"] = "HTMX-created synthetic transaction"
        enhanced = await self.client.post("/transactions/new", data=fields, headers={"HX-Request": "true"})
        self.assertEqual(enhanced.status_code, 200)
        self.assertTrue(enhanced.headers.get("hx-redirect", "").startswith("/transactions/"))

    async def test_invalid_forms_preserve_input_and_do_not_write(self):
        fields = self.valid_fields(await self.csrf())
        before = await self.snapshot()
        invalid = [dict(description="   "), dict(currency="US1"), dict(card_id="999999"), dict(amount="NaN"),
                   dict(amount="Infinity"), dict(amount="1.001"), dict(amount="10000000000000.00"),
                   dict(location="x" * 201), dict(original_amount="2.00"),
                   dict(original_amount="2", original_currency="USD", fx_rate="0"),
                   dict(original_amount="2", original_currency="USD", fx_rate="1.0000001"),
                   dict(original_amount="2", original_currency="USD", fx_rate="1000000000"),
                   dict(transaction_kind="invalid"), dict(transaction_datetime="not-a-date")]
        for change in invalid:
            with self.subTest(change=change):
                response = await self.client.post("/transactions/new", data={**fields, **change}, headers={"HX-Request": "true"})
                self.assertEqual(response.status_code, 422, response.text[:700])
                self.assertIn("csrf_token", response.text)
                if "description" not in change:
                    self.assertIn(fields["description"], response.text)
        self.assertEqual(await self.snapshot(), before)

    async def test_filter_pagination_counts_stable_order_and_last_page(self):
        ids = await self.add_transactions([
            {"description": f"Pagination fixture {number:02d}", "transaction_datetime": datetime(2026, 4, 1)}
            for number in range(55)
        ])
        first = await self.client.get("/transactions", params={"q": "Pagination fixture"})
        second = await self.client.get("/transactions", params={"q": "Pagination fixture", "page": 2})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(self.listed_ids(first.text), list(reversed(ids))[:50])
        self.assertEqual(self.listed_ids(second.text), list(reversed(ids))[50:])
        self.assertRegex(first.text, r"1\s*[–−-]\s*50\s+of\s+55")
        self.assertRegex(second.text, r"51\s*[–−-]\s*55\s+of\s+55")
        last = await self.client.get("/transactions", params={"q": "Pagination fixture", "page": 99}, follow_redirects=True)
        self.assertEqual(last.status_code, 200)
        self.assertEqual(self.listed_ids(last.text), list(reversed(ids))[50:])
        empty = await self.client.get("/transactions", params={"q": "No such synthetic record", "page": 9}, follow_redirects=True)
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(self.listed_ids(empty.text), [])

    async def test_filters_literal_search_direction_currency_and_absolute_bounds(self):
        ids = await self.add_transactions([
            {"description": "Filter fixture literal 10%_off", "amount": Decimal("-10.00")},
            {"description": "Filter fixture positive", "amount": Decimal("10.00")},
            {"description": "Filter fixture zero", "amount": Decimal("0.00")},
            {"description": "Filter fixture dollars", "amount": Decimal("-10.00"), "currency": "USD"},
            {"description": "Filter fixture alternative 10percent-off", "amount": Decimal("-20.00")},
        ])
        literal = await self.client.get("/transactions", params={"q": "  10%_OFF  "})
        self.assertEqual(self.listed_ids(literal.text), [ids[0]])
        for direction, expected in [("out", [ids[0]]), ("in", [ids[1]])]:
            response = await self.client.get("/transactions", params={"q": "Filter fixture", "currency": "AED",
                "direction": direction, "min_abs_amount": "10.00", "max_abs_amount": "10.00"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.listed_ids(response.text), expected)
        zero = await self.client.get("/transactions", params={"q": "Filter fixture", "currency": "AED",
            "min_abs_amount": "0", "max_abs_amount": "0"})
        self.assertEqual(self.listed_ids(zero.text), [ids[2]])
        invalid_filters = [
            {"min_abs_amount": "1"}, {"currency": "AED", "min_abs_amount": "-1"},
            {"currency": "AED", "min_abs_amount": "20", "max_abs_amount": "10"},
            {"account_id": self.data["account"], "card_id": self.data["foreign_card"]},
            {"period": "custom", "date_from": "2026-02-02", "date_to": "2026-02-01"},
            {"period": "custom", "date_from": "2026-02-02"}, {"account_id": "999999"},
            {"currency": "US1"}, {"direction": "sideways"}, {"page": "-1"},
        ]
        for params in invalid_filters:
            with self.subTest(params=params):
                response = await self.client.get("/transactions", params=params)
                self.assertEqual(response.status_code, 422, response.text[:600])
                self.assertNotIn("Filter fixture positive", response.text)

    async def test_dates_include_complete_days_and_use_posting_fallback_without_creation_date(self):
        ids = await self.add_transactions([
            {"description": "Boundary fixture start", "transaction_datetime": datetime(2026, 4, 2)},
            {"description": "Boundary fixture end", "posting_datetime": datetime(2026, 4, 2, 23, 59, 59, 999999)},
            {"description": "Boundary fixture yesterday", "transaction_datetime": datetime(2026, 4, 1, 23, 59, 59, 999999)},
            {"description": "Boundary fixture tomorrow", "transaction_datetime": datetime(2026, 4, 3)},
            {"description": "Boundary fixture undated", "created_at": datetime(2026, 4, 2)},
            {"description": "Boundary fixture posting precedence", "transaction_datetime": datetime(2026, 4, 2),
             "posting_datetime": datetime(2026, 4, 3)},
        ])
        day = await self.client.get("/transactions", params={"q": "Boundary fixture", "period": "custom",
                                                             "date_from": "2026-04-02", "date_to": "2026-04-02"})
        self.assertEqual(day.status_code, 200)
        self.assertEqual(self.listed_ids(day.text), [ids[1], ids[0]])
        all_time = await self.client.get("/transactions", params={"q": "Boundary fixture"})
        self.assertEqual(self.listed_ids(all_time.text), [ids[5], ids[3], ids[1], ids[0], ids[2], ids[4]])
        self.assertIn("No date", all_time.text)

    async def test_list_displays_transaction_date_before_posting_date(self):
        await self.add_transactions([
            {"description": "Display date precedence", "transaction_datetime": datetime(2026, 4, 2, 10, 30),
             "posting_datetime": datetime(2026, 4, 3, 11, 45)},
            {"description": "Display date posting fallback", "posting_datetime": datetime(2026, 4, 4, 12, 15)},
        ])
        response = await self.client.get("/transactions", params={"q": "Display date"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text.count("Thu, 02 Apr 2026 10:30:00"), 2)
        self.assertNotIn("Fri, 03 Apr 2026 11:45:00", response.text)
        self.assertEqual(response.text.count("Sat, 04 Apr 2026 12:15:00"), 2)
        self.assertEqual(response.text.count('data-local-datetime'), 4)
        self.assertIn('datetime="2026-04-02T10:30:00"', response.text)
        self.assertEqual(response.text.count(">Transaction date</span>"), 2)
        self.assertEqual(response.text.count(">Posted</span>"), 2)

    async def test_detail_and_sources_mark_timestamps_for_localized_display_without_microseconds(self):
        response = await self.client.get(f"/transactions/{self.data['transaction']}")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.text.count('data-local-datetime'), 7)
        self.assertIn(">Mon, 16 Feb 2026 12:34:56</time>", response.text)

    async def test_this_month_uses_explicit_dates_for_ordinary_and_htmx_history(self):
        today = datetime.now().date()
        first_day = today.replace(day=1)
        last_day = (first_day + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        params = {"period": "month", "q": "synthetic", "currency": "AED"}
        ordinary = await self.client.get("/transactions", params=params)
        self.assertEqual(ordinary.status_code, 303)
        canonical = ordinary.headers["location"]
        self.assertEqual(urlsplit(canonical).path, "/transactions")
        expected = {"period": ["custom"], "date_from": [first_day.isoformat()], "date_to": [last_day.isoformat()],
                    "q": ["synthetic"], "currency": ["AED"]}
        self.assertEqual(parse_qs(urlsplit(canonical).query), expected)
        reopened = await self.client.get(canonical)
        self.assertEqual(reopened.status_code, 200)
        fields = Forms(reopened.text).for_action("/transactions")
        self.assertEqual({key: fields[key] for key in expected}, {key: values[0] for key, values in expected.items()})

        enhanced = await self.client.get("/transactions", params=params, headers={"HX-Request": "true"})
        self.assertEqual(enhanced.status_code, 200)
        self.assertEqual(enhanced.headers["HX-Push-Url"], canonical)
        self.assertNotIn("<html", enhanced.text.lower())
        enhanced_fields = Forms(enhanced.text).for_action("/transactions")
        self.assertEqual(enhanced_fields["period"], "custom")
        self.assertEqual(enhanced_fields["date_from"], first_day.isoformat())
        self.assertEqual(enhanced_fields["date_to"], last_day.isoformat())
        self.assertEqual(self.listed_ids(enhanced.text), self.listed_ids(reopened.text))

    async def test_edit_preserves_untouched_precision_legacy_fx_fee_and_sources(self):
        path = f"/transactions/{self.data['transaction']}/edit"
        fields = await self.form(path)
        before = await self.snapshot()
        fields["description"] = "Unrelated edit to legacy record"
        response = await self.client.post(path, data=fields)
        self.assertEqual(response.status_code, 303, response.text[:800])
        async with self.sessions() as db:
            transaction = await db.get(Transaction, self.data["transaction"])
            payload = await db.get(SourcePayload, self.data["payload"])
            observation = await db.get(TransactionObservation, self.data["source"])
            self.assertEqual(transaction.transaction_datetime, self.data["precise"])
            self.assertEqual(transaction.posting_datetime, self.data["precise"] + timedelta(hours=1))
            self.assertEqual(transaction.original_amount, Decimal("-3.36"))
            self.assertIsNone(transaction.original_currency)
            self.assertEqual(transaction.fx_rate, Decimal("3.672500"))
            self.assertEqual(transaction.fx_fee, Decimal("0.25"))
            self.assertIn("Synthetic original source", payload.raw_text)
            self.assertEqual(observation.description, "Source extraction")
        self.assertEqual(await self.snapshot(), before)

    async def test_edit_clears_nullable_fields_and_rejects_card_change(self):
        transaction_id = self.data["transaction"]
        async with self.sessions() as db:
            transaction = await db.get(Transaction, transaction_id)
            transaction.original_currency = "USD"
            await db.commit()
        path = f"/transactions/{transaction_id}/edit"
        fields = await self.form(path)
        changed_card = await self.client.post(path, data={**fields, "card_id": str(self.data["foreign_card"])})
        self.assertEqual(changed_card.status_code, 422)
        fields.update(transaction_datetime="", posting_datetime="", location="", original_amount="", original_currency="")
        response = await self.client.post(path, data=fields)
        self.assertEqual(response.status_code, 303, response.text[:800])
        async with self.sessions() as db:
            transaction = await db.get(Transaction, transaction_id)
            self.assertEqual(transaction.card_id, self.data["card"])
            for field in ["transaction_datetime", "posting_datetime", "location", "original_amount", "original_currency", "fx_rate"]:
                self.assertIsNone(getattr(transaction, field), field)
            self.assertEqual(transaction.fx_fee, Decimal("0.25"))

    async def test_changed_legacy_fx_group_requires_consistent_pair(self):
        path = f"/transactions/{self.data['transaction']}/edit"
        fields = await self.form(path)
        fields["original_amount"] = "-4.00"
        response = await self.client.post(path, data=fields)
        self.assertEqual(response.status_code, 422)
        async with self.sessions() as db:
            transaction = await db.get(Transaction, self.data["transaction"])
            self.assertEqual(transaction.original_amount, Decimal("-3.36"))

    async def test_clearing_incomplete_legacy_pair_also_clears_saved_rate(self):
        path = f"/transactions/{self.data['transaction']}/edit"
        fields = await self.form(path)
        self.assertEqual(fields["original_currency"], "")
        fields.update(original_amount="", original_currency="")
        response = await self.client.post(path, data=fields)
        self.assertEqual(response.status_code, 303, response.text[:800])
        async with self.sessions() as db:
            transaction = await db.get(Transaction, self.data["transaction"])
            self.assertIsNone(transaction.original_amount)
            self.assertIsNone(transaction.original_currency)
            self.assertIsNone(transaction.fx_rate)
            self.assertEqual(transaction.fx_fee, Decimal("0.25"))

    async def test_confirmed_unlink_delete_preserve_source_file_and_other_links(self):
        transaction, source = self.data["transaction"], self.data["source"]
        token = await self.csrf()
        before = await self.snapshot()
        unlink_path = f"/transactions/{transaction}/sources/{source}/unlink"
        confirmation = await self.client.post(unlink_path, data={"csrf_token": token})
        self.assertEqual(confirmation.status_code, 200)
        self.assertIn("Unlink", confirmation.text)
        self.assertIn("canonical transaction values may change", confirmation.text)
        self.assertEqual(await self.snapshot(), before)
        unlinked = await self.client.post(unlink_path, data={"csrf_token": token, "confirmed": "yes"})
        self.assertEqual(unlinked.status_code, 303)
        async with self.sessions() as db:
            self.assertIsNone(await db.get(TransactionSourceLink, source))
            self.assertIsNotNone(await db.get(TransactionSourceLink, self.data["other_source"]))
            self.assertIsNotNone(await db.get(TransactionObservation, source))
            self.assertIsNotNone(await db.get(SourcePayload, self.data["payload"]))
        self.assertTrue(self.data["file"].is_file())
        delete_path = f"/transactions/{self.data['other_transaction']}/delete"
        confirmation = await self.client.post(delete_path, data={"csrf_token": token})
        self.assertEqual(confirmation.status_code, 200)
        self.assertIn("Other linked transaction", confirmation.text)
        removed = await self.client.post(delete_path, data={"csrf_token": token, "confirmed": "yes"})
        self.assertEqual(removed.status_code, 303)
        self.assertEqual(urlsplit(removed.headers["location"]).path, "/transactions")
        async with self.sessions() as db:
            self.assertIsNone(await db.get(Transaction, self.data["other_transaction"]))
            self.assertIsNotNone(await db.get(Transaction, transaction))
            self.assertIsNotNone(await db.get(TransactionObservation, self.data["other_source"]))
            self.assertIsNotNone(await db.get(SourcePayload, self.data["other_payload"]))
            self.assertIsNotNone(await db.get(Card, self.data["foreign_card"]))
            self.assertIsNotNone(await db.get(Account, self.data["foreign_account"]))
        self.assertTrue(self.data["file"].is_file())

    async def test_move_observation_uses_atomic_service_and_refreshes_the_source_transaction(self):
        transaction, source = self.data["transaction"], self.data["source"]
        target = (await self.add_transactions([{
            "description": "Move destination", "amount": Decimal("-1.00"),
        }]))[0]
        details = await self.client.get(f"/transactions/{transaction}")
        move_path = f"/transactions/{transaction}/sources/move"
        self.assertIn("/static/js/transactions.js?v=move-observation-modal-1", details.text)
        self.assertIn('data-move-observation-trigger', details.text)
        self.assertIn("Move observation", details.text)
        self.assertIn('id="move-observation-dialog"', details.text)
        fields = Forms(details.text).for_action(move_path)
        self.assertIn("Destination transaction ID", details.text)
        self.assertIn(str(target), details.text)
        async with self.sessions() as db:
            self.assertEqual((await db.get(TransactionSourceLink, source)).transaction_id, transaction)

        moved = await self.client.post(
            move_path,
            data={**fields, "observation_id": str(source), "transaction_id": str(target)},
        )
        self.assertEqual(moved.status_code, 303, moved.text[:800])
        self.assertIn(f"moved_to={target}", moved.headers["location"])
        refreshed = await self.client.get(moved.headers["location"])
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn(f"Observation moved to transaction #{target}", refreshed.text)
        self.assertNotIn(f"Observation #{source}", refreshed.text)
        async with self.sessions() as db:
            link = await db.get(TransactionSourceLink, source)
            destination = await db.get(Transaction, target)
            self.assertEqual(link.transaction_id, target)
            self.assertEqual(link.match_method, "manual")
            self.assertIsNone(link.match_confidence)
            self.assertEqual(destination.amount, Decimal("-12.34"))
            self.assertEqual(destination.description, "Source extraction")

    async def test_move_observation_rejects_invalid_or_stale_destination_without_changing_link(self):
        transaction, source = self.data["transaction"], self.data["source"]
        move_path = f"/transactions/{transaction}/sources/move"
        fields = Forms((await self.client.get(f"/transactions/{transaction}")).text).for_action(move_path)
        invalid = await self.client.post(move_path, data={**fields, "observation_id": str(source), "transaction_id": str(transaction)})
        self.assertEqual(invalid.status_code, 422)
        self.assertIn("Choose a different destination transaction", invalid.text)
        missing = await self.client.post(move_path, data={**fields, "observation_id": str(source), "transaction_id": "999999"})
        self.assertEqual(missing.status_code, 422)
        self.assertIn("Destination transaction not found", missing.text)
        async with self.sessions() as db:
            self.assertEqual((await db.get(TransactionSourceLink, source)).transaction_id, transaction)
            link = await db.get(TransactionSourceLink, source)
            link.transaction_id = self.data["other_transaction"]
            await db.commit()
        stale = await self.client.post(
            move_path,
            data={**fields, "observation_id": str(source), "transaction_id": str(self.data["other_transaction"])},
        )
        self.assertEqual(stale.status_code, 404)
        self.assertIn("no longer linked", stale.text)
        async with self.sessions() as db:
            self.assertEqual(
                (await db.get(TransactionSourceLink, source)).transaction_id,
                self.data["other_transaction"],
            )

    async def test_move_observation_keeps_the_link_when_destination_dates_conflict(self):
        transaction, source = self.data["transaction"], self.data["source"]
        target = (await self.add_transactions([{"description": "Conflicting move destination"}]))[0]
        async with self.sessions() as db:
            payload = SourcePayload(
                source_kind="sms", media_type="text/plain", ingestion_method="migration",
                raw_text="Synthetic conflicting source", content_hash="e" * 64,
                processing_status="processed", ingestion_metadata={},
            )
            db.add(payload)
            await db.flush()
            observation = TransactionObservation(
                source_payload_id=payload.id, source_item_key="conflicting-date",
                transaction_datetime=datetime(2026, 2, 17), extraction_metadata={},
            )
            db.add(observation)
            await db.flush()
            db.add(TransactionSourceLink(
                transaction_id=target, observation_id=observation.id, match_method="manual",
            ))
            await db.commit()
        move_path = f"/transactions/{transaction}/sources/move"
        fields = Forms((await self.client.get(f"/transactions/{transaction}")).text).for_action(move_path)
        rejected = await self.client.post(
            move_path,
            data={**fields, "observation_id": str(source), "transaction_id": str(target)},
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertIn("date conflicts", rejected.text)
        async with self.sessions() as db:
            self.assertEqual((await db.get(TransactionSourceLink, source)).transaction_id, transaction)

    async def test_htmx_unlink_refreshes_canonical_transaction_and_checks_parent(self):
        async with self.sessions() as db:
            statement = SourcePayload(
                source_kind="bank_statement", media_type="application/pdf",
                ingestion_method="manual_upload", original_filename="canonical.pdf",
                content_hash="d" * 64, received_at=datetime(2026, 4, 2),
                processing_status="processed", ingestion_metadata={},
            )
            db.add(statement)
            await db.flush()
            observation = TransactionObservation(
                source_payload_id=statement.id, source_item_key="row-1",
                amount=Decimal("-50.00"), currency="AED",
                posting_datetime=datetime(2026, 2, 17), description="Statement canonical",
                transaction_kind="purchase", extraction_metadata={},
            )
            db.add(observation)
            await db.flush()
            db.add(TransactionSourceLink(
                transaction_id=self.data["transaction"], observation_id=observation.id,
                match_method="automatic",
            ))
            transaction = await db.get(Transaction, self.data["transaction"])
            transaction.amount = Decimal("-50.00")
            transaction.description = "Statement canonical"
            await db.commit()
            observation_id = observation.id

        response = await self.client.post(
            f"/transactions/{self.data['transaction']}/sources/{observation_id}/unlink",
            data={"csrf_token": await self.csrf(), "confirmed": "yes"},
            headers={"HX-Request": "true", "HX-Target": "transaction-detail"},
        )
        self.assertEqual(response.status_code, 200, response.text[:800])
        self.assertIn('id="transaction-detail"', response.text)
        self.assertNotIn("<html", response.text.lower())
        self.assertIn("−12.34 AED", response.text)
        self.assertIn("Source extraction", response.text)
        self.assertNotIn("Statement canonical", response.text)
        async with self.sessions() as db:
            transaction = await db.get(Transaction, self.data["transaction"])
            self.assertEqual(transaction.amount, Decimal("-12.34"))
            self.assertEqual(transaction.description, "Source extraction")
            self.assertIsNone(await db.get(TransactionSourceLink, observation_id))
            self.assertIsNotNone(await db.get(TransactionObservation, observation_id))

        wrong_parent = await self.client.post(
            f"/transactions/{self.data['transaction']}/sources/{self.data['other_source']}/unlink",
            data={"csrf_token": await self.csrf(), "confirmed": "yes"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(wrong_parent.status_code, 200)
        self.assertIn("This link no longer exists", wrong_parent.text)
        async with self.sessions() as db:
            self.assertIsNotNone(await db.get(TransactionSourceLink, self.data["other_source"]))

    async def test_missing_ids_and_missing_links_have_safe_recovery(self):
        for path in ["/transactions/999999", "/transactions/999999/edit", "/transactions/not-an-id",
                     "/transactions/-1", "/transactions/999999/sources", "/transactions/sources/999999/download"]:
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 404)
        token = await self.csrf()
        missing = await self.client.post(f"/transactions/{self.data['transaction']}/sources/999999/unlink",
                                         data={"csrf_token": token, "confirmed": "yes"}, headers={"HX-Request": "true"})
        self.assertIn(missing.status_code, (200, 404))
        self.assertIn("source", missing.text.lower())
        self.assertNotIn("Internal Server Error", missing.text)

    async def test_oversized_record_ids_recover_without_binding_or_writing(self):
        token = await self.csrf()
        before = await self.snapshot()
        for identifier in ["2147483648", "9" * 100]:
            for path in [f"/transactions/{identifier}", f"/transactions/{identifier}/edit",
                         f"/transactions/{identifier}/sources", f"/transactions/sources/{identifier}/download"]:
                with self.subTest(read=path):
                    response = await self.client.get(path)
                    self.assertEqual(response.status_code, 404)
                    if not path.endswith("/download"):
                        self.assertIn("Back to transactions", response.text)
            for name in ["account_id", "card_id"]:
                with self.subTest(filter=name, identifier=identifier):
                    response = await self.client.get("/transactions", params={name: identifier})
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(self.listed_ids(response.text), [])
            with self.subTest(create=identifier):
                response = await self.client.post("/transactions/new", data={**self.valid_fields(token), "card_id": identifier})
                self.assertEqual(response.status_code, 422)
            with self.subTest(unlink=identifier):
                response = await self.client.post(f"/transactions/{self.data['transaction']}/sources/{identifier}/unlink",
                    data={"csrf_token": token, "confirmed": "yes"}, headers={"HX-Request": "true"})
                self.assertEqual(response.status_code, 200)
                self.assertIn("This link no longer exists", response.text)
        self.assertEqual(await self.snapshot(), before)

    async def test_source_states_escaping_pagination_and_preserved_extraction(self):
        await self.add_sources(22)
        transaction = self.data["transaction"]
        async with self.sessions() as db:
            shared = TransactionObservation(
                source_payload_id=self.data["payload"], source_item_key="sms-1",
                description="Second observation from shared payload", extraction_metadata={},
            )
            db.add(shared)
            await db.flush()
            db.add(TransactionSourceLink(
                transaction_id=transaction, observation_id=shared.id, match_method="manual",
            ))
            await db.commit()
            shared_id = shared.id
        before = await self.snapshot()
        first = await self.client.get(f"/transactions/{transaction}/sources", params={"source_page": 1})
        second = await self.client.get(f"/transactions/{transaction}/sources", params={"source_page": 2})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        joined = first.text + second.text
        for label in ["Pending", "Processing", "Processed", "Ignored", "Failed", "Unknown status"]:
            self.assertIn(label, joined)
        self.assertIn("&lt;script&gt;", joined)
        self.assertNotIn("<script>alert('unsafe')</script>", joined)
        self.assertNotIn("<img src=x onerror=alert(1)>", joined)
        self.assertNotIn("a" * 64, joined)
        self.assertNotIn(str(self.upload_dir), joined)
        self.assertNotIn("hidden metadata", joined)
        self.assertNotIn("Download file", joined)
        self.assertIn("No extracted data", joined)
        self.assertIn("Source extraction", joined)
        self.assertIn(f"Observation #{shared_id}", joined)
        self.assertEqual(joined.count(f"Payload #{self.data['payload']} · SMS"), 2)
        for value in [
            "text/plain · Phone API", "Original filename: statement &lt;unsafe&gt;.txt",
            "Private attachment stored", "Parser: synthetic_parser · version 1-test",
            "Card last four digits", "Extraction confidence", "87.50%",
            "Match method", "Automatic", "Match confidence", "90.00%",
            "Synthetic sender", "Synthetic recipients",
        ]:
            self.assertIn(value, joined)
        previews1 = set(re.findall(r"Synthetic source (\d{2})", first.text))
        previews2 = set(re.findall(r"Synthetic source (\d{2})", second.text))
        self.assertFalse(previews1 & previews2)
        self.assertEqual(len(previews1 | previews2), 22)
        self.assertEqual(await self.snapshot(), before)

    async def test_unlink_last_source_on_page_returns_to_available_page(self):
        source_ids = await self.add_sources(20)
        transaction = self.data["transaction"]
        page = await self.client.get(f"/transactions/{transaction}/sources", params={"source_page": 2})
        self.assertEqual(page.status_code, 200)
        # The baseline source has a later creation date; source 00 is now last.
        source_id = source_ids[0]
        response = await self.client.post(f"/transactions/{transaction}/sources/{source_id}/unlink",
            data={"csrf_token": await self.csrf(), "confirmed": "yes", "source_page": "2"},
            headers={"HX-Request": "true", "HX-Target": "transaction-sources"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Synthetic source 19", response.text)
        self.assertNotIn("Synthetic source 00", response.text)
        async with self.sessions() as db:
            observation = await db.get(TransactionObservation, source_id)
            self.assertIsNotNone(observation)
            self.assertIsNotNone(await db.get(SourcePayload, observation.source_payload_id))
            self.assertIsNone(await db.get(TransactionSourceLink, source_id))

    async def test_return_urls_reject_external_paths_and_unapproved_parameters(self):
        bad_urls = ["https://evil.example/transactions", "//evil.example/transactions", "/auth/logout",
                    "/transactions?next=https://evil.example", "/transactions?page=-1", "/transactions?currency=US1"]
        for value in bad_urls:
            with self.subTest(value=value):
                fields = await self.form("/transactions/new", params={"return_url": value})
                returned = fields.get("return_url", "/transactions")
                parsed = urlsplit(returned)
                self.assertFalse(parsed.netloc)
                self.assertFalse(parsed.scheme)
                self.assertEqual(parsed.path, "/transactions")
                self.assertNotIn("next", parse_qs(parsed.query))
                self.assertNotEqual(parse_qs(parsed.query).get("page"), ["-1"])
                self.assertNotEqual(parse_qs(parsed.query).get("currency"), ["US1"])
        allowed = "/transactions?q=synthetic&currency=AED&page=2"
        fields = await self.form("/transactions/new", params={"return_url": allowed})
        self.assertEqual(parse_qs(urlsplit(fields["return_url"]).query), parse_qs(urlsplit(allowed).query))

    async def test_no_cards_disables_creation_and_shows_explanation(self):
        async with self.sessions() as db:
            for model in [TransactionSourceLink, TransactionObservation, Transaction, Card]:
                await db.execute(delete(model))
            await db.commit()
        response = await self.client.get("/transactions/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Add a card before creating a transaction", response.text)

    async def test_private_files_and_unlinked_observations_are_not_exposed(self):
        old_download = await self.client.get(f"/transactions/sources/{self.data['source']}/download")
        self.assertEqual(old_download.status_code, 404)
        async with self.sessions() as db:
            payload = SourcePayload(
                source_kind="sms", media_type="text/plain", ingestion_method="phone_api",
                raw_text="Unlinked private source", file_path="/private/storage/secret.payload",
                original_filename="private-source.txt", content_hash="c" * 64,
                processing_status="processed", ingestion_metadata={},
            )
            db.add(payload)
            await db.flush()
            observation = TransactionObservation(
                source_payload_id=payload.id, source_item_key="unlinked",
                description="Unlinked observation must stay hidden", extraction_metadata={},
            )
            db.add(observation)
            await db.commit()
        details = await self.client.get(f"/transactions/{self.data['transaction']}")
        self.assertEqual(details.status_code, 200)
        self.assertIn("Private attachment stored", details.text)
        self.assertNotIn(str(self.upload_dir), details.text)
        self.assertNotIn("Synthetic attachment only", details.text)
        self.assertNotIn("Unlinked observation must stay hidden", details.text)
        self.assertNotIn("/private/storage/secret.payload", details.text)

    async def test_read_failures_offer_retry_and_writes_never_replay(self):
        transaction, source = self.data["transaction"], self.data["source"]
        return_url = "/transactions?q=synthetic&page=2&currency=AED"
        for path, target, params in [
            ("/transactions", "app.web.transactions.transaction_service.get_transactions", {"q": "synthetic & literal", "page": "2"}),
            ("/transactions/new", "app.web.transactions.transaction_service.get_transaction_references", {"return_url": return_url}),
            (f"/transactions/{transaction}", "app.web.transactions.transaction_service.get_transaction", {"return_url": return_url}),
            (f"/transactions/{transaction}/sources", "app.web.transactions.transaction_service.get_transaction", {"source_page": "2", "return_url": return_url}),
            (f"/transactions/{transaction}/edit", "app.web.transactions.transaction_service.get_transaction", {"return_url": return_url}),
        ]:
            with self.subTest(read=path), patch(target, new_callable=AsyncMock, side_effect=SQLAlchemyError("synthetic read failure")) as call:
                response = await self.client.get(path, params=params)
                self.assertEqual(response.status_code, 503)
                retry = re.search(r'<a href="([^"]+)"[^>]*>Retry</a>', response.text)
                self.assertIsNotNone(retry)
                target_url = urlsplit(unescape(retry.group(1)))
                self.assertEqual(target_url.path, path)
                self.assertEqual(parse_qs(target_url.query), {key: [value] for key, value in params.items()})
                self.assertNotIn("synthetic read failure", response.text)
                call.assert_awaited_once()
        token = await self.csrf()
        before = await self.snapshot()
        writes = [
            ("/transactions/new", "app.web.transactions.transaction_service.create_transaction", self.valid_fields(token)),
            (f"/transactions/{transaction}/edit", "app.web.transactions.transaction_service.update_transaction",
             {"csrf_token": token, "description": "This write fails"}),
            (f"/transactions/{transaction}/delete", "app.web.transactions.transaction_service.delete_transaction",
             {"csrf_token": token, "confirmed": "yes"}),
            (f"/transactions/{transaction}/sources/{source}/unlink", "app.web.transactions.source_processing_service.unlink_observation",
             {"csrf_token": token, "confirmed": "yes"}),
        ]
        for path, target, fields in writes:
            with self.subTest(write=path), patch(target, new_callable=AsyncMock, side_effect=SQLAlchemyError("synthetic write failure")) as call:
                response = await self.client.post(path, data=fields, headers={"HX-Request": "true"})
                self.assertEqual(response.status_code, 503, response.text[:600])
                self.assertIn("could not be confirmed", response.text)
                self.assertIn("Refresh", response.text)
                self.assertNotIn("synthetic write failure", response.text)
                call.assert_awaited_once()
        self.assertEqual(await self.snapshot(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
