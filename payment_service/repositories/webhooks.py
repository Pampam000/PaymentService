from uuid import uuid7

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from payment_service.core.db import session_factory
from payment_service.models.operations import OutboxEvent, Payment, Refund


def add_event(session, payment: Payment, status: str, refund: Refund | None = None) -> None:
    event_id = uuid7()
    payload = {
        "event_id": str(event_id), "payment_id": str(payment.id), "order_id": str(payment.order_id),
        "status": "refund.succeeded" if refund else status,
        "amount_kopecks": refund.amount_kopecks if refund else payment.amount_kopecks,
        "currency": refund.currency if refund else payment.currency,
    }
    if refund:
        payload["refund_id"] = str(refund.id)
    session.add(OutboxEvent(id=event_id, payload=payload))


async def find_operation(event: str, provider_id: str):
    model = Refund if event.startswith("refund.") else Payment
    column = model.provider_refund_id if model is Refund else model.provider_payment_id
    statement = select(model).where(column == provider_id)
    if model is Refund:
        statement = statement.options(selectinload(Refund.payment))
    async with session_factory()() as session:
        return await session.scalar(statement)


async def confirm_status(event: str, provider_id: str, status: str) -> None:
    model = Refund if event.startswith("refund.") else Payment
    column = model.provider_refund_id if model is Refund else model.provider_payment_id
    async with session_factory()() as session, session.begin():
        changed = (await session.execute(
            update(model).where(column == provider_id, model.status == "pending")
            .values(status=status, resolution_status="known", updated_at=func.now()).returning(model.id)
        )).scalar_one_or_none()
        if changed is not None:
            if model is Refund:
                refund = await session.get(Refund, changed)
                payment = await session.get(Payment, refund.payment_id)
                if status == "succeeded":
                    add_event(session, payment, status, refund)
            else:
                payment = await session.get(Payment, changed)
                add_event(session, payment, status)
