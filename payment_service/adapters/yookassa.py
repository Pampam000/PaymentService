from typing import Any

import httpx
from pydantic import ValidationError

from payment_service.core.config import settings
from payment_service.adapters.base import ProviderError
from payment_service.schemas.payment import (
    ProviderPaymentCreate, ProviderPaymentResult, ProviderPaymentStatus, ProviderRefundCreate, ProviderRefundStatus,
    YooAmount, YooConfirmation, YooPaymentDetails, YooPaymentPayload, YooRefundDetails, YooRefundPayload,
)


class YooKassaError(ProviderError):
    pass


async def _request(method: str, path: str, *, key: str | None = None, payload: dict | None = None) -> dict[str, Any]:
    shop_id = settings.yoo_shop_id
    secret = settings.yoo_secret_key.get_secret_value()
    if not shop_id or not secret:
        raise YooKassaError("YooKassa credentials are missing")
    headers = {"Idempotence-Key": key} if key else None
    try:
        async with httpx.AsyncClient(timeout=5.0, auth=(shop_id, secret)) as client:
            response = await client.request(method, f"https://api.yookassa.ru/v3/{path}", headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise YooKassaError("YooKassa request failed") from exc
    if not isinstance(result, dict):
        raise YooKassaError("Invalid YooKassa response")
    return result


async def create_payment(payment: ProviderPaymentCreate) -> ProviderPaymentResult:
    if settings.payment_return_url is None:
        raise YooKassaError("Payment return URL is missing")
    payload = YooPaymentPayload(
        amount=YooAmount(value=f"{payment.amount_kopecks // 100}.{payment.amount_kopecks % 100:02d}"),
        confirmation=YooConfirmation(return_url=str(settings.payment_return_url)),
        description=f"Subscription {payment.plan_id}: {payment.period}",
        metadata={"order_id": str(payment.order_id), "payment_id": str(payment.id)},
    )
    result = await _request("POST", "payments", key=str(payment.id), payload=payload.model_dump(mode="json"))
    amount = result.get("amount")
    confirmation = result.get("confirmation")
    expected = f"{payment.amount_kopecks // 100}.{payment.amount_kopecks % 100:02d}"
    if not isinstance(amount, dict) or amount.get("value") != expected or amount.get("currency") != "RUB":
        raise YooKassaError("Invalid payment amount")
    if not isinstance(confirmation, dict):
        raise YooKassaError("Invalid payment confirmation")
    provider_id = result.get("id")
    url = confirmation.get("confirmation_url")
    if not isinstance(provider_id, str) or not provider_id or not isinstance(url, str) or not url.startswith("https://"):
        raise YooKassaError("Invalid payment confirmation")
    return ProviderPaymentResult(provider_id=provider_id, confirmation_url=url)


async def get_payment(provider_id: str) -> ProviderPaymentStatus:
    try:
        result = YooPaymentDetails.model_validate(await _request("GET", f"payments/{provider_id}"))
    except ValidationError as exc:
        raise YooKassaError("Invalid YooKassa payment") from exc
    rubles, kopecks = result.amount.value.split(".")
    return ProviderPaymentStatus(
        provider_id=result.id, status=result.status,
        amount_kopecks=int(rubles) * 100 + int(kopecks),
        payment_id=result.metadata.payment_id,
        confirmation_url=result.confirmation.confirmation_url if result.confirmation else None,
    )


def _refund_result(result: dict[str, Any]) -> ProviderRefundStatus:
    try:
        refund = YooRefundDetails.model_validate(result)
        rubles, kopecks = refund.amount.value.split(".")
        return ProviderRefundStatus(
            provider_id=refund.id, provider_payment_id=refund.payment_id,
            status=refund.status, amount_kopecks=int(rubles) * 100 + int(kopecks),
        )
    except ValidationError as exc:
        raise YooKassaError("Invalid YooKassa refund") from exc


async def create_refund(refund: ProviderRefundCreate, provider_payment_id: str) -> ProviderRefundStatus:
    payload = YooRefundPayload(
        payment_id=provider_payment_id,
        amount=YooAmount(value=f"{refund.amount_kopecks // 100}.{refund.amount_kopecks % 100:02d}"),
    )
    return _refund_result(await _request("POST", "refunds", key=str(refund.id), payload=payload.model_dump(mode="json")))


async def get_refund(provider_id: str) -> ProviderRefundStatus:
    return _refund_result(await _request("GET", f"refunds/{provider_id}"))
