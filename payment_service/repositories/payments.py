from datetime import timedelta
from uuid import uuid7

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from payment_service.core.db import session_factory
from payment_service.models.operations import Payment
from payment_service.schemas.payment import OrderSnapshot


def as_dict(payment: Payment) -> dict:
    return {column.key: getattr(payment, column.key) for column in Payment.__table__.columns}


async def find_by_key(key: str) -> dict | None:
    async with session_factory()() as session:
        payment = await session.scalar(select(Payment).where(Payment.idempotency_key == key))
        return as_dict(payment) if payment else None


async def reserve_payment(key: str, fingerprint: str, order: OrderSnapshot) -> tuple[dict | None, bool]:
    async with session_factory()() as session, session.begin():
        statement = insert(Payment).values(
            id=uuid7(), order_id=order.order_id, user_id=order.user_id,
            plan_id=order.plan_id, period=order.period, amount_kopecks=order.amount_kopecks,
            currency=order.currency, idempotency_key=key, request_fingerprint=fingerprint,
        ).on_conflict_do_nothing().returning(Payment)
        payment = (await session.execute(statement)).scalar_one_or_none()
        if payment:
            return as_dict(payment), True
        payment = await session.scalar(select(Payment).where(Payment.idempotency_key == key))
        return (as_dict(payment), False) if payment else (None, False)


async def claim_provider_create(payment_id) -> bool:
    async with session_factory()() as session, session.begin():
        statement = (update(Payment)
                     .where(Payment.id == payment_id, Payment.provider_create_started_at.is_(None))
                     .values(provider_create_started_at=func.now(), resolution_status="unknown")
                     .returning(Payment.id))
        return (await session.execute(statement)).scalar_one_or_none() is not None


async def finish_provider_create(payment_id, provider_id: str, confirmation_url: str) -> dict:
    async with session_factory()() as session, session.begin():
        statement = (update(Payment).where(Payment.id == payment_id)
                     .values(provider_payment_id=provider_id, confirmation_url=confirmation_url,
                             resolution_status="known", updated_at=func.now())
                     .returning(Payment))
        return as_dict((await session.execute(statement)).scalar_one())


async def claim_reconciliation(payment_id) -> dict | None:
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
        return as_dict(payment) if payment else None


async def get_payment(payment_id) -> dict | None:
    async with session_factory()() as session:
        payment = await session.get(Payment, payment_id)
        return as_dict(payment) if payment else None


async def list_unknown_payments() -> list[dict]:
    async with session_factory()() as session:
        result = await session.execute(select(
            Payment.id, Payment.order_id, Payment.provider_payment_id,
            Payment.provider_create_started_at, Payment.reconcile_attempts,
            Payment.reconcile_claimed_at,
        ).where(Payment.resolution_status == "unknown").order_by(Payment.created_at))
        return [dict(row._mapping) for row in result]


async def finish_reconciliation(payment_id, provider_id: str, confirmation_url: str | None, status: str) -> dict | None:
    async with session_factory()() as session, session.begin():
        statement = (update(Payment)
                     .where(Payment.id == payment_id, Payment.resolution_status == "unknown")
                     .values(provider_payment_id=provider_id,
                             confirmation_url=func.coalesce(confirmation_url, Payment.confirmation_url),
                             status=status, resolution_status="known", updated_at=func.now())
                     .returning(Payment))
        payment = (await session.execute(statement)).scalar_one_or_none()
        return as_dict(payment) if payment else None
