from hashlib import sha256
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from payment_service.repositories.payments import claim_provider_create, find_by_key, finish_provider_create, get_payment, reserve_payment
from payment_service.services.orders import get_order_snapshot
from payment_service.adapters import get_adapter
from payment_service.adapters.base import ProviderError
from payment_service.schemas.payment import PaymentRecord, ProviderPaymentCreate


class PaymentConflict(Exception):
    pass


def request_fingerprint(order_id: UUID) -> str:
    return sha256(order_id.bytes).hexdigest()


async def read_payment(payment_id: UUID) -> PaymentRecord | None:
    try:
        return await get_payment(payment_id)
    except (SQLAlchemyError, OSError, TimeoutError, ValueError) as exc:
        raise PaymentUnavailable from exc


async def create_or_get_payment(key: str, order_id: UUID) -> tuple[PaymentRecord, bool]:
    fingerprint = request_fingerprint(order_id)
    try:
        existing = await find_by_key(key)
    except (SQLAlchemyError, OSError, TimeoutError, ValueError) as exc:
        raise PaymentUnavailable from exc
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise PaymentConflict
        return existing, False

    order = await get_order_snapshot(order_id)
    try:
        payment, created = await reserve_payment(key, fingerprint, order)
    except (SQLAlchemyError, OSError, TimeoutError, ValueError) as exc:
        raise PaymentUnavailable from exc
    if payment is None or payment.request_fingerprint != fingerprint:
        raise PaymentConflict
    try:
        claimed = await claim_provider_create(payment.id)
    except (SQLAlchemyError, OSError, TimeoutError, ValueError) as exc:
        raise PaymentUnavailable from exc
    if not claimed:
        return await find_by_key(key), False
    try:
        provider = await get_adapter().create_payment(ProviderPaymentCreate.model_validate(payment))
        payment = await finish_provider_create(payment.id, provider.provider_id, provider.confirmation_url)
    except ProviderError:
        payment = await find_by_key(key)
        return payment, False
    except (SQLAlchemyError, OSError, TimeoutError, ValueError) as exc:
        raise PaymentUnavailable from exc
    return payment, created


class PaymentUnavailable(Exception):
    pass
