from hashlib import sha256
from uuid import UUID

import asyncpg

from payment_service.repositories.payments import claim_provider_create, find_by_key, finish_provider_create, reserve_payment
from payment_service.services.orders import get_order_snapshot
from payment_service.adapters import get_adapter
from payment_service.adapters.base import ProviderError
from payment_service.schemas.payment import ProviderPaymentCreate


class PaymentConflict(Exception):
    pass


def request_fingerprint(order_id: UUID) -> str:
    return sha256(order_id.bytes).hexdigest()


async def create_or_get_payment(key: str, order_id: UUID) -> tuple[dict, bool]:
    fingerprint = request_fingerprint(order_id)
    try:
        existing = await find_by_key(key)
    except (asyncpg.PostgresError, OSError, TimeoutError, ValueError) as exc:
        raise PaymentUnavailable from exc
    if existing:
        if existing["request_fingerprint"] != fingerprint:
            raise PaymentConflict
        return existing, False

    order = await get_order_snapshot(order_id)
    try:
        payment, created = await reserve_payment(key, fingerprint, order)
    except (asyncpg.PostgresError, OSError, TimeoutError, ValueError) as exc:
        raise PaymentUnavailable from exc
    if payment is None or payment["request_fingerprint"] != fingerprint:
        raise PaymentConflict
    try:
        claimed = await claim_provider_create(payment["id"])
    except (asyncpg.PostgresError, OSError, TimeoutError, ValueError) as exc:
        raise PaymentUnavailable from exc
    if not claimed:
        return await find_by_key(key), False
    try:
        provider = await get_adapter().create_payment(ProviderPaymentCreate.model_validate(payment))
        payment = await finish_provider_create(payment["id"], provider.provider_id, provider.confirmation_url)
    except ProviderError:
        payment = await find_by_key(key)
        return payment, False
    except (asyncpg.PostgresError, OSError, TimeoutError, ValueError) as exc:
        raise PaymentUnavailable from exc
    return payment, created


class PaymentUnavailable(Exception):
    pass
