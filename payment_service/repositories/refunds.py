from hashlib import sha256
from uuid import UUID, uuid7

from datetime import timedelta

from sqlalchemy import func, or_, select, update

from payment_service.core.db import session_factory
from payment_service.models.operations import Payment, Refund
from payment_service.schemas.payment import RefundResponse


async def reserve_full_refund(payment_id: UUID, key: str, reason: str | None) -> tuple[RefundResponse | None, bool, str]:
    fingerprint = sha256(payment_id.bytes + (reason or "").encode()).hexdigest()
    async with session_factory()() as session, session.begin():
        # Serialize all reservations for this payment, including requests with different keys.
        payment = await session.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
        if payment is None:
            return None, False, "not_found"
        existing = await session.scalar(select(Refund).where(Refund.idempotency_key == key))
        if existing:
            if existing.payment_id != payment_id or existing.request_fingerprint != fingerprint:
                return None, False, "conflict"
            return RefundResponse.model_validate(existing), False, "ok"
        if payment.status != "succeeded" or payment.resolution_status != "known":
            return None, False, "not_succeeded"
        reserved = await session.scalar(
            select(func.coalesce(func.sum(Refund.amount_kopecks), 0)).where(
                Refund.payment_id == payment_id, Refund.status != "canceled"
            )
        )
        if reserved + payment.amount_kopecks > payment.amount_kopecks:
            return None, False, "insufficient_balance"
        refund = Refund(
            id=uuid7(), payment_id=payment_id, amount_kopecks=payment.amount_kopecks,
            currency=payment.currency, idempotency_key=key, request_fingerprint=fingerprint,
        )
        session.add(refund)
        await session.flush()
        return RefundResponse.model_validate(refund), True, "ok"


async def get_refund(refund_id: UUID) -> RefundResponse | None:
    async with session_factory()() as session:
        refund = await session.get(Refund, refund_id)
        return RefundResponse.model_validate(refund) if refund else None


async def claim_provider_create(refund_id: UUID) -> str | None:
    async with session_factory()() as session, session.begin():
        refund = (await session.execute(
            update(Refund).where(Refund.id == refund_id, Refund.provider_create_started_at.is_(None))
            .values(provider_create_started_at=func.now(), resolution_status="unknown")
            .returning(Refund.payment_id)
        )).scalar_one_or_none()
        if refund is None:
            return None
        return await session.scalar(select(Payment.provider_payment_id).where(Payment.id == refund))


async def finish_provider_create(refund_id: UUID, provider_id: str) -> RefundResponse:
    async with session_factory()() as session, session.begin():
        refund = (await session.execute(
            update(Refund).where(Refund.id == refund_id)
            .values(provider_refund_id=provider_id, resolution_status="known", updated_at=func.now())
            .returning(Refund)
        )).scalar_one()
        return RefundResponse.model_validate(refund)


async def get_refund_details(refund_id: UUID):
    async with session_factory()() as session:
        return (await session.execute(
            select(Refund, Payment.provider_payment_id).join(Payment).where(Refund.id == refund_id)
        )).one_or_none()


async def list_pending_refunds() -> list[UUID]:
    async with session_factory()() as session:
        return list(await session.scalars(select(Refund.id).where(Refund.status == "pending")))


async def claim_reconciliation(refund_id: UUID) -> bool:
    async with session_factory()() as session, session.begin():
        claimed = (await session.execute(
            update(Refund).where(
                Refund.id == refund_id, Refund.status == "pending",
                or_(Refund.provider_refund_id.is_not(None), Refund.reconcile_attempts < 5),
                or_(Refund.reconcile_claimed_at.is_(None),
                    Refund.reconcile_claimed_at < func.now() - timedelta(minutes=1)),
            ).values(reconcile_attempts=Refund.reconcile_attempts + 1,
                     reconcile_claimed_at=func.now()).returning(Refund.id)
        )).scalar_one_or_none()
        return claimed is not None
