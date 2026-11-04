import asyncio
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from pydantic import SecretStr

from payment_service.adapters import yookassa
from payment_service.schemas.payment import ProviderPaymentCreate


class YooKassaTests(unittest.TestCase):
    def test_create_uses_exact_kopecks_and_local_idempotency_key(self) -> None:
        payment_id = uuid4()
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={
                "id": "provider-1", "amount": {"value": "1.01", "currency": "RUB"},
                "confirmation": {"confirmation_url": "https://yookassa.ru/pay/one"},
            })

        real_client = httpx.AsyncClient
        with patch("payment_service.adapters.yookassa.settings") as settings, patch(
            "payment_service.adapters.yookassa.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
        ):
            settings.yoo_shop_id = "shop"
            settings.yoo_secret_key = SecretStr("secret-value")
            settings.payment_return_url = "https://example.com/return"
            payment = ProviderPaymentCreate(id=payment_id, order_id=uuid4(), amount_kopecks=101,
                                       plan_id="basic", period="month")
            result = asyncio.run(yookassa.create_payment(payment))
            self.assertEqual(result.provider_id, "provider-1")
        self.assertEqual(requests[0].headers["Idempotence-Key"], str(payment_id))
        self.assertEqual(requests[0].url.path, "/v3/payments")
        self.assertEqual(requests[0].method, "POST")
        self.assertIn(b'"value":"1.01"', requests[0].content)
        self.assertIn(b'"capture":true', requests[0].content)
        self.assertIn(b'"return_url":"https://example.com/return"', requests[0].content)

    def test_provider_error_hides_response(self) -> None:
        real_client = httpx.AsyncClient
        with patch("payment_service.adapters.yookassa.settings") as settings, patch(
            "payment_service.adapters.yookassa.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(
                transport=httpx.MockTransport(lambda request: httpx.Response(500, text="secret-provider-detail")), **kwargs
            ),
        ):
            settings.yoo_shop_id = "shop"
            settings.yoo_secret_key = SecretStr("secret-value")
            with self.assertRaises(yookassa.YooKassaError) as raised:
                asyncio.run(yookassa.get_payment("provider-1"))
        self.assertNotIn("secret-provider-detail", str(raised.exception))
