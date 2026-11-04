"""Operational signals with an allowlisted log payload."""

import json
import logging
from contextvars import ContextVar
from uuid import UUID, uuid4

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from payment_service.core.db import session_factory
from payment_service.models.operations import MetricCounter, ReconciliationIssue

logger = logging.getLogger("payment_service.operations")
correlation_id: ContextVar[UUID | None] = ContextVar("correlation_id", default=None)
api_errors: dict[str, int] = {}


def count_api_error(code: str) -> None:
    api_errors[code] = api_errors.get(code, 0) + 1


def current_correlation_id() -> UUID:
    value = correlation_id.get()
    return value if value is not None else uuid4()


def log_operation(operation: str, outcome: str, *, local_id: UUID | None = None,
                  provider_id: str | None = None, error_class: str | None = None) -> None:
    payload = json.dumps({
        "correlation_id": str(current_correlation_id()), "operation": operation,
        "local_id": str(local_id) if local_id else None, "provider_id": provider_id,
        "outcome": outcome, "error_class": error_class,
    }, separators=(",", ":"))
    if outcome in ("error", "unknown", "manual_review", "unavailable"):
        logger.warning(payload)
    else:
        logger.info(payload)


async def increment_counter(name: str) -> None:
    async with session_factory()() as session, session.begin():
        statement = insert(MetricCounter).values(name=name, value=1)
        await session.execute(statement.on_conflict_do_update(
            index_elements=[MetricCounter.name], set_={"value": MetricCounter.value + 1}
        ))


async def record_issue(operation_type: str, operation_id: UUID, unresolved: bool) -> None:
    async with session_factory()() as session, session.begin():
        if unresolved:
            await session.execute(insert(ReconciliationIssue).values(
                operation_type=operation_type, operation_id=operation_id
            ).on_conflict_do_nothing())
        else:
            await session.execute(delete(ReconciliationIssue).where(
                ReconciliationIssue.operation_type == operation_type,
                ReconciliationIssue.operation_id == operation_id,
            ))
