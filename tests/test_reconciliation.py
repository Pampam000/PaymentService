import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import delete, select

from payment_service.adapters.base import ProviderError
from payment_service.core.db import database_available, session_factory
from payment_service.models.operations import OutboxEvent, Payment
from payment_service.repositories.payments import claim_reconciliation, finish_reconciliation, get_payment
from payment_service.schemas.payment import ProviderPaymentResult, ProviderPaymentStatus
from payment_service.services.reconciliation import reconcile_payment


class ReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payment_id = uuid4()
        self.payment = {
            "id": self.payment_id, "order_id": uuid4(), "amount_kopecks": 101,
            "plan_id": "basic", "period": "month", "status": "pending", "resolution_status": "unknown",
            "provider_payment_id": None,
            "provider_create_started_at": datetime.now(timezone.utc) - timedelta(minutes=2),
        }

    def test_lost_response_reuses_original_payment_id(self) -> None:
        create = AsyncMock(return_value=ProviderPaymentResult(
            provider_id="provider-1", confirmation_url="https://yookassa.ru/pay/1",
        ))
        with patch("payment_service.services.reconciliation.get_payment", new=AsyncMock(return_value=SimpleNamespace(**self.payment))), patch(
            "payment_service.services.reconciliation.claim_reconciliation", new=AsyncMock(return_value=SimpleNamespace(**self.payment))
        ), patch("payment_service.services.reconciliation.finish_reconciliation", new=AsyncMock()) as finish, patch(
            "payment_service.services.reconciliation.get_adapter", return_value=SimpleNamespace(create_payment=create)
        ):
            self.assertEqual(asyncio.run(reconcile_payment(self.payment_id)), "resolved")
        self.assertEqual(create.await_count, 1)
        self.assertEqual(create.await_args.args[0].id, self.payment_id)
        self.assertEqual(finish.await_args.args[1], "provider-1")

    def test_unavailable_provider_remains_unknown(self) -> None:
        create = AsyncMock(side_effect=ProviderError("unavailable"))
        with patch("payment_service.services.reconciliation.get_payment", new=AsyncMock(return_value=SimpleNamespace(**self.payment))), patch(
            "payment_service.services.reconciliation.claim_reconciliation", new=AsyncMock(return_value=SimpleNamespace(**self.payment))
        ), patch("payment_service.services.reconciliation.finish_reconciliation", new=AsyncMock()) as finish, patch(
            "payment_service.services.reconciliation.get_adapter", return_value=SimpleNamespace(create_payment=create)
        ):
            self.assertEqual(asyncio.run(reconcile_payment(self.payment_id)), "unknown")
        finish.assert_not_awaited()

    def test_expired_key_requires_manual_review(self) -> None:
        self.payment["provider_create_started_at"] -= timedelta(hours=25)
        with patch("payment_service.services.reconciliation.get_payment", new=AsyncMock(return_value=SimpleNamespace(**self.payment))), patch(
            "payment_service.services.reconciliation.claim_reconciliation", new=AsyncMock()
        ) as claim:
            self.assertEqual(asyncio.run(reconcile_payment(self.payment_id)), "manual_review")
        claim.assert_not_awaited()

    def test_known_provider_id_is_checked_without_creating_payment(self) -> None:
        self.payment["provider_payment_id"] = "provider-1"
        self.payment["provider_create_started_at"] -= timedelta(hours=25)
        create = AsyncMock()
        get = AsyncMock(return_value=ProviderPaymentStatus(
            provider_id="provider-1", status="pending", amount_kopecks=101,
            payment_id=self.payment_id,
        ))
        with patch("payment_service.services.reconciliation.get_payment", new=AsyncMock(return_value=SimpleNamespace(**self.payment))), patch(
            "payment_service.services.reconciliation.claim_reconciliation", new=AsyncMock(return_value=SimpleNamespace(**self.payment))
        ), patch("payment_service.services.reconciliation.finish_reconciliation", new=AsyncMock()) as finish, patch(
            "payment_service.services.reconciliation.get_adapter",
            return_value=SimpleNamespace(create_payment=create, get_payment=get),
        ):
            self.assertEqual(asyncio.run(reconcile_payment(self.payment_id)), "resolved")
        create.assert_not_awaited()
        finish.assert_awaited_once()

    def test_pending_known_payment_is_reconciled_after_missing_webhook(self) -> None:
        self.payment.update(status="pending", resolution_status="known", provider_payment_id="provider-1")
        get = AsyncMock(return_value=ProviderPaymentStatus(
            provider_id="provider-1", status="succeeded", amount_kopecks=101,
            payment_id=self.payment_id,
        ))
        with patch("payment_service.services.reconciliation.get_payment", new=AsyncMock(return_value=SimpleNamespace(**self.payment))), patch(
            "payment_service.services.reconciliation.claim_reconciliation", new=AsyncMock(return_value=SimpleNamespace(**self.payment))
        ), patch("payment_service.services.reconciliation.finish_reconciliation", new=AsyncMock()) as finish, patch(
            "payment_service.services.reconciliation.get_adapter", return_value=SimpleNamespace(get_payment=get)
        ):
            self.assertEqual(asyncio.run(reconcile_payment(self.payment_id)), "resolved")
        self.assertEqual(finish.await_args.args[-1], "succeeded")

    def test_recent_terminal_mismatch_is_reported_without_mutation(self) -> None:
        self.payment.update(status="succeeded", resolution_status="known", provider_payment_id="provider-1")
        get = AsyncMock(return_value=ProviderPaymentStatus(
            provider_id="provider-1", status="canceled", amount_kopecks=101,
            payment_id=self.payment_id,
        ))
        with patch("payment_service.services.reconciliation.get_payment", new=AsyncMock(return_value=SimpleNamespace(**self.payment))), patch(
            "payment_service.services.reconciliation.finish_reconciliation", new=AsyncMock()
        ) as finish, patch("payment_service.services.reconciliation.get_adapter", return_value=SimpleNamespace(get_payment=get)):
            self.assertEqual(asyncio.run(reconcile_payment(self.payment_id)), "manual_review")
        finish.assert_not_awaited()

    def test_repository_claim_is_atomic_and_persisted(self) -> None:
        if not asyncio.run(database_available()):
            self.skipTest("Local PostgreSQL is unavailable")

        async def run() -> None:
            async with session_factory()() as session, session.begin():
                session.add(Payment(
                    id=self.payment_id, order_id=self.payment["order_id"],
                    amount_kopecks=101, currency="RUB", idempotency_key=str(uuid4()),
                    request_fingerprint="f" * 64, resolution_status="unknown",
                    provider_create_started_at=self.payment["provider_create_started_at"],
                ))
            try:
                claimed = await asyncio.gather(*[claim_reconciliation(self.payment_id) for _ in range(3)])
                self.assertEqual(sum(item is not None for item in claimed), 1)
                self.assertEqual((await get_payment(self.payment_id)).reconcile_attempts, 1)
                await finish_reconciliation(self.payment_id, "provider-1", "https://yookassa.ru/pay/1", "pending")
                self.assertEqual((await get_payment(self.payment_id)).resolution_status, "known")
                self.assertIsNone(await claim_reconciliation(self.payment_id))
            finally:
                async with session_factory()() as session, session.begin():
                    await session.execute(delete(Payment).where(Payment.id == self.payment_id))

        asyncio.run(run())

    def test_missing_webhook_is_recovered_with_outbox_event(self) -> None:
        if not asyncio.run(database_available()):
            self.skipTest("Local PostgreSQL is unavailable")

        async def run() -> None:
            async with session_factory()() as session, session.begin():
                session.add(Payment(
                    id=self.payment_id, order_id=self.payment["order_id"], amount_kopecks=101,
                    provider_payment_id="provider-" + str(self.payment_id),
                    idempotency_key=str(uuid4()), request_fingerprint="f" * 64,
                ))
            try:
                get = AsyncMock(return_value=ProviderPaymentStatus(
                    provider_id="provider-" + str(self.payment_id), status="succeeded",
                    amount_kopecks=101, payment_id=self.payment_id,
                ))
                with patch("payment_service.services.reconciliation.get_adapter", return_value=SimpleNamespace(get_payment=get)):
                    self.assertEqual(await reconcile_payment(self.payment_id), "resolved")
                self.assertEqual((await get_payment(self.payment_id)).status, "succeeded")
                async with session_factory()() as session:
                    events = (await session.scalars(select(OutboxEvent).where(
                        OutboxEvent.payload["payment_id"].as_string() == str(self.payment_id)
                    ))).all()
                    self.assertEqual(len(events), 1)
            finally:
                async with session_factory()() as session, session.begin():
                    await session.execute(delete(OutboxEvent).where(
                        OutboxEvent.payload["payment_id"].as_string() == str(self.payment_id)
                    ))
                    await session.execute(delete(Payment).where(Payment.id == self.payment_id))

        asyncio.run(run())
