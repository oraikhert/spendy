"""Isolated transaction schema, service and JSON API regressions.

Run from the repository root: python tests/test_transaction_service.py
No personal database, external server, or network service is used.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["DEBUG"] = "false"
os.environ["SECRET_KEY"] = "synthetic-transaction-service-test-secret"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.transactions import router
from app.core.security import create_access_token
from app.database import Base, get_db
from app.models import (
    Account, Card, SourcePayload, Transaction, TransactionObservation,
    TransactionSourceLink, User,
)
from app.schemas.transaction import TransactionCreate, TransactionResponse, TransactionUpdate
from app.services import transaction_service as service


BASE_INPUT = {
    "card_id": 1, "amount": "-12.34", "currency": "AED",
    "description": "Synthetic purchase", "transaction_kind": "purchase",
}


class TransactionInputTests(unittest.TestCase):
    def test_normalization_and_numeric_boundaries(self):
        data = TransactionCreate(**{
            **BASE_INPUT, "amount": "0", "currency": " aEd ",
            "description": "  Synthetic purchase \n", "location": "  Somewhere  ",
            "original_amount": "-9999999999999.99", "original_currency": " usd ",
            "fx_rate": "999999999.999999",
            "transaction_datetime": "2026-02-16T12:34:56.123456+04:00",
        })
        self.assertEqual(data.amount, Decimal("0"))
        self.assertEqual(data.currency, "AED")
        self.assertEqual(data.original_currency, "USD")
        self.assertEqual(data.description, "Synthetic purchase")
        self.assertEqual(data.location, "Somewhere")
        self.assertEqual(data.transaction_datetime.microsecond, 123456)
        self.assertEqual(data.transaction_datetime.utcoffset(), timedelta(hours=4))
        self.assertIsNone(TransactionUpdate(location="   ").location)
        self.assertEqual(TransactionUpdate().model_dump(exclude_unset=True), {})
        self.assertEqual(TransactionUpdate(location=None).model_dump(exclude_unset=True), {"location": None})

    def test_invalid_fields_and_required_nulls(self):
        cases = [
            {"amount": "NaN"}, {"amount": "Infinity"}, {"amount": "-Infinity"},
            {"amount": "0.001"}, {"amount": "10000000000000"},
            {"currency": "A1D"}, {"currency": "АЕД"}, {"currency": "aß"},
            {"description": " \n "}, {"location": "x" * 201},
            {"transaction_kind": "transfer"}, {"card_id": 0},
            {"card_id": 2**31}, {"card_id": 999999999999999999999999},
            {"original_amount": "1"}, {"original_currency": "USD"},
            {"fx_rate": "1"},
            {"original_amount": "1", "original_currency": "USD", "fx_rate": "0"},
            {"original_amount": "1", "original_currency": "USD", "fx_rate": "0.0000001"},
            {"original_amount": "1", "original_currency": "USD", "fx_rate": "1000000000"},
            {"original_amount": "1", "original_currency": "USD", "fx_rate": "NaN"},
        ]
        for patch in cases:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                TransactionCreate(**{**BASE_INPUT, **patch})
        for name in ("amount", "currency", "description", "transaction_kind"):
            with self.subTest(required=name), self.assertRaises(ValidationError):
                TransactionUpdate(**{name: None})
        with self.assertRaises(ValidationError):
            TransactionUpdate(card_id=1)

    def test_response_does_not_revalidate_legacy_input_rules(self):
        legacy = TransactionResponse(
            **{**BASE_INPUT, "description": "", "currency": "aed"},
            id=1, original_currency="USD", original_amount=None, fx_rate=Decimal("0"),
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )
        self.assertEqual(legacy.description, "")
        self.assertEqual(legacy.currency, "aed")
        self.assertEqual(legacy.fx_rate, Decimal("0"))


class TransactionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.statements = []

        @event.listens_for(self.engine.sync_engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(self.engine.sync_engine, "before_cursor_execute")
        def capture_sql(_connection, _cursor, statement, _parameters, _context, _many):
            self.statements.append(statement)

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.accounts = [
            Account(institution="Synthetic bank", name="Family", account_currency="AED"),
            Account(institution="Other bank", name="Travel", account_currency="USD"),
        ]
        self.db.add_all(self.accounts)
        await self.db.flush()
        self.cards = [
            Card(account_id=self.accounts[0].id, name="Everyday", card_masked_number="**** 1111", card_type="debit"),
            Card(account_id=self.accounts[1].id, name="Travel", card_masked_number="**** 2222", card_type="credit"),
        ]
        self.db.add_all(self.cards)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def record(self, **values):
        data = {**BASE_INPUT, "card_id": self.cards[0].id, **values}
        transaction = Transaction(**data)
        self.db.add(transaction)
        await self.db.commit()
        return transaction

    async def test_transaction_date_sort_ties_undated_and_relationships(self):
        undated = await self.record(description="No date", created_at=datetime(2030, 1, 1))
        older = await self.record(posting_datetime=datetime(2026, 2, 1), transaction_datetime=datetime(2026, 3, 1))
        newer = await self.record(transaction_datetime=datetime(2026, 2, 10))
        tie = await self.record(transaction_datetime=datetime(2026, 2, 10))
        self.db.expunge_all()
        rows, total = await service.get_transactions(self.db, limit=2)
        self.assertEqual(total, 4)
        self.assertEqual([row.id for row in rows], [older.id, tie.id])
        self.assertEqual(rows[0].card.account.name, "Family")
        rows, _ = await service.get_transactions(self.db, limit=2, offset=2)
        self.assertEqual([row.id for row in rows], [newer.id, undated.id])
        rows, total = await service.get_transactions(
            self.db,
            date_from=datetime(2026, 2, 1),
            date_to=datetime(2026, 2, 28, 23, 59, 59, 999999),
        )
        self.assertEqual(total, 2)
        self.assertEqual([row.id for row in rows], [tie.id, newer.id])
        selected = await service.get_transaction(self.db, newer.id)
        self.assertEqual(selected.card.account.institution, "Synthetic bank")

    async def test_full_inclusive_date_bounds_and_literal_search(self):
        start = datetime(2026, 2, 16)
        finish = datetime(2026, 2, 16, 23, 59, 59, 999999)
        first = await self.record(description="Shop 10%_off", transaction_datetime=start)
        last = await self.record(description="SHOP 10%_OFF", posting_datetime=finish)
        await self.record(description="Shop 100Xoff", transaction_datetime=start)
        await self.record(description="Shop 10%_off", transaction_datetime=finish + timedelta(microseconds=1))
        await self.record(description="Shop 10%_off")
        rows, total = await service.get_transactions(self.db, date_from=start, date_to=finish, q="  shop 10%_off  ")
        self.assertEqual(total, 2)
        self.assertEqual([row.id for row in rows], [last.id, first.id])
        backslash = await self.record(description="Synthetic \\ store")
        rows, total = await service.get_transactions(self.db, q="\\")
        self.assertEqual((total, rows[0].id), (1, backslash.id))

    async def test_all_filters_signed_and_absolute_zero_and_paging(self):
        negative = await self.record(amount=Decimal("-10"), currency="AED", transaction_kind="refund")
        positive = await self.record(amount=Decimal("10"), currency="AED")
        zero = await self.record(amount=Decimal("0"), currency="AED")
        await self.record(amount=Decimal("-10"), currency="USD", card_id=self.cards[1].id)
        rows, total = await service.get_transactions(
            self.db, account_id=self.accounts[0].id, card_id=self.cards[0].id,
            currency=" aed ", direction="out", min_abs_amount=Decimal("10"),
            max_abs_amount=Decimal("10"), kind="refund", limit=1,
        )
        self.assertEqual((total, rows[0].id), (1, negative.id))
        rows, total = await service.get_transactions(self.db, currency="AED", direction="in")
        self.assertEqual((total, rows[0].id), (1, positive.id))
        rows, total = await service.get_transactions(self.db, currency="AED", min_abs_amount=0, max_abs_amount=0)
        self.assertEqual((total, rows[0].id), (1, zero.id))
        rows, total = await service.get_transactions(self.db, min_amount=Decimal("-10"), max_amount=Decimal("-10"))
        self.assertEqual(total, 2)
        self.assertTrue(all(row.amount == Decimal("-10") for row in rows))
        # The old positional call contract remains valid.
        rows, total = await service.get_transactions(self.db, None, None, None, None, None, None, None, None, 1, 1)
        self.assertEqual((total, len(rows)), (4, 1))

    async def test_invalid_query_combinations(self):
        invalid = [
            {"account_id": 9999}, {"card_id": 9999},
            {"account_id": 2**31}, {"card_id": 2**31},
            {"account_id": 999999999999999999999999}, {"card_id": 999999999999999999999999},
            {"account_id": self.accounts[0].id, "card_id": self.cards[1].id},
            {"date_from": datetime(2026, 2, 2), "date_to": datetime(2026, 2, 1)},
            {"date_from": datetime(2026, 2, 1), "date_to": datetime(2026, 2, 2, tzinfo=timezone.utc)},
            {"kind": "invalid"}, {"direction": "invalid"}, {"currency": "US"},
            {"min_abs_amount": Decimal("1")},
            {"currency": "AED", "min_abs_amount": Decimal("-1")},
            {"currency": "AED", "min_abs_amount": Decimal("2"), "max_abs_amount": Decimal("1")},
            {"min_amount": Decimal("2"), "max_amount": Decimal("1")},
            {"min_amount": Decimal("NaN")}, {"max_amount": Decimal("Infinity")},
            {"min_amount": Decimal("0.001")}, {"limit": 0}, {"limit": 1001}, {"offset": -1},
        ]
        for query in invalid:
            with self.subTest(query=query), self.assertRaises(ValueError):
                await service.get_transactions(self.db, **query)

    async def test_create_missing_card_and_no_ingestion_or_deduplication(self):
        with self.assertRaisesRegex(ValueError, "card_id"):
            await service.create_transaction(self.db, TransactionCreate(**{**BASE_INPUT, "card_id": 9999}))
        data = TransactionCreate(**BASE_INPUT)
        first = await service.create_transaction(self.db, data)
        second = await service.create_transaction(self.db, data)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.amount, Decimal("-12.34"))
        self.assertEqual(first.card.account.name, "Family")
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(SourcePayload)), 0)
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(TransactionSourceLink)), 0)

    async def test_update_preserves_omitted_legacy_fx_dates_and_fee(self):
        precise = datetime(2026, 2, 16, 12, 34, 56, 123456)
        old = await self.record(
            original_currency="USD", original_amount=None, fx_rate=Decimal("0"),
            fx_fee=Decimal("2.34"), transaction_datetime=precise, location="Somewhere",
        )
        self.db.expunge_all()
        self.statements.clear()
        updated = await service.update_transaction(self.db, old.id, TransactionUpdate(description="  Edited  "))
        self.assertEqual(updated.description, "Edited")
        self.assertIsNone(updated.original_amount)
        self.assertEqual(updated.original_currency, "USD")
        self.assertEqual(updated.fx_rate, Decimal("0"))
        self.assertEqual(updated.fx_fee, Decimal("2.34"))
        self.assertEqual(updated.transaction_datetime, precise)
        updates = [sql for sql in self.statements if sql.startswith("UPDATE transactions")]
        self.assertEqual(len(updates), 1)
        self.assertNotIn("transaction_datetime=", updates[0])
        self.assertNotIn("fx_fee=", updates[0])
        with self.assertRaisesRegex(ValueError, "original_amount"):
            await service.update_transaction(self.db, old.id, TransactionUpdate(amount="20"))
        self.assertEqual(updated.amount, Decimal("-12.34"))
        await service.update_transaction(self.db, old.id, TransactionUpdate(location=None, transaction_datetime=None))
        self.assertIsNone(updated.location)
        self.assertIsNone(updated.transaction_datetime)

    async def test_update_merged_fx_and_explicit_pair_clear(self):
        saved = await self.record(original_amount=Decimal("-5"), original_currency="USD", fx_rate=Decimal("2"), fx_fee=Decimal("1.50"))
        updated = await service.update_transaction(self.db, saved.id, TransactionUpdate(original_amount="-6"))
        self.assertEqual(updated.original_amount, Decimal("-6"))
        self.assertEqual(updated.original_currency, "USD")
        with self.assertRaisesRegex(ValueError, "original_currency"):
            await service.update_transaction(self.db, saved.id, TransactionUpdate(original_currency=None))
        updated = await service.update_transaction(self.db, saved.id, TransactionUpdate(original_amount=None, original_currency=None))
        self.assertIsNone(updated.original_amount)
        self.assertIsNone(updated.original_currency)
        self.assertIsNone(updated.fx_rate)
        self.assertEqual(updated.fx_fee, Decimal("1.50"))
        standalone = await self.record(fx_rate=Decimal("2"))
        updated = await service.update_transaction(self.db, standalone.id, TransactionUpdate(original_amount=None, original_currency=None))
        self.assertIsNone(updated.fx_rate)
        invalid_currency = await self.record(currency="123", original_amount=Decimal("1"), original_currency="USD")
        with self.assertRaisesRegex(ValueError, "currency"):
            await service.update_transaction(self.db, invalid_currency.id, TransactionUpdate(fx_rate="2"))
        self.assertIsNone(await service.update_transaction(self.db, 9999, TransactionUpdate(description="Missing")))

    async def test_observation_pages_counts_and_delete_preserve_payloads_and_other_links(self):
        transaction = await self.record()
        other = await self.record()
        with tempfile.TemporaryDirectory() as directory:
            attachment = Path(directory) / "synthetic.txt"
            attachment.write_text("Synthetic attachment", encoding="utf-8")
            payloads = [SourcePayload(
                source_kind="other", media_type="text/plain", ingestion_method="migration",
                content_hash=f"{index:064x}", raw_text=f"Source {index}",
                created_at=datetime(2026, 1, 1), file_path=str(attachment) if index == 0 else None,
            ) for index in range(23)]
            other_payload = SourcePayload(
                source_kind="other", media_type="text/plain", ingestion_method="migration",
                content_hash="f" * 64, raw_text="Other source", created_at=datetime(2026, 1, 1),
            )
            self.db.add_all([*payloads, other_payload])
            await self.db.flush()
            observations = [TransactionObservation(
                source_payload_id=payload.id, source_item_key="0", raw_fragment=payload.raw_text,
            ) for payload in payloads]
            other_observation = TransactionObservation(
                source_payload_id=other_payload.id, source_item_key="0", raw_fragment="Other source",
            )
            self.db.add_all([*observations, other_observation])
            await self.db.flush()
            self.db.add_all([TransactionSourceLink(
                transaction_id=transaction.id, observation_id=observation.id, match_method="manual",
            ) for observation in observations])
            self.db.add(TransactionSourceLink(
                transaction_id=other.id, observation_id=other_observation.id, match_method="manual",
            ))
            await self.db.commit()
            self.db.expunge_all()
            self.statements.clear()
            counts = await service.get_source_counts(self.db, [transaction.id, other.id, 9999])
            self.assertEqual(counts, {transaction.id: 23, other.id: 1, 9999: 0})
            self.assertEqual(len(self.statements), 1)
            page, total = await service.get_transaction_observations_page(self.db, transaction.id)
            self.assertEqual(total, 23)
            self.assertEqual([link.observation_id for link in page], [value.id for value in reversed(observations)][0:20])
            self.assertEqual(page[0].observation.payload.raw_text, "Source 22")
            page, total = await service.get_transaction_observations_page(self.db, transaction.id, offset=20)
            self.assertEqual(len(page), 3)
            self.assertTrue(await service.delete_transaction(self.db, transaction.id))
            self.assertFalse(await service.delete_transaction(self.db, transaction.id))
            self.assertEqual(await self.db.scalar(select(func.count()).select_from(SourcePayload)), 24)
            self.assertEqual(await self.db.scalar(select(func.count()).select_from(TransactionObservation)), 24)
            self.assertEqual(await service.get_source_counts(self.db, [other.id]), {other.id: 1})
            self.assertEqual(await self.db.scalar(select(func.count()).select_from(Account)), 2)
            self.assertEqual(await self.db.scalar(select(func.count()).select_from(Card)), 2)
            self.assertTrue(attachment.is_file())

    async def test_all_reference_options_are_reachable_across_batches(self):
        self.db.add_all([Card(
            account_id=self.accounts[0].id, name=f"Synthetic {index}",
            card_masked_number=f"**** {index + 3000}", card_type="debit",
        ) for index in range(service.REFERENCE_BATCH_SIZE + 1)])
        await self.record(currency="EUR", original_currency="GBP")
        references = await service.get_transaction_references(self.db)
        self.assertEqual(len(references["cards"]), service.REFERENCE_BATCH_SIZE + 3)
        self.assertEqual(references["currencies"], ["AED", "EUR", "GBP", "USD"])
        self.assertEqual(references["accounts"][0]["label"], "Synthetic bank · Family")
        self.assertEqual(references["cards"][0]["currency"], "AED")
        self.assertEqual(references["cards"][0]["label"], "Everyday · **** 1111")

    async def test_api_auth_validation_filters_and_source_pagination(self):
        active = User(username="synthetic-active", email="active@example.test", hashed_password="unused", is_active=True)
        inactive = User(username="synthetic-inactive", email="inactive@example.test", hashed_password="unused", is_active=False)
        self.db.add_all([active, inactive])
        await self.db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        async def isolated_db():
            async with self.sessions() as session:
                yield session

        app.dependency_overrides[get_db] = isolated_db
        token = create_access_token({"sub": str(active.id)})
        inactive_token = create_access_token({"sub": str(inactive.id)})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            self.assertEqual((await client.get("/api/v1/transactions")).status_code, 401)
            self.assertEqual((await client.post("/api/v1/transactions", json=BASE_INPUT)).status_code, 401)
            self.assertEqual((await client.get("/api/v1/transactions", headers={"Authorization": f"Bearer {inactive_token}"})).status_code, 400)
            client.headers["Authorization"] = f"Bearer {token}"
            response = await client.post("/api/v1/transactions", json={**BASE_INPUT, "card_id": 9999})
            self.assertEqual(response.status_code, 422)
            self.assertIn("card_id", response.json()["detail"])
            for identifier in (2**31, 999999999999999999999999):
                response = await client.post("/api/v1/transactions", json={**BASE_INPUT, "card_id": identifier})
                self.assertEqual(response.status_code, 422)
                for field in ("account_id", "card_id"):
                    response = await client.get("/api/v1/transactions", params={field: str(identifier)})
                    self.assertEqual(response.status_code, 422)
                    self.assertIn(field, response.json()["detail"])
                for suffix in ("", "/observations"):
                    response = await client.get(f"/api/v1/transactions/{identifier}{suffix}")
                    self.assertEqual(response.status_code, 404)
                response = await client.patch(f"/api/v1/transactions/{identifier}", json={"description": "Missing"})
                self.assertEqual(response.status_code, 404)
                response = await client.delete(f"/api/v1/transactions/{identifier}")
                self.assertEqual(response.status_code, 404)
            response = await client.post("/api/v1/transactions", json={**BASE_INPUT, "original_currency": "USD"})
            self.assertEqual(response.status_code, 422)
            response = await client.post("/api/v1/transactions", json=BASE_INPUT)
            self.assertEqual(response.status_code, 201, response.text)
            transaction_id = response.json()["id"]
            for patch in ({"card_id": self.cards[1].id}, {"amount": None}, {"original_currency": "USD"}):
                response = await client.patch(f"/api/v1/transactions/{transaction_id}", json=patch)
                self.assertEqual(response.status_code, 422, response.text)
            response = await client.get("/api/v1/transactions", params={"min_abs_amount": "1"})
            self.assertEqual(response.status_code, 422)
            response = await client.get("/api/v1/transactions", params={"currency": "AED", "direction": "out", "min_abs_amount": "12.34", "max_abs_amount": "12.34"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["total"], 1)
            self.assertEqual((await client.get(f"/api/v1/transactions/{transaction_id}/observations?limit=1&offset=1")).json(), [])
            self.assertEqual((await client.get(f"/api/v1/transactions/{transaction_id}/observations?limit=1001")).status_code, 422)
            self.assertEqual((await client.get("/api/v1/transactions/9999/observations")).status_code, 404)
            self.assertEqual((await client.delete(f"/api/v1/transactions/{transaction_id}")).status_code, 204)
            self.assertEqual((await client.get(f"/api/v1/transactions/{transaction_id}")).status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
