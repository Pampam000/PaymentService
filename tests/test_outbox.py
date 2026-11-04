import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy import delete, select

from payment_service.core.db import database_available, session_factory
from payment_service.models.operations import OutboxEvent, Payment
from payment_service.repositories.webhooks import confirm_status
from payment_service.services.outbox import deliver_pending


class OutboxTests(unittest.TestCase):
    def test_ten_concurrent_confirmations_create_one_event(self) -> None:
        if not asyncio.run(database_available()):
            self.skipTest("Local PostgreSQL is unavailable")
        payment_id, order_id = uuid4(), uuid4()
        provider_id = str(uuid4())

        async def run() -> None:
            async with session_factory()() as session, session.begin():
                session.add(Payment(id=payment_id, order_id=order_id, amount_kopecks=101,
                                    idempotency_key=str(uuid4()), request_fingerprint="f" * 64,
                                    provider_payment_id=provider_id))
            try:
                await asyncio.gather(*(confirm_status("payment.succeeded", provider_id, "succeeded") for _ in range(10)))
                async with session_factory()() as session:
                    payment = await session.get(Payment, payment_id)
                    events = (await session.scalars(select(OutboxEvent))).all()
                    related = [event for event in events if event.payload["payment_id"] == str(payment_id)]
                    self.assertEqual(payment.status, "succeeded")
                    self.assertEqual(len(related), 1)
                    self.assertEqual(related[0].payload["order_id"], str(order_id))
            finally:
                async with session_factory()() as session, session.begin():
                    for event in (await session.scalars(select(OutboxEvent))).all():
                        if event.payload["payment_id"] == str(payment_id):
                            await session.delete(event)
                    await session.execute(delete(Payment).where(Payment.id == payment_id))

        asyncio.run(run())

    def test_delivery_reuses_event_id_after_failure(self) -> None:
        event_id = uuid4()
        payload = {"event_id": str(event_id), "status": "succeeded"}
        seen = []

        def respond(request):
            seen.append(request)
            return httpx.Response(503 if len(seen) == 1 else 200)

        real_client = httpx.AsyncClient
        with patch("payment_service.services.outbox.settings") as settings, patch(
            "payment_service.services.outbox.claim_event", new=AsyncMock(side_effect=[(event_id, payload), (event_id, payload)])
        ), patch("payment_service.services.outbox.finish_event", new=AsyncMock()) as finish, patch(
            "payment_service.services.outbox.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
        ):
            settings.backend_base_url = "https://backend.example"
            settings.payment_event_token = SecretStr("event-secret")
            self.assertEqual(asyncio.run(deliver_pending(limit=1)), 0)
            self.assertEqual(asyncio.run(deliver_pending(limit=1)), 1)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0].content, seen[1].content)
        self.assertEqual(seen[0].headers["Authorization"], "Bearer event-secret")
        finish.assert_awaited_once_with(event_id, delivered=True)


if __name__ == "__main__":
    unittest.main()
