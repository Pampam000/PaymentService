import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy import delete, select

from payment_service.core.db import database_available, session_factory
from payment_service.main import app
from payment_service.models.operations import OutboxEvent, Payment, Refund
from payment_service.adapters.base import ProviderError
from payment_service.schemas.payment import ProviderRefundStatus
from payment_service.services.refunds import reconcile_refund
from payment_service.services.webhooks import verify_notification
from payment_service.repositories.refunds import reserve_full_refund


class RefundReservationTests(unittest.TestCase):
    def test_existing_partial_refund_reduces_available_balance(self) -> None:
        if not asyncio.run(database_available()):
            self.skipTest("Local PostgreSQL is unavailable")

        async def run() -> None:
            payment = Payment(
                id=uuid4(), order_id=uuid4(), amount_kopecks=100, status="succeeded",
                idempotency_key=str(uuid4()), request_fingerprint="payment",
            )
            partial = Refund(
                id=uuid4(), payment_id=payment.id, amount_kopecks=40, status="succeeded",
                idempotency_key=str(uuid4()), request_fingerprint="partial",
            )
            async with session_factory()() as session, session.begin():
                session.add_all([payment, partial])
            try:
                refund, created, outcome = await reserve_full_refund(payment.id, str(uuid4()), None)
                self.assertIsNone(refund)
                self.assertFalse(created)
                self.assertEqual(outcome, "insufficient_balance")
            finally:
                async with session_factory()() as session, session.begin():
                    await session.execute(delete(Refund).where(Refund.payment_id == payment.id))
                    await session.execute(delete(Payment).where(Payment.id == payment.id))

        asyncio.run(run())

    def test_lost_response_is_reconciled_with_same_refund_id(self) -> None:
        if not asyncio.run(database_available()):
            self.skipTest("Local PostgreSQL is unavailable")

        payment = Payment(
            id=uuid4(), order_id=uuid4(), amount_kopecks=101, status="succeeded",
            provider_payment_id=str(uuid4()), idempotency_key=str(uuid4()), request_fingerprint="payment",
        )
        key = str(uuid4())
        create = AsyncMock(side_effect=ProviderError("lost response"))

        async def run() -> None:
            async with session_factory()() as session, session.begin():
                session.add(payment)
            try:
                transport = httpx.ASGITransport(app=app)
                headers = {"Authorization": "Bearer admin-test", "Idempotency-Key": key}
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                    first = await client.post(f"/payments/{payment.id}/refunds", json={}, headers=headers)
                    self.assertEqual(first.status_code, 202)
                    refund_id = first.json()["id"]
                    second = await client.post(f"/payments/{payment.id}/refunds", json={}, headers=headers)
                    self.assertEqual(second.status_code, 202)
                    self.assertEqual(second.json()["id"], refund_id)
                    self.assertEqual(create.await_count, 1)
                    found = await client.get(f"/refunds/{refund_id}", headers=headers)
                    self.assertEqual(found.status_code, 200)
                    self.assertEqual(found.json()["resolution_status"], "unknown")
                create.side_effect = lambda refund, provider_id: ProviderRefundStatus(
                    provider_id="provider-refund", provider_payment_id=provider_id,
                    status="pending", amount_kopecks=refund.amount_kopecks,
                )
                self.assertEqual(await reconcile_refund(UUID(refund_id)), "resolved")
                self.assertEqual(str(create.await_args.args[0].id), refund_id)
                self.assertEqual(await reconcile_refund(UUID(refund_id)), "rate_limited")
                async with session_factory()() as session:
                    row = await session.get(Refund, UUID(refund_id))
                    self.assertEqual(row.provider_refund_id, "provider-refund")
                    self.assertEqual(row.resolution_status, "known")
            finally:
                async with session_factory()() as session, session.begin():
                    await session.execute(delete(Refund).where(Refund.payment_id == payment.id))
                    await session.execute(delete(Payment).where(Payment.id == payment.id))

        with patch("payment_service.core.auth.settings") as settings, patch(
            "payment_service.services.refunds.get_adapter",
            return_value=SimpleNamespace(create_refund=create),
        ):
            settings.backend_token = SecretStr("backend-test")
            settings.admin_token = SecretStr("admin-test")
            asyncio.run(run())

    def test_confirmed_cancellation_releases_reservation(self) -> None:
        if not asyncio.run(database_available()):
            self.skipTest("Local PostgreSQL is unavailable")

        payment = Payment(
            id=uuid4(), order_id=uuid4(), amount_kopecks=101, status="succeeded",
            provider_payment_id=str(uuid4()), idempotency_key=str(uuid4()), request_fingerprint="payment",
        )
        created_ids = []
        create = AsyncMock(side_effect=lambda refund, payment_id: ProviderRefundStatus(
            provider_id=str(refund.id), provider_payment_id=payment_id,
            status="pending", amount_kopecks=refund.amount_kopecks,
        ))

        async def run() -> None:
            async with session_factory()() as session, session.begin():
                session.add(payment)
            try:
                transport = httpx.ASGITransport(app=app)
                admin = {"Authorization": "Bearer admin-test"}
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                    path = f"/payments/{payment.id}/refunds"
                    first = await client.post(path, json={}, headers={**admin, "Idempotency-Key": str(uuid4())})
                    self.assertEqual(first.status_code, 201)
                    first_id = first.json()["id"]
                    created_ids.append(first_id)
                    self.assertEqual(first.json()["status"], "pending")
                    self.assertEqual((await client.post(path, json={}, headers={**admin, "Idempotency-Key": str(uuid4())})).status_code, 409)

                    get = AsyncMock(return_value=ProviderRefundStatus(
                        provider_id=first_id, provider_payment_id=payment.provider_payment_id,
                        status="canceled", amount_kopecks=101,
                    ))
                    with patch("payment_service.services.refunds.get_adapter", return_value=SimpleNamespace(get_refund=get)):
                        self.assertEqual(await reconcile_refund(UUID(first_id)), "resolved")
                    self.assertEqual((await client.get(f"/refunds/{first_id}", headers=admin)).json()["status"], "canceled")
                    second = await client.post(path, json={}, headers={**admin, "Idempotency-Key": str(uuid4())})
                    self.assertEqual(second.status_code, 201)
                    second_id = second.json()["id"]
                    created_ids.append(second_id)
                    succeeded = AsyncMock(return_value=ProviderRefundStatus(
                        provider_id=second_id, provider_payment_id=payment.provider_payment_id,
                        status="succeeded", amount_kopecks=101,
                    ))
                    with patch("payment_service.services.webhooks.get_adapter", return_value=SimpleNamespace(get_refund=succeeded)):
                        self.assertEqual(await verify_notification("refund.succeeded", second_id), "accepted")
                        self.assertEqual(await verify_notification("refund.succeeded", second_id), "accepted")
                    self.assertEqual((await client.get(f"/refunds/{second_id}", headers=admin)).json()["status"], "succeeded")
                    self.assertEqual((await client.post(path, json={}, headers={**admin, "Idempotency-Key": str(uuid4())})).status_code, 409)
                async with session_factory()() as session:
                    events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.payload["refund_id"].as_string() == second_id))).all()
                    self.assertEqual(len(events), 1)
            finally:
                async with session_factory()() as session, session.begin():
                    await session.execute(delete(OutboxEvent).where(OutboxEvent.payload["refund_id"].as_string().in_(created_ids)))
                    await session.execute(delete(Refund).where(Refund.payment_id == payment.id))
                    await session.execute(delete(Payment).where(Payment.id == payment.id))

        with patch("payment_service.core.auth.settings") as settings, patch(
            "payment_service.services.refunds.get_adapter", return_value=SimpleNamespace(create_refund=create),
        ):
            settings.backend_token = SecretStr("backend-test")
            settings.admin_token = SecretStr("admin-test")
            asyncio.run(run())

    def test_full_refund_is_authorized_and_reserved_once(self) -> None:
        if not asyncio.run(database_available()):
            self.skipTest("Local PostgreSQL is unavailable")

        async def run() -> None:
            payment = Payment(
                id=uuid4(), order_id=uuid4(), amount_kopecks=12345, status="succeeded",
                idempotency_key=str(uuid4()), request_fingerprint="payment", provider_payment_id=str(uuid4()),
            )
            pending = Payment(
                id=uuid4(), order_id=uuid4(), amount_kopecks=500, status="pending",
                idempotency_key=str(uuid4()), request_fingerprint="payment",
            )
            async with session_factory()() as session, session.begin():
                session.add_all([payment, pending])
            try:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                    path = f"/payments/{payment.id}/refunds"
                    admin = {"Authorization": "Bearer admin-test"}
                    self.assertEqual((await client.post(path, json={}, headers={"Idempotency-Key": "unauthorized"})).status_code, 401)
                    self.assertEqual((await client.post(path, json={}, headers={**admin, "Idempotency-Key": "wrong", "Authorization": "Bearer backend-test"})).status_code, 401)
                    self.assertEqual((await client.post(path, json={"amount_kopecks": 1}, headers={**admin, "Idempotency-Key": "amount"})).status_code, 400)
                    self.assertEqual((await client.post(f"/payments/{pending.id}/refunds", json={}, headers={**admin, "Idempotency-Key": "pending"})).status_code, 409)
                    first_key, second_key = str(uuid4()), str(uuid4())
                    results = await asyncio.gather(*[
                        client.post(path, json={}, headers={**admin, "Idempotency-Key": key})
                        for key in (first_key, second_key)
                    ])
                    self.assertEqual(sorted(r.status_code for r in results), [201, 409])
                    created = next(r for r in results if r.status_code == 201)
                    self.assertEqual(created.json()["amount_kopecks"], 12345)
                    winner = first_key if results[0].status_code == 201 else second_key
                    repeated = await client.post(path, json={}, headers={**admin, "Idempotency-Key": winner})
                    self.assertEqual(repeated.status_code, 200)
                    self.assertEqual(repeated.json()["id"], created.json()["id"])
                async with session_factory()() as session:
                    refunds = (await session.scalars(select(Refund).where(Refund.payment_id == payment.id))).all()
                    self.assertEqual(len(refunds), 1)
                    self.assertEqual(refunds[0].amount_kopecks, payment.amount_kopecks)
            finally:
                async with session_factory()() as session, session.begin():
                    await session.execute(delete(Refund).where(Refund.payment_id == payment.id))
                    await session.execute(delete(Payment).where(Payment.id.in_([payment.id, pending.id])))

        provider = AsyncMock(side_effect=lambda refund, payment_id: ProviderRefundStatus(
            provider_id=str(refund.id), provider_payment_id=payment_id,
            status="pending", amount_kopecks=refund.amount_kopecks,
        ))
        with patch("payment_service.core.auth.settings") as settings, patch(
            "payment_service.services.refunds.get_adapter",
            return_value=SimpleNamespace(create_refund=provider),
        ):
            settings.backend_token = SecretStr("backend-test")
            settings.admin_token = SecretStr("admin-test")
            asyncio.run(run())
