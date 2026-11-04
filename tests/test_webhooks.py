import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from litestar.testing import TestClient

from payment_service.api.webhooks import MAX_WEBHOOK_BYTES
from payment_service.main import app
from payment_service.schemas.payment import ProviderPaymentStatus, ProviderRefundStatus
from payment_service.services.webhooks import verify_notification


class WebhookTests(unittest.TestCase):
    def test_valid_notification_is_verified(self) -> None:
        with patch("payment_service.api.webhooks.verify_notification", new=AsyncMock(return_value="accepted")) as verify, TestClient(app) as client:
            response = client.post("/webhooks/yookassa", json={"type": "notification", "event": "payment.succeeded", "object": {"id": "provider-id"}})
        verify.assert_awaited_once_with("payment.succeeded", "provider-id")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "accepted"})

    def test_provider_outage_requests_retry(self) -> None:
        with patch("payment_service.api.webhooks.verify_notification", new=AsyncMock(return_value="unavailable")), TestClient(app) as client:
            response = client.post("/webhooks/yookassa", json={"type": "notification", "event": "payment.succeeded", "object": {"id": "provider-id"}})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "verification_unavailable")

    def test_operation_not_yet_linked_requests_retry(self) -> None:
        import asyncio
        with patch("payment_service.services.webhooks.find_operation", new=AsyncMock(return_value=None)):
            self.assertEqual(asyncio.run(verify_notification("payment.succeeded", "provider-id")), "unavailable")

    def test_bad_notifications_are_rejected(self) -> None:
        with TestClient(app) as client:
            for payload in ({"type": "notification", "event": "payment.succeeded", "object": {}},
                            {"type": "other", "event": "payment.succeeded", "object": {"id": "x"}},
                            ["not", "an", "object"]):
                self.assertEqual(client.post("/webhooks/yookassa", json=payload).status_code, 400)
            self.assertEqual(client.post("/webhooks/yookassa", content=b"{", headers={"content-type": "application/json"}).status_code, 400)

    def test_oversized_notification_is_rejected(self) -> None:
        with TestClient(app) as client:
            response = client.post("/webhooks/yookassa", content=b" " * (MAX_WEBHOOK_BYTES + 1), headers={"content-type": "application/json"})
        self.assertEqual(response.status_code, 413)

    def test_payment_mismatch_never_changes_status(self) -> None:
        import asyncio
        payment_id = uuid4()
        payment = SimpleNamespace(id=payment_id, amount_kopecks=101, currency="RUB")
        get = AsyncMock(return_value=ProviderPaymentStatus(provider_id="provider-id", payment_id=payment_id,
                                                             amount_kopecks=102, status="succeeded"))
        with patch("payment_service.services.webhooks.find_operation", new=AsyncMock(return_value=payment)), patch(
            "payment_service.services.webhooks.get_adapter", return_value=SimpleNamespace(get_payment=get)
        ), patch("payment_service.services.webhooks.confirm_status", new=AsyncMock()) as confirm:
            self.assertEqual(asyncio.run(verify_notification("payment.succeeded", "provider-id")), "ignored")
        confirm.assert_not_awaited()

    def test_confirmed_payment_changes_status(self) -> None:
        import asyncio
        payment_id = uuid4()
        payment = SimpleNamespace(id=payment_id, amount_kopecks=101, currency="RUB")
        get = AsyncMock(return_value=ProviderPaymentStatus(provider_id="provider-id", payment_id=payment_id,
                                                             amount_kopecks=101, status="succeeded"))
        with patch("payment_service.services.webhooks.find_operation", new=AsyncMock(return_value=payment)), patch(
            "payment_service.services.webhooks.get_adapter", return_value=SimpleNamespace(get_payment=get)
        ), patch("payment_service.services.webhooks.confirm_status", new=AsyncMock()) as confirm:
            self.assertEqual(asyncio.run(verify_notification("payment.succeeded", "provider-id")), "accepted")
        confirm.assert_awaited_once_with("payment.succeeded", "provider-id", "succeeded")

    def test_refund_checks_original_payment(self) -> None:
        import asyncio
        refund = SimpleNamespace(amount_kopecks=101, currency="RUB", payment=SimpleNamespace(provider_payment_id="payment-id"))
        get = AsyncMock(return_value=ProviderRefundStatus(provider_id="refund-id", provider_payment_id="other-id",
                                                            amount_kopecks=101, status="succeeded"))
        with patch("payment_service.services.webhooks.find_operation", new=AsyncMock(return_value=refund)), patch(
            "payment_service.services.webhooks.get_adapter", return_value=SimpleNamespace(get_refund=get)
        ), patch("payment_service.services.webhooks.confirm_status", new=AsyncMock()) as confirm:
            self.assertEqual(asyncio.run(verify_notification("refund.succeeded", "refund-id")), "ignored")
        confirm.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
