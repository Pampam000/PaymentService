import asyncio
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr, ValidationError

from payment_service.schemas.payment import CreatePayment, OrderSnapshot
from payment_service.services.orders import OrderLookupError, get_order_snapshot


class OrderTests(unittest.TestCase):
    def test_request_cannot_set_price_or_omit_order_id(self) -> None:
        with self.assertRaises(ValidationError):
            CreatePayment.model_validate({"order_id": str(uuid4()), "amount_kopecks": 1})
        with self.assertRaises(ValidationError):
            CreatePayment.model_validate({"order_id": ""})

    def test_money_and_description_limits(self) -> None:
        order = self.valid_order()
        for amount in (1, 9_223_372_036_854_775_807):
            self.assertEqual(OrderSnapshot.model_validate({**order, "amount_kopecks": amount}).amount_kopecks, amount)
        for amount in (0, -1, 9_223_372_036_854_775_808, 1.5, "100"):
            with self.assertRaises(ValidationError):
                OrderSnapshot.model_validate({**order, "amount_kopecks": amount})
        for currency in ("USD", "rub"):
            with self.assertRaises(ValidationError):
                OrderSnapshot.model_validate({**order, "currency": currency})
        with self.assertRaises(ValidationError):
            OrderSnapshot.model_validate({**order, "plan_id": "x" * 101})
        self.assertLessEqual(len(OrderSnapshot.model_validate({**order, "plan_id": "x" * 100}).description), 128)

    def test_lookup_uses_backend_token_and_rejects_mismatched_order(self) -> None:
        order = self.valid_order()
        request_id = UUID(order["order_id"])
        seen = []

        def respond(request):
            seen.append(request)
            return httpx.Response(200, json=order)

        transport = httpx.MockTransport(respond)
        original_client = httpx.AsyncClient

        def client(**kwargs):
            return original_client(transport=transport, **kwargs)

        with patch("payment_service.services.orders.settings") as settings, patch("payment_service.services.orders.httpx.AsyncClient", side_effect=client):
            settings.backend_base_url = "https://backend.internal"
            settings.order_lookup_token = SecretStr("lookup-secret")
            result = asyncio.run(get_order_snapshot(request_id))
            self.assertEqual(result.amount_kopecks, 99000)
            self.assertEqual(seen[0].headers["Authorization"], "Bearer lookup-secret")
            self.assertEqual(seen[0].url.path, f"/internal/billing/orders/{request_id}")
            order["order_id"] = str(uuid4())
            with self.assertRaises(OrderLookupError) as raised:
                asyncio.run(get_order_snapshot(request_id))
            self.assertEqual(raised.exception.status_code, 502)

    @staticmethod
    def valid_order() -> dict:
        return {
            "order_id": str(uuid4()), "user_id": str(uuid4()), "plan_id": "basic",
            "period": "month", "amount_kopecks": 99000, "currency": "RUB", "status": "awaiting_payment",
        }
