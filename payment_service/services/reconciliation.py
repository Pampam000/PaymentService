from datetime import datetime, timedelta, timezone
from uuid import UUID

from payment_service.adapters import get_adapter
from payment_service.adapters.base import ProviderError
from payment_service.repositories.payments import claim_reconciliation, finish_reconciliation, get_payment
from payment_service.schemas.payment import ProviderPaymentCreate


async def reconcile_payment(payment_id: UUID) -> str:
    payment = await get_payment(payment_id)
    if payment is None:
        return "not_found"
    if payment.status != "pending":
        if not payment.provider_payment_id:
            return "manual_review"
        try:
            result = await get_adapter().get_payment(payment.provider_payment_id)
        except ProviderError:
            return "unknown"
        if (result.provider_id != payment.provider_payment_id or result.payment_id != payment_id
                or result.amount_kopecks != payment.amount_kopecks
                or result.status != payment.status):
            return "manual_review"
        return "known"
    # YooKassa keeps idempotence keys for 24 hours; never create after that window.
    can_retry_create = (payment.provider_create_started_at is not None
                        and datetime.now(timezone.utc) - payment.provider_create_started_at < timedelta(hours=24))
    if payment.provider_payment_id is None and not can_retry_create:
        return "manual_review"
    payment = await claim_reconciliation(payment_id)
    if payment is None:
        return "rate_limited"
    try:
        if payment.provider_payment_id:
            result = await get_adapter().get_payment(payment.provider_payment_id)
            if (result.provider_id != payment.provider_payment_id
                    or result.amount_kopecks != payment.amount_kopecks
                    or result.payment_id != payment_id):
                return "manual_review"
            await finish_reconciliation(payment_id, payment.provider_payment_id, result.confirmation_url,
                                        "pending" if result.status == "waiting_for_capture" else result.status)
        else:
            result = await get_adapter().create_payment(ProviderPaymentCreate.model_validate(payment))
            await finish_reconciliation(payment_id, result.provider_id, result.confirmation_url, "pending")
    except ProviderError:
        return "unknown"
    return "resolved"
