import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy import delete, select, update

from payment_service.core.db import database_available, session_factory
from payment_service.main import app
from payment_service.models.operations import Payment
from payment_service.services.payments import PaymentUnavailable
from payment_service.schemas.payment import OrderSnapshot
from payment_service.schemas.payment import ProviderPaymentResult
from payment_service.adapters.yookassa import YooKassaError


class CreatePaymentTests(unittest.TestCase):
    def test_lost_provider_response_is_not_retried_with_new_request(self) -> None:
        if not asyncio.run(database_available()):
            self.skipTest("Local PostgreSQL is unavailable")
        order_id = uuid4()
        key = str(uuid4())
        order = OrderSnapshot.model_validate({
            "order_id": str(order_id), "user_id": str(uuid4()), "plan_id": "basic",
            "period": "month", "amount_kopecks": 101, "currency": "RUB",
            "status": "awaiting_payment",
        })

        async def run() -> None:
            transport = httpx.ASGITransport(app=app)
            headers = {"Authorization": "Bearer backend-test", "Idempotency-Key": key}
            try:
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                    first = await client.post("/payments", json={"order_id": str(order_id)}, headers=headers)
                    second = await client.post("/payments", json={"order_id": str(order_id)}, headers=headers)
                    self.assertEqual((first.status_code, second.status_code), (202, 202))
                    self.assertEqual(first.json()["id"], second.json()["id"])
                    self.assertEqual(first.json()["resolution_status"], "unknown")
                    pending = await client.get(f"/payments/{first.json()['id']}", headers=headers)
                    self.assertEqual(pending.status_code, 200)
                    self.assertEqual(pending.json()["status"], "pending")
                    self.assertEqual(pending.json()["resolution_status"], "unknown")
                    self.assertEqual((await client.post("/payments", json={"order_id": str(order_id)}, headers={**headers, "Idempotency-Key": str(uuid4())})).status_code, 409)
            finally:
                async with session_factory()() as session, session.begin():
                    await session.execute(delete(Payment).where(Payment.order_id == order_id))

        provider = AsyncMock(side_effect=YooKassaError("lost response"))
        with patch("payment_service.core.auth.settings") as auth_settings, patch(
            "payment_service.services.payments.get_order_snapshot", new=AsyncMock(return_value=order)
        ), patch(
            "payment_service.services.payments.get_adapter",
            return_value=SimpleNamespace(create_payment=provider),
        ):
            auth_settings.backend_token = SecretStr("backend-test")
            auth_settings.admin_token = SecretStr("admin-test")
            asyncio.run(run())
        self.assertEqual(provider.await_count, 1)

    def test_snapshot_and_idempotency_in_postgres(self) -> None:
        if not asyncio.run(database_available()):
            self.skipTest("Local PostgreSQL is unavailable")
        order_id = uuid4()
        other_order_id = uuid4()
        key = str(uuid4())
        provider_id = str(uuid4())
        order = OrderSnapshot.model_validate({
            "order_id": str(order_id), "user_id": str(uuid4()), "plan_id": "basic",
            "period": "month", "amount_kopecks": 12345, "currency": "RUB",
            "status": "awaiting_payment",
        })

        async def run() -> None:
            transport = httpx.ASGITransport(app=app)
            headers = {"Authorization": "Bearer backend-test", "Idempotency-Key": key}
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                concurrent = await asyncio.gather(*[
                    client.post("/payments", json={"order_id": str(order_id)}, headers=headers)
                    for _ in range(5)
                ])
                self.assertEqual(sum(r.status_code == 201 for r in concurrent), 1)
                self.assertTrue(all(r.status_code in (200, 201, 202) for r in concurrent))
                self.assertEqual(len({r.json()["id"] for r in concurrent}), 1)
                first = next(r for r in concurrent if r.status_code == 201)
                self.assertEqual(first.status_code, 201, first.text)
                self.assertEqual(UUID(first.json()["id"]).version, 7)
                repeated = await client.post("/payments", json={"order_id": str(order_id)}, headers=headers)
                self.assertEqual(repeated.status_code, 200)
                self.assertEqual(first.json()["id"], repeated.json()["id"])
                self.assertEqual(first.json()["amount_kopecks"], 12345)
                self.assertEqual(first.json()["confirmation_url"], "https://yookassa.ru/pay/example")
                payment_id = first.json()["id"]
                found = await client.get(f"/payments/{payment_id}", headers=headers)
                self.assertEqual(found.status_code, 200)
                self.assertEqual(found.json(), first.json())
                self.assertEqual(set(found.json()), {
                    "id", "order_id", "status", "resolution_status",
                    "amount_kopecks", "currency", "confirmation_url",
                })
                self.assertEqual(found.json()["status"], "pending")
                self.assertEqual((await client.get(f"/payments/{payment_id}")).status_code, 401)
                self.assertEqual((await client.get(f"/payments/{uuid4()}", headers=headers)).status_code, 404)
                self.assertEqual((await client.get("/payments/not-a-uuid", headers=headers)).status_code, 404)
                with patch("payment_service.api.payments.load_payment", new=AsyncMock(side_effect=PaymentUnavailable)):
                    unavailable = await client.get(f"/payments/{payment_id}", headers=headers)
                self.assertEqual(unavailable.status_code, 503)
                self.assertEqual(unavailable.json()["code"], "database_unavailable")
                simultaneous = await asyncio.gather(*[
                    client.post("/payments", json={"order_id": str(order_id)}, headers=headers)
                    for _ in range(5)
                ])
                self.assertTrue(all(r.status_code == 200 and r.json()["id"] == first.json()["id"] for r in simultaneous))
                self.assertEqual((await client.post("/payments", json={"order_id": str(other_order_id)}, headers=headers)).status_code, 409)
                self.assertEqual((await client.post("/payments", json={"order_id": str(order_id)}, headers={**headers, "Idempotency-Key": str(uuid4())})).status_code, 409)
                self.assertEqual((await client.post("/payments", json={"order_id": str(order_id), "amount_kopecks": 1}, headers=headers)).status_code, 400)
                self.assertEqual((await client.post("/payments", json={"order_id": ""}, headers=headers)).status_code, 400)
                self.assertEqual((await client.post("/payments", json={"order_id": str(order_id)}, headers={"Idempotency-Key": key})).status_code, 401)
                async with session_factory()() as session, session.begin():
                    await session.execute(update(Payment).where(Payment.id == UUID(payment_id)).values(status="succeeded"))
                succeeded = await client.get(f"/payments/{payment_id}", headers=headers)
                self.assertEqual(succeeded.status_code, 200)
                self.assertEqual(succeeded.json()["status"], "succeeded")
            async with session_factory()() as session:
                rows = (await session.scalars(select(Payment).where(Payment.order_id == order_id))).all()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].amount_kopecks, 12345)
                self.assertEqual(rows[0].user_id, order.user_id)
                self.assertEqual(rows[0].plan_id, "basic")
                self.assertEqual(rows[0].period, "month")
                await session.execute(delete(Payment).where(Payment.order_id == order_id))
                await session.commit()

        provider = AsyncMock(return_value=ProviderPaymentResult(
            provider_id=provider_id, confirmation_url="https://yookassa.ru/pay/example",
        ))
        with patch("payment_service.core.auth.settings") as auth_settings, patch(
            "payment_service.services.payments.get_order_snapshot", new=AsyncMock(return_value=order)
        ) as lookup, patch(
            "payment_service.services.payments.get_adapter",
            return_value=SimpleNamespace(create_payment=provider),
        ):
            auth_settings.backend_token = SecretStr("backend-test")
            auth_settings.admin_token = SecretStr("admin-test")
            asyncio.run(run())
        self.assertGreaterEqual(lookup.await_count, 2)
        self.assertEqual(provider.await_count, 1)
