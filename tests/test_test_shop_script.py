import asyncio
import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

from sqlalchemy import delete

from payment_service.core.db import database_available, session_factory
from payment_service.models.operations import OutboxEvent, Payment, Refund
from payment_service.schemas.payment import ProviderPaymentResult, ProviderPaymentStatus, ProviderRefundStatus
from scripts import test_yookassa


class TestShopScriptTests(unittest.TestCase):
    def test_guard_rejects_live_mode(self) -> None:
        with patch.object(test_yookassa, "settings") as settings:
            settings.environment = "production"
            settings.yoo_mode = "live"
            with self.assertRaises(SystemExit):
                test_yookassa.require_test_shop()

    def test_lost_response_leaves_unknown_payment(self) -> None:
        if not asyncio.run(database_available()):
            self.skipTest("Local PostgreSQL is unavailable")

        async def run() -> None:
            output = io.StringIO()
            payment_id = None
            try:
                with redirect_stdout(output):
                    await test_yookassa.create_payment(101, simulate_lost_response=True)
                payment_id = UUID(output.getvalue().split("Payment ID: ")[1].splitlines()[0])
                self.assertIn("Confirmation URL: https://example.test/checkout", output.getvalue())
                async with session_factory()() as session:
                    payment = await session.get(Payment, payment_id)
                    self.assertEqual((payment.status, payment.resolution_status), ("pending", "unknown"))
                    self.assertIsNone(payment.provider_payment_id)
            finally:
                if payment_id:
                    async with session_factory()() as session, session.begin():
                        await session.execute(delete(Payment).where(Payment.id == payment_id))

        adapter = SimpleNamespace(create_payment=AsyncMock(return_value=ProviderPaymentResult(
            provider_id="script-unknown", confirmation_url="https://example.test/checkout",
        )))
        with patch("scripts.test_yookassa.get_adapter", return_value=adapter):
            asyncio.run(run())
        adapter.create_payment.assert_awaited_once()

    def test_flow_uses_local_payment_without_backend(self) -> None:
        if not asyncio.run(database_available()):
            self.skipTest("Local PostgreSQL is unavailable")

        async def run() -> None:
            output = io.StringIO()
            payment_id = None
            try:
                with redirect_stdout(output):
                    await test_yookassa.create_payment(101)
                payment_id = UUID(output.getvalue().split("Payment ID: ")[1].splitlines()[0])
                with redirect_stdout(io.StringIO()):
                    await test_yookassa.payment_status(payment_id)
                output = io.StringIO()
                with redirect_stdout(output):
                    await test_yookassa.create_refund(payment_id)
                refund_id = UUID(output.getvalue().split("Refund ID: ")[1].splitlines()[0])
                with redirect_stdout(output):
                    await test_yookassa.refund_status(refund_id)
                async with session_factory()() as session:
                    self.assertEqual((await session.get(Payment, payment_id)).status, "succeeded")
                    self.assertEqual((await session.get(Refund, refund_id)).status, "succeeded")
            finally:
                if payment_id:
                    async with session_factory()() as session, session.begin():
                        await session.execute(delete(OutboxEvent).where(OutboxEvent.payload["payment_id"].as_string() == str(payment_id)))
                        await session.execute(delete(Refund).where(Refund.payment_id == payment_id))
                        await session.execute(delete(Payment).where(Payment.id == payment_id))

        adapter = SimpleNamespace(
            create_payment=AsyncMock(return_value=ProviderPaymentResult(
                provider_id="script-payment", confirmation_url="https://example.test/checkout",
            )),
            get_payment=AsyncMock(side_effect=lambda provider_id: ProviderPaymentStatus(
                provider_id=provider_id, payment_id=payment_id_from_adapter(),
                status="succeeded", amount_kopecks=101,
            )),
            create_refund=AsyncMock(side_effect=lambda refund, provider_id: ProviderRefundStatus(
                provider_id=str(refund.id), provider_payment_id=provider_id,
                status="pending", amount_kopecks=101,
            )),
            get_refund=AsyncMock(side_effect=lambda provider_id: ProviderRefundStatus(
                provider_id=provider_id, provider_payment_id="script-payment",
                status="succeeded", amount_kopecks=101,
            )),
        )

        def payment_id_from_adapter():
            return adapter.create_payment.await_args.args[0].id

        with patch("scripts.test_yookassa.get_adapter", return_value=adapter), patch(
            "payment_service.services.refunds.get_adapter", return_value=adapter,
        ):
            asyncio.run(run())

    def test_pending_payment_status_prints_confirmation_url(self) -> None:
        from uuid import uuid4

        payment_id = uuid4()
        payment = SimpleNamespace(id=payment_id, provider_payment_id="provider-id",
                                  amount_kopecks=101, status="pending",
                                  confirmation_url="https://example.test/checkout")
        adapter = SimpleNamespace(get_payment=AsyncMock(return_value=ProviderPaymentStatus(
            provider_id="provider-id", payment_id=payment_id, status="pending", amount_kopecks=101,
        )))
        output = io.StringIO()
        with patch("scripts.test_yookassa.get_payment", new=AsyncMock(return_value=payment)), patch(
            "scripts.test_yookassa.get_adapter", return_value=adapter,
        ), redirect_stdout(output):
            asyncio.run(test_yookassa.payment_status(payment_id))
        self.assertIn("Confirmation URL: https://example.test/checkout", output.getvalue())
