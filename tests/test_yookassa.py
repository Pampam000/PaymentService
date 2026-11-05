import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from pydantic import SecretStr

from payment_service.adapters import yookassa
from payment_service.schemas.payment import ProviderPaymentCreate, ProviderRefundCreate


class YooKassaTests(unittest.TestCase):
    def test_payment_amounts_keep_two_decimal_places(self) -> None:
        for kopecks, expected in ((1, "0.01"), (99, "0.99"), (100, "1.00"), (101, "1.01"), (12345, "123.45")):
            with self.subTest(kopecks=kopecks):
                payment = ProviderPaymentCreate(
                    id=uuid4(), order_id=uuid4(), amount_kopecks=kopecks,
                    plan_id="basic", period="month",
                )
                response = {
                    "id": "provider-1", "status": "pending",
                    "metadata": {"payment_id": str(payment.id)},
                    "amount": {"value": expected, "currency": "RUB"},
                    "confirmation": {"confirmation_url": "https://yookassa.ru/pay/one"},
                }
                with patch("payment_service.adapters.yookassa.settings") as settings, patch(
                    "payment_service.adapters.yookassa._request", new=AsyncMock(return_value=response),
                ) as request:
                    settings.payment_return_url = "https://example.com/return"
                    asyncio.run(yookassa.create_payment(payment))
                self.assertEqual(request.await_args.kwargs["payload"]["amount"]["value"], expected)

    def test_create_uses_exact_kopecks_and_local_idempotency_key(self) -> None:
        payment_id = uuid4()
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={
                "id": "provider-1", "status": "pending", "metadata": {"payment_id": str(payment_id)},
                "amount": {"value": "1.01", "currency": "RUB"},
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

    def test_repeated_create_accepts_paid_payment_without_confirmation(self) -> None:
        payment_id = uuid4()
        payment = ProviderPaymentCreate(id=payment_id, order_id=uuid4(), amount_kopecks=101,
                                        plan_id="basic", period="month")
        response = {
            "id": "provider-1", "status": "succeeded", "metadata": {"payment_id": str(payment_id)},
            "amount": {"value": "1.01", "currency": "RUB"},
        }
        with patch("payment_service.adapters.yookassa.settings") as settings, patch(
            "payment_service.adapters.yookassa._request", new=AsyncMock(return_value=response),
        ):
            settings.payment_return_url = "https://example.com/return"
            result = asyncio.run(yookassa.create_payment(payment))
        self.assertEqual((result.status, result.confirmation_url), ("succeeded", None))

        response["metadata"]["payment_id"] = str(uuid4())
        with patch("payment_service.adapters.yookassa.settings") as settings, patch(
            "payment_service.adapters.yookassa._request", new=AsyncMock(return_value=response),
        ):
            settings.payment_return_url = "https://example.com/return"
            with self.assertRaises(yookassa.YooKassaError):
                asyncio.run(yookassa.create_payment(payment))

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

    def test_provider_objects_are_validated_before_return(self) -> None:
        payment_id = uuid4()
        payment = {
            "id": "provider-1", "status": "succeeded",
            "amount": {"value": "1.01", "currency": "RUB"},
            "metadata": {"payment_id": str(payment_id)},
        }
        with patch("payment_service.adapters.yookassa._request", new=AsyncMock(return_value=payment)):
            result = asyncio.run(yookassa.get_payment("provider-1"))
        self.assertEqual((result.payment_id, result.amount_kopecks), (payment_id, 101))

        with patch("payment_service.adapters.yookassa._request", new=AsyncMock(return_value={
            **payment, "amount": {"value": "1.001", "currency": "RUB"},
        })):
            with self.assertRaises(yookassa.YooKassaError):
                asyncio.run(yookassa.get_payment("provider-1"))

        refund = {
            "id": "refund-1", "payment_id": "provider-1", "status": "pending",
            "amount": {"value": "1.01", "currency": "RUB"},
        }
        with patch("payment_service.adapters.yookassa._request", new=AsyncMock(return_value=refund)):
            result = asyncio.run(yookassa.create_refund(
                ProviderRefundCreate(id=uuid4(), amount_kopecks=101), "provider-1",
            ))
        self.assertEqual((result.provider_id, result.amount_kopecks), ("refund-1", 101))

    def test_refund_uses_local_id_as_provider_key(self) -> None:
        refund_id = uuid4()
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={
                "id": "refund-1", "payment_id": "payment-1", "status": "pending",
                "amount": {"value": "1.01", "currency": "RUB"},
            })

        real_client = httpx.AsyncClient
        with patch("payment_service.adapters.yookassa.settings") as settings, patch(
            "payment_service.adapters.yookassa.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
        ):
            settings.yoo_shop_id = "shop"
            settings.yoo_secret_key = SecretStr("secret-value")
            asyncio.run(yookassa.create_refund(ProviderRefundCreate(id=refund_id, amount_kopecks=101), "payment-1"))
        self.assertEqual(requests[0].headers["Idempotence-Key"], str(refund_id))
        self.assertEqual(requests[0].url.path, "/v3/refunds")
        self.assertIn(b'"value":"1.01"', requests[0].content)
