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
    if payment["resolution_status"] != "unknown":
        return "known"
    # YooKassa keeps idempotence keys for 24 hours; never create after that window.
    can_retry_create = (payment["provider_create_started_at"] is not None
                        and datetime.now(timezone.utc) - payment["provider_create_started_at"] < timedelta(hours=24))
    if payment["provider_payment_id"] is None and not can_retry_create:
        return "manual_review"
    payment = await claim_reconciliation(payment_id)
    if payment is None:
        return "rate_limited"
    try:
        if payment["provider_payment_id"]:
            result = await get_adapter().get_payment(payment["provider_payment_id"])
            amount = result.get("amount")
            metadata = result.get("metadata")
            status = result.get("status")
            if (result.get("id") != payment["provider_payment_id"]
                    or not isinstance(amount, dict)
                    or amount.get("value") != f"{payment['amount_kopecks'] // 100}.{payment['amount_kopecks'] % 100:02d}"
                    or amount.get("currency") != "RUB"
                    or not isinstance(metadata, dict)
                    or metadata.get("payment_id") != str(payment_id)
                    or status not in ("pending", "waiting_for_capture", "succeeded", "canceled")):
                return "manual_review"
            confirmation = result.get("confirmation")
            url = confirmation.get("confirmation_url") if isinstance(confirmation, dict) else None
            await finish_reconciliation(payment_id, payment["provider_payment_id"], url,
                                        "pending" if status == "waiting_for_capture" else status)
        else:
            result = await get_adapter().create_payment(ProviderPaymentCreate.model_validate(payment))
            await finish_reconciliation(payment_id, result.provider_id, result.confirmation_url, "pending")
    except ProviderError:
        return "unknown"
    return "resolved"
