from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from payment_service.adapters import get_adapter
from payment_service.adapters.base import ProviderError
from payment_service.repositories.refunds import (
    claim_provider_create, claim_reconciliation, finish_provider_create, get_refund,
    get_refund_details,
)
from payment_service.repositories.webhooks import confirm_status
from payment_service.schemas.payment import ProviderRefundCreate


class RefundUnavailable(Exception):
    pass


async def read_refund(refund_id: UUID):
    try:
        return await get_refund(refund_id)
    except (SQLAlchemyError, OSError, TimeoutError, ValueError) as exc:
        raise RefundUnavailable from exc


async def start_refund(refund_id: UUID):
    try:
        provider_payment_id = await claim_provider_create(refund_id)
        if provider_payment_id is None:
            return await get_refund(refund_id)
        refund = await get_refund(refund_id)
        result = await get_adapter().create_refund(
            ProviderRefundCreate(id=refund.id, amount_kopecks=refund.amount_kopecks), provider_payment_id
        )
        if result.provider_payment_id != provider_payment_id or result.amount_kopecks != refund.amount_kopecks:
            return refund
        return await finish_provider_create(refund_id, result.provider_id)
    except ProviderError:
        return await read_refund(refund_id)
    except (SQLAlchemyError, OSError, TimeoutError, ValueError) as exc:
        raise RefundUnavailable from exc


async def reconcile_refund(refund_id: UUID) -> str:
    details = await get_refund_details(refund_id)
    if details is None:
        return "not_found"
    refund, provider_payment_id = details
    if refund.status != "pending":
        return "known"
    if refund.resolution_status == "known" and refund.provider_refund_id is None:
        return "manual_review"
    can_retry = (refund.provider_create_started_at is not None and
                 datetime.now(timezone.utc) - refund.provider_create_started_at < timedelta(hours=24))
    if refund.provider_refund_id is None and not can_retry:
        return "manual_review"
    if not await claim_reconciliation(refund_id):
        return "rate_limited"
    try:
        if refund.provider_refund_id:
            result = await get_adapter().get_refund(refund.provider_refund_id)
        else:
            result = await get_adapter().create_refund(
                ProviderRefundCreate(id=refund.id, amount_kopecks=refund.amount_kopecks), provider_payment_id
            )
        if (result.provider_payment_id != provider_payment_id or
                result.amount_kopecks != refund.amount_kopecks or
                (refund.provider_refund_id and result.provider_id != refund.provider_refund_id)):
            return "manual_review"
        if refund.resolution_status == "unknown":
            await finish_provider_create(refund_id, result.provider_id)
        if result.status in ("succeeded", "canceled"):
            await confirm_status("refund.succeeded", result.provider_id, result.status)
    except ProviderError:
        return "unknown"
    return "resolved"
