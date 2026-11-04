from datetime import timedelta
from uuid import uuid7

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from payment_service.core.db import session_factory
from payment_service.models.operations import Payment
from payment_service.schemas.payment import OrderSnapshot, PaymentRecord, UnknownPayment
from payment_service.repositories.webhooks import add_event


def as_record(payment: Payment) -> PaymentRecord:
    return PaymentRecord.model_validate(payment)


async def find_by_key(key: str) -> PaymentRecord | None:
    async with session_factory()() as session:
        payment = await session.scalar(select(Payment).where(Payment.idempotency_key == key))
        return as_record(payment) if payment else None


async def reserve_payment(key: str, fingerprint: str, order: OrderSnapshot) -> tuple[PaymentRecord | None, bool]:
    async with session_factory()() as session, session.begin():
        statement = insert(Payment).values(
            id=uuid7(), order_id=order.order_id, user_id=order.user_id,
            plan_id=order.plan_id, period=order.period, amount_kopecks=order.amount_kopecks,
            currency=order.currency, idempotency_key=key, request_fingerprint=fingerprint,
        ).on_conflict_do_nothing().returning(Payment)
        payment = (await session.execute(statement)).scalar_one_or_none()
        if payment:
            return as_record(payment), True
        payment = await session.scalar(select(Payment).where(Payment.idempotency_key == key))
        return (as_record(payment), False) if payment else (None, False)


async def claim_provider_create(payment_id) -> bool:
    async with session_factory()() as session, session.begin():
        statement = (update(Payment)
                     .where(Payment.id == payment_id, Payment.provider_create_started_at.is_(None))
                     .values(provider_create_started_at=func.now(), resolution_status="unknown")
                     .returning(Payment.id))
        return (await session.execute(statement)).scalar_one_or_none() is not None


async def finish_provider_create(payment_id, provider_id: str, confirmation_url: str) -> PaymentRecord:
    async with session_factory()() as session, session.begin():
        statement = (update(Payment).where(Payment.id == payment_id)
                     .values(provider_payment_id=provider_id, confirmation_url=confirmation_url,
                             resolution_status="known", updated_at=func.now())
                     .returning(Payment))
        return as_record((await session.execute(statement)).scalar_one())


async def claim_reconciliation(payment_id) -> PaymentRecord | None:
    async with session_factory()() as session, session.begin():
        statement = (update(Payment)
                     .where(Payment.id == payment_id, Payment.resolution_status == "unknown",
                            Payment.reconcile_attempts < 5,
                            or_(Payment.reconcile_claimed_at.is_(None),
                                Payment.reconcile_claimed_at < func.now() - timedelta(minutes=1)))
                     .values(reconcile_attempts=Payment.reconcile_attempts + 1,
                             reconcile_claimed_at=func.now(), updated_at=func.now())
                     .returning(Payment))
        payment = (await session.execute(statement)).scalar_one_or_none()
        return as_record(payment) if payment else None


async def get_payment(payment_id) -> PaymentRecord | None:
    async with session_factory()() as session:
        payment = await session.get(Payment, payment_id)
        return as_record(payment) if payment else None


async def list_unknown_payments() -> list[UnknownPayment]:
    async with session_factory()() as session:
        payments = await session.scalars(
            select(Payment).where(Payment.resolution_status == "unknown").order_by(Payment.created_at)
        )
        return [UnknownPayment.model_validate(payment) for payment in payments]


async def finish_reconciliation(payment_id, provider_id: str, confirmation_url: str | None, status: str) -> PaymentRecord | None:
    async with session_factory()() as session, session.begin():
        statement = (update(Payment)
                     .where(Payment.id == payment_id, Payment.resolution_status == "unknown", Payment.status == "pending")
                     .values(provider_payment_id=provider_id,
                             confirmation_url=func.coalesce(confirmation_url, Payment.confirmation_url),
                             status=status, resolution_status="known", updated_at=func.now())
                     .returning(Payment))
        payment = (await session.execute(statement)).scalar_one_or_none()
        if payment and status in ("succeeded", "canceled"):
            add_event(session, payment, status)
        return as_record(payment) if payment else None
