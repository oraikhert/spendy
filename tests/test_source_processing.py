"""Isolated source payload, observation, API, and canonicalization regressions."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

_upload_dir = tempfile.mkdtemp(prefix="spendy-source-uploads-")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["DEBUG"] = "false"
os.environ["SECRET_KEY"] = "synthetic-source-processing-test-secret"
os.environ["UPLOAD_DIR"] = _upload_dir
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from fastapi import FastAPI, HTTPException
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.source_payloads import router as payload_router
from app.api.v1.transaction_observations import router as observation_router
from app.api.v1.transactions import router as transaction_router
from app.core.security import create_access_token
from app.database import Base, get_db
from app.models import (
    Account,
    Card,
    SourcePayload,
    Transaction,
    TransactionObservation,
    TransactionSourceLink,
    User,
)
from app.models.source_payload import ProcessingStatus, SourceKind
from app.services import source_processing_service as service
from app.services.source_parsers import (
    PARSER_REGISTRY,
    ObservationInput,
    ParserResult,
    RegisteredParser,
)
from app.utils.canonicalization import canonicalize_transaction
from app.utils.matching import normalize_merchant


SMS = (
    "Purchase of AED 12.34 with Credit Card ending 1111 at SYNTHETIC SHOP, DUBAI. "
    "Avl Cr. Limit is AED 100.00"
)


class SourceProcessingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(self.engine.sync_engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as db:
            account = Account(
                institution="Synthetic bank", name="Main", account_currency="AED"
            )
            db.add(account)
            await db.flush()
            card = Card(
                account_id=account.id,
                card_masked_number="**** 1111",
                card_type="credit",
                name="Main card",
            )
            user = User(
                username="source-user",
                email="source@example.test",
                hashed_password="unused",
                is_active=True,
            )
            db.add_all([card, user])
            await db.commit()
            self.account_id = account.id
            self.card_id = card.id
            self.user_id = user.id

        app = FastAPI()
        app.include_router(payload_router, prefix="/api/v1")
        app.include_router(observation_router, prefix="/api/v1")
        app.include_router(transaction_router, prefix="/api/v1")

        async def isolated_db():
            async with self.sessions() as session:
                yield session

        app.dependency_overrides[get_db] = isolated_db
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )
        self.client.headers["Authorization"] = (
            f"Bearer {create_access_token({'sub': str(self.user_id)})}"
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()

    async def test_text_ingestion_idempotency_and_private_storage_fields(self):
        body = {
            "source_kind": "sms",
            "text": SMS,
            "transaction_datetime": "2026-08-01T10:30:00+04:00",
            "account_id": self.account_id,
        }
        created = await self.client.post(
            "/api/v1/source-payloads/text",
            json=body,
            headers={"Idempotency-Key": "phone-delivery-1"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        payload = created.json()
        self.assertEqual(payload["processing_status"], "processed")
        self.assertEqual(len(payload["observations"]), 1)
        self.assertNotIn("file_path", payload)
        self.assertNotIn("download_url", payload)
        observation_id = payload["observations"][0]["id"]

        replay = await self.client.post(
            "/api/v1/source-payloads/text",
            json=body,
            headers={"Idempotency-Key": "phone-delivery-1"},
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["id"], payload["id"])

        conflict = await self.client.post(
            "/api/v1/source-payloads/text",
            json={**body, "text": SMS.replace("12.34", "13.34")},
            headers={"Idempotency-Key": "phone-delivery-1"},
        )
        self.assertEqual(conflict.status_code, 409)

        duplicate = await self.client.post("/api/v1/source-payloads/text", json=body)
        self.assertEqual(duplicate.status_code, 201, duplicate.text)
        self.assertNotEqual(duplicate.json()["id"], payload["id"])

        payload_list = await self.client.get(
            "/api/v1/source-payloads?has_observations=true"
        )
        self.assertEqual(payload_list.status_code, 200, payload_list.text)
        self.assertEqual(payload_list.json()["total"], 2)
        observation_list = await self.client.get(
            "/api/v1/transaction-observations?has_transaction=true"
        )
        self.assertEqual(observation_list.status_code, 200, observation_list.text)
        self.assertEqual(observation_list.json()["total"], 2)
        detail = await self.client.get(
            f"/api/v1/transaction-observations/{observation_id}"
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["transaction_link"]["match_method"], "automatic")

    async def test_auth_validation_and_missing_objects(self):
        authorization = self.client.headers.pop("Authorization")
        try:
            unauthenticated = await self.client.get("/api/v1/source-payloads")
        finally:
            self.client.headers["Authorization"] = authorization
        self.assertEqual(unauthenticated.status_code, 401, unauthenticated.text)

        invalid_context = await self.client.post(
            "/api/v1/source-payloads/text",
            json={"source_kind": "sms", "text": SMS, "account_id": 999999},
        )
        self.assertEqual(invalid_context.status_code, 422, invalid_context.text)
        self.assertEqual(
            (await self.client.get("/api/v1/source-payloads/999999")).status_code,
            404,
        )
        self.assertEqual(
            (
                await self.client.get(
                    "/api/v1/transaction-observations/999999"
                )
            ).status_code,
            404,
        )

    async def test_ambiguous_same_day_match_stays_unlinked(self):
        observed_at = datetime(2026, 8, 1, 10, 30, tzinfo=UTC)
        async with self.sessions() as db:
            db.add_all(
                [
                    Transaction(
                        card_id=self.card_id,
                        amount=Decimal("-12.34"),
                        currency="AED",
                        transaction_datetime=observed_at,
                        description="SYNTHETIC SHOP",
                        transaction_kind="purchase",
                        merchant_norm=normalize_merchant("SYNTHETIC SHOP"),
                    )
                    for _ in range(2)
                ]
            )
            await db.commit()

        created = await self.client.post(
            "/api/v1/source-payloads/text",
            json={
                "source_kind": "sms",
                "text": SMS,
                "transaction_datetime": observed_at.isoformat(),
                "card_id": self.card_id,
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        observation_id = created.json()["observations"][0]["id"]
        detail = await self.client.get(
            f"/api/v1/transaction-observations/{observation_id}"
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertIsNone(detail.json()["transaction_link"])
        self.assertEqual(
            detail.json()["extraction_metadata"],
            {"matching_status": "ambiguous", "candidate_count": 2},
        )

    async def test_adjacent_calendar_day_does_not_match(self):
        prior_date = datetime(2026, 8, 1, 10, 30, tzinfo=UTC)
        observed_at = prior_date + timedelta(days=1)
        async with self.sessions() as db:
            existing = Transaction(
                card_id=self.card_id,
                amount=Decimal("-12.34"),
                currency="AED",
                transaction_datetime=prior_date,
                description="SYNTHETIC SHOP",
                transaction_kind="purchase",
                merchant_norm=normalize_merchant("SYNTHETIC SHOP"),
            )
            db.add(existing)
            await db.commit()
            existing_id = existing.id

        created = await self.client.post(
            "/api/v1/source-payloads/text",
            json={
                "source_kind": "sms",
                "text": SMS,
                "transaction_datetime": observed_at.isoformat(),
                "card_id": self.card_id,
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        observation_id = created.json()["observations"][0]["id"]
        async with self.sessions() as db:
            linked_transaction_id = await db.scalar(
                select(TransactionSourceLink.transaction_id).where(
                    TransactionSourceLink.observation_id == observation_id
                )
            )
            self.assertNotEqual(linked_transaction_id, existing_id)
            self.assertEqual(
                await db.scalar(select(func.count()).select_from(Transaction)),
                2,
            )

    async def test_ignored_failed_and_upload_pending(self):
        ignored = await self.client.post(
            "/api/v1/source-payloads/text",
            json={"source_kind": "sms", "text": "Upcoming payment reminder"},
        )
        self.assertEqual(ignored.status_code, 201)
        self.assertEqual(ignored.json()["processing_status"], "ignored")
        self.assertEqual(ignored.json()["observations"], [])

        failed = await self.client.post(
            "/api/v1/source-payloads/text",
            json={"source_kind": "sms", "text": "Unrecognized synthetic message"},
        )
        self.assertEqual(failed.status_code, 201)
        self.assertEqual(failed.json()["processing_status"], "failed")
        self.assertEqual(failed.json()["observations"], [])

        files_before = set(Path(_upload_dir).iterdir())
        upload = await self.client.post(
            "/api/v1/source-payloads/upload",
            data={
                "source_kind": "bank_statement",
                "account_id": str(self.account_id),
                "card_id": str(self.card_id),
            },
            files={"file": ("statement.pdf", b"synthetic-pdf", "application/pdf")},
            headers={"Idempotency-Key": "statement-upload-1"},
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        uploaded = upload.json()
        files_after_create = set(Path(_upload_dir).iterdir())
        self.assertEqual(len(files_after_create - files_before), 1)
        self.assertEqual(uploaded["processing_status"], "pending")
        self.assertTrue(uploaded["has_file"])
        self.assertEqual(uploaded["bank_statement_details"]["card_id"], self.card_id)
        self.assertNotIn("file_path", uploaded)

        replay = await self.client.post(
            "/api/v1/source-payloads/upload",
            data={
                "source_kind": "bank_statement",
                "account_id": str(self.account_id),
                "card_id": str(self.card_id),
            },
            files={"file": ("statement.pdf", b"synthetic-pdf", "application/pdf")},
            headers={"Idempotency-Key": "statement-upload-1"},
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["id"], uploaded["id"])
        self.assertEqual(set(Path(_upload_dir).iterdir()), files_after_create)

        conflict = await self.client.post(
            "/api/v1/source-payloads/upload",
            data={"source_kind": "bank_statement"},
            files={"file": ("statement.pdf", b"different-pdf", "application/pdf")},
            headers={"Idempotency-Key": "statement-upload-1"},
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(set(Path(_upload_dir).iterdir()), files_after_create)

        metadata_conflict = await self.client.post(
            "/api/v1/source-payloads/upload",
            data={"source_kind": "other"},
            files={"file": ("statement.pdf", b"synthetic-pdf", "application/pdf")},
            headers={"Idempotency-Key": "statement-upload-1"},
        )
        self.assertEqual(metadata_conflict.status_code, 409, metadata_conflict.text)
        self.assertEqual(set(Path(_upload_dir).iterdir()), files_after_create)

        duplicate = await self.client.post(
            "/api/v1/source-payloads/upload",
            data={
                "source_kind": "bank_statement",
                "account_id": str(self.account_id),
                "card_id": str(self.card_id),
            },
            files={"file": ("statement.pdf", b"synthetic-pdf", "application/pdf")},
        )
        self.assertEqual(duplicate.status_code, 201, duplicate.text)
        self.assertNotEqual(duplicate.json()["id"], uploaded["id"])
        self.assertEqual(len(set(Path(_upload_dir).iterdir()) - files_before), 2)

        files_before_empty = set(Path(_upload_dir).iterdir())
        empty = await self.client.post(
            "/api/v1/source-payloads/upload",
            data={"source_kind": "other"},
            files={"file": ("empty.bin", b"", "application/octet-stream")},
        )
        self.assertEqual(empty.status_code, 422, empty.text)
        self.assertEqual(set(Path(_upload_dir).iterdir()), files_before_empty)

        blank_key = await self.client.post(
            "/api/v1/source-payloads/text",
            json={"source_kind": "sms", "text": SMS},
            headers={"Idempotency-Key": "   "},
        )
        self.assertEqual(blank_key.status_code, 422, blank_key.text)
        self.assertEqual(
            (
                await self.client.post(
                    f"/api/v1/source-payloads/{uploaded['id']}/reprocess"
                )
            ).status_code,
            409,
        )
        for path in (
            f"/api/v1/source-payloads/{uploaded['id']}/download",
            f"/api/v1/source-events/{uploaded['id']}/download",
            f"/transactions/sources/{uploaded['id']}/download",
        ):
            self.assertEqual((await self.client.get(path)).status_code, 404)

    async def test_reprocess_replaces_observations_and_preserves_orphan(self):
        created = await self.client.post(
            "/api/v1/source-payloads/text",
            json={"source_kind": "sms", "text": SMS, "card_id": self.card_id},
        )
        payload_id = created.json()["id"]
        observation_id = created.json()["observations"][0]["id"]
        async with self.sessions() as db:
            transaction_id = await db.scalar(
                select(TransactionSourceLink.transaction_id).where(
                    TransactionSourceLink.observation_id == observation_id
                )
            )

        failed_parser = RegisteredParser(
            name="sms_regex",
            version="2-test",
            parse=lambda _payload: ParserResult(
                status=ProcessingStatus.FAILED, error="Synthetic parser failure"
            ),
        )
        with patch.dict(
            PARSER_REGISTRY,
            {(SourceKind.SMS.value, "text/plain"): failed_parser},
        ):
            reprocessed = await self.client.post(
                f"/api/v1/source-payloads/{payload_id}/reprocess"
            )
        self.assertEqual(reprocessed.status_code, 200, reprocessed.text)
        self.assertEqual(reprocessed.json()["processing_status"], "failed")
        self.assertEqual(reprocessed.json()["observations"], [])
        async with self.sessions() as db:
            self.assertIsNotNone(await db.get(Transaction, transaction_id))
            self.assertIsNone(await db.get(TransactionObservation, observation_id))
            self.assertEqual(
                await db.scalar(select(func.count()).select_from(TransactionSourceLink)), 0
            )

    async def test_reprocess_system_error_rolls_back_old_observation_and_link(self):
        created = await self.client.post(
            "/api/v1/source-payloads/text",
            json={"source_kind": "sms", "text": SMS, "card_id": self.card_id},
        )
        payload_id = created.json()["id"]
        observation_id = created.json()["observations"][0]["id"]

        def raise_system_error(_payload):
            raise RuntimeError("Synthetic system failure")

        parser = RegisteredParser(
            name="broken_system_parser",
            version="1-test",
            parse=raise_system_error,
        )
        with patch.dict(
            PARSER_REGISTRY,
            {(SourceKind.SMS.value, "text/plain"): parser},
        ):
            with self.assertRaisesRegex(RuntimeError, "Synthetic system failure"):
                await self.client.post(
                    f"/api/v1/source-payloads/{payload_id}/reprocess"
                )

        async with self.sessions() as db:
            payload = await db.get(SourcePayload, payload_id)
            self.assertEqual(payload.processing_status, "processed")
            self.assertIsNotNone(await db.get(TransactionObservation, observation_id))
            self.assertIsNotNone(await db.get(TransactionSourceLink, observation_id))

    async def test_fx_failure_is_recorded_without_a_link(self):
        foreign_sms = SMS.replace("AED 12.34", "USD 12.34")
        with patch.object(
            service.exchange_rate_service,
            "get_rate",
            side_effect=HTTPException(status_code=502, detail="Synthetic FX failure"),
        ):
            created = await self.client.post(
                "/api/v1/source-payloads/text",
                json={
                    "source_kind": "sms",
                    "text": foreign_sms,
                    "card_id": self.card_id,
                },
            )
        self.assertEqual(created.status_code, 201, created.text)
        payload = created.json()
        self.assertEqual(payload["processing_status"], "failed")
        self.assertIn("Synthetic FX failure", payload["processing_error"])
        observation_id = payload["observations"][0]["id"]
        detail = await self.client.get(
            f"/api/v1/transaction-observations/{observation_id}"
        )
        self.assertIsNone(detail.json()["transaction_link"])
        self.assertEqual(
            detail.json()["extraction_metadata"]["matching_error"],
            "exchange_rate_unavailable",
        )

    async def test_successful_reprocess_replaces_observation_ids_and_links(self):
        created = await self.client.post(
            "/api/v1/source-payloads/text",
            json={"source_kind": "sms", "text": SMS, "card_id": self.card_id},
        )
        self.assertEqual(created.status_code, 201, created.text)
        payload_id = created.json()["id"]
        old_observation_id = created.json()["observations"][0]["id"]
        async with self.sessions() as db:
            old_transaction_id = await db.scalar(
                select(TransactionSourceLink.transaction_id).where(
                    TransactionSourceLink.observation_id == old_observation_id
                )
            )

        parser = RegisteredParser(
            name="synthetic_multi",
            version="1-test",
            parse=lambda _payload: ParserResult(
                status=ProcessingStatus.PROCESSED,
                observations=(
                    ObservationInput(
                        source_item_key="purchase",
                        amount=Decimal("-12.34"),
                        currency="AED",
                        card_id=self.card_id,
                        description="SYNTHETIC SHOP",
                        transaction_kind="purchase",
                    ),
                    ObservationInput(
                        source_item_key="fee",
                        amount=Decimal("-1.00"),
                        currency="AED",
                        description="Synthetic fee",
                    ),
                ),
            ),
        )
        with patch.dict(
            PARSER_REGISTRY,
            {(SourceKind.SMS.value, "text/plain"): parser},
        ):
            response = await self.client.post(
                f"/api/v1/source-payloads/{payload_id}/reprocess"
            )

        self.assertEqual(response.status_code, 200, response.text)
        observation_ids = {item["id"] for item in response.json()["observations"]}
        self.assertEqual(len(observation_ids), 2)
        self.assertNotIn(old_observation_id, observation_ids)
        async with self.sessions() as db:
            self.assertIsNone(await db.get(TransactionObservation, old_observation_id))
            self.assertIsNotNone(await db.get(Transaction, old_transaction_id))
            linked_ids = set(await db.scalars(select(TransactionSourceLink.observation_id)))
            self.assertTrue(linked_ids)
            self.assertTrue(linked_ids <= observation_ids)

    async def test_manual_link_list_and_unlink_api(self):
        async with self.sessions() as db:
            transaction = Transaction(
                card_id=self.card_id,
                amount=Decimal("-1.00"),
                currency="AED",
                description="Manual value",
                transaction_kind="other",
            )
            payload = SourcePayload(
                source_kind="bank_statement",
                media_type="application/pdf",
                ingestion_method="manual_upload",
                file_path="/private/not-readable-through-api",
                original_filename="statement.pdf",
                content_hash="c" * 64,
                processing_status="processed",
            )
            sms_payload = SourcePayload(
                source_kind="sms",
                media_type="text/plain",
                ingestion_method="phone_api",
                raw_text="Synthetic SMS evidence",
                content_hash="d" * 64,
                processing_status="processed",
            )
            db.add_all([transaction, payload, sms_payload])
            await db.flush()
            observation = TransactionObservation(
                source_payload_id=payload.id,
                source_item_key="line-1",
                amount=Decimal("-99.00"),
                currency="AED",
                description="Statement value",
                transaction_kind="purchase",
                card_id=self.card_id,
            )
            sms_observation = TransactionObservation(
                source_payload_id=sms_payload.id,
                source_item_key="0",
                amount=Decimal("-10.00"),
                currency="AED",
                description="SMS value",
                transaction_kind="purchase",
                card_id=self.card_id,
            )
            db.add_all([observation, sms_observation])
            await db.flush()
            db.add(
                TransactionSourceLink(
                    observation_id=sms_observation.id,
                    transaction_id=transaction.id,
                    match_method="manual",
                )
            )
            await db.flush()
            await canonicalize_transaction(db, transaction)
            await db.commit()
            transaction_id = transaction.id
            observation_id = observation.id
            sms_observation_id = sms_observation.id

        linked = await self.client.post(
            f"/api/v1/transaction-observations/{observation_id}/link",
            json={"transaction_id": transaction_id},
        )
        self.assertEqual(linked.status_code, 201, linked.text)
        self.assertEqual(linked.json()["match_method"], "manual")
        self.assertNotIn("file_path", str(linked.json()))

        duplicate = await self.client.post(
            f"/api/v1/transaction-observations/{observation_id}/link",
            json={"transaction_id": transaction_id},
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

        links = await self.client.get(
            f"/api/v1/transactions/{transaction_id}/observations"
        )
        self.assertEqual(links.status_code, 200, links.text)
        self.assertEqual(
            {value["observation_id"] for value in links.json()},
            {observation_id, sms_observation_id},
        )
        async with self.sessions() as db:
            refreshed = await db.get(Transaction, transaction_id)
            self.assertEqual(refreshed.amount, Decimal("-99.00"))
            self.assertEqual(refreshed.description, "Statement value")

        unlinked = await self.client.delete(
            f"/api/v1/transaction-observations/{observation_id}/link"
        )
        self.assertEqual(unlinked.status_code, 204, unlinked.text)
        async with self.sessions() as db:
            refreshed = await db.get(Transaction, transaction_id)
            self.assertEqual(refreshed.amount, Decimal("-10.00"))
            self.assertEqual(refreshed.description, "SMS value")
        missing = await self.client.delete(
            f"/api/v1/transaction-observations/{observation_id}/link"
        )
        self.assertEqual(missing.status_code, 404, missing.text)

    async def test_create_transaction_from_observation_api(self):
        async with self.sessions() as db:
            payload = SourcePayload(
                source_kind="other",
                media_type="text/plain",
                ingestion_method="migration",
                raw_text="Synthetic unlinked evidence",
                content_hash="e" * 64,
                processing_status="processed",
            )
            db.add(payload)
            await db.flush()
            observation = TransactionObservation(
                source_payload_id=payload.id,
                source_item_key="manual-row",
                description="Observation merchant",
            )
            db.add(observation)
            await db.commit()
            observation_id = observation.id

        invalid = await self.client.post(
            f"/api/v1/transaction-observations/{observation_id}/transaction",
            json={},
        )
        self.assertEqual(invalid.status_code, 422, invalid.text)

        created = await self.client.post(
            f"/api/v1/transaction-observations/{observation_id}/transaction",
            json={
                "card_id": self.card_id,
                "amount": "-4.25",
                "currency": "aed",
                "transaction_kind": "purchase",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["amount"], "-4.25")
        self.assertEqual(created.json()["currency"], "AED")
        self.assertEqual(created.json()["description"], "Observation merchant")
        async with self.sessions() as db:
            link = await db.get(TransactionSourceLink, observation_id)
            self.assertEqual(link.transaction_id, created.json()["id"])

        conflict = await self.client.post(
            f"/api/v1/transaction-observations/{observation_id}/transaction",
            json={
                "card_id": self.card_id,
                "amount": "-4.25",
                "currency": "AED",
            },
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)

    async def test_one_final_link_and_field_priority_canonicalization(self):
        async with self.sessions() as db:
            transaction = Transaction(
                card_id=self.card_id,
                amount=Decimal("-1"),
                currency="AED",
                description="Manual",
                transaction_kind="other",
            )
            sms_payload = SourcePayload(
                source_kind="sms",
                media_type="text/plain",
                ingestion_method="phone_api",
                raw_text="Synthetic",
                content_hash="a" * 64,
                processing_status="processed",
            )
            statement_payload = SourcePayload(
                source_kind="bank_statement",
                media_type="application/pdf",
                ingestion_method="manual_upload",
                file_path="/private/synthetic",
                original_filename="statement.pdf",
                content_hash="b" * 64,
                processing_status="processed",
                received_at=datetime.now(UTC) + timedelta(seconds=1),
            )
            db.add_all([transaction, sms_payload, statement_payload])
            await db.flush()
            sms = TransactionObservation(
                source_payload_id=sms_payload.id,
                source_item_key="0",
                amount=Decimal("-10"),
                currency="AED",
                transaction_datetime=datetime(2026, 8, 1, 10, tzinfo=UTC),
                description="SMS merchant",
                transaction_kind="purchase",
                location="SMS location",
            )
            statement = TransactionObservation(
                source_payload_id=statement_payload.id,
                source_item_key="row-1",
                amount=Decimal("-11"),
                currency="AED",
                posting_datetime=datetime(2026, 8, 2, tzinfo=UTC),
                description="Statement merchant",
                transaction_kind="other",
            )
            db.add_all([sms, statement])
            await db.flush()
            db.add_all(
                [
                    TransactionSourceLink(
                        observation_id=sms.id,
                        transaction_id=transaction.id,
                        match_method="manual",
                    ),
                    TransactionSourceLink(
                        observation_id=statement.id,
                        transaction_id=transaction.id,
                        match_method="manual",
                    ),
                ]
            )
            await db.flush()
            await canonicalize_transaction(db, transaction)
            self.assertEqual(transaction.amount, Decimal("-11"))
            self.assertEqual(transaction.description, "Statement merchant")
            self.assertEqual(transaction.transaction_datetime, sms.transaction_datetime)
            self.assertEqual(transaction.location, "SMS location")
            self.assertEqual(transaction.transaction_kind, "purchase")

            other = Transaction(
                card_id=self.card_id,
                amount=Decimal("-1"),
                currency="AED",
                description="Other",
                transaction_kind="other",
            )
            db.add(other)
            await db.flush()
            db.add(
                TransactionSourceLink(
                    observation_id=sms.id,
                    transaction_id=other.id,
                    match_method="manual",
                )
            )
            with self.assertRaises(IntegrityError):
                await db.flush()
            await db.rollback()


if __name__ == "__main__":
    unittest.main(verbosity=2)
