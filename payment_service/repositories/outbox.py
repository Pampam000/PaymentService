from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, update

from payment_service.core.db import session_factory
from payment_service.models.operations import OutboxEvent


async def claim_event() -> tuple[UUID, dict] | None:
    async with session_factory()() as session, session.begin():
        event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.delivered_at.is_(None), OutboxEvent.needs_review.is_(False),
                or_(OutboxEvent.claimed_at.is_(None), OutboxEvent.claimed_at < func.now() - timedelta(minutes=1)),
            ).order_by(OutboxEvent.id).with_for_update(skip_locked=True).limit(1)
        )
        if event is None:
            return None
        event.claimed_at = func.now()
        return event.id, event.payload


async def finish_event(event_id: UUID, *, delivered: bool = False, review: bool = False) -> None:
    async with session_factory()() as session, session.begin():
        await session.execute(update(OutboxEvent).where(OutboxEvent.id == event_id).values(
            delivered_at=func.now() if delivered else None,
            needs_review=review,
            claimed_at=None,
        ))


async def list_review_events() -> list[UUID]:
    async with session_factory()() as session:
        return list((await session.scalars(select(OutboxEvent.id).where(OutboxEvent.needs_review.is_(True)))).all())
