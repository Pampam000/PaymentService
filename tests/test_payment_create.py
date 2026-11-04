import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import asyncpg
import httpx
from pydantic import SecretStr

from payment_service.core.config import settings
from payment_service.core.db import database_available
from payment_service.main import app
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
                    self.assertEqual((await client.post("/payments", json={"order_id": str(order_id)}, headers={**headers, "Idempotency-Key": str(uuid4())})).status_code, 409)
            finally:
                connection = await asyncpg.connect(settings.database_url.get_secret_value())
                try:
                    await connection.execute("DELETE FROM payments WHERE order_id = $1", order_id)
                finally:
                    await connection.close()

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
                repeated = await client.post("/payments", json={"order_id": str(order_id)}, headers=headers)
                self.assertEqual(repeated.status_code, 200)
                self.assertEqual(first.json()["id"], repeated.json()["id"])
                self.assertEqual(first.json()["amount_kopecks"], 12345)
                self.assertEqual(first.json()["confirmation_url"], "https://yookassa.ru/pay/example")
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
            connection = await asyncpg.connect(settings.database_url.get_secret_value())
            try:
                rows = await connection.fetch("SELECT * FROM payments WHERE order_id = $1", order_id)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["amount_kopecks"], 12345)
                self.assertEqual(rows[0]["user_id"], order.user_id)
                self.assertEqual(rows[0]["plan_id"], "basic")
                self.assertEqual(rows[0]["period"], "month")
            finally:
                await connection.execute("DELETE FROM payments WHERE order_id = $1", order_id)
                await connection.close()

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
