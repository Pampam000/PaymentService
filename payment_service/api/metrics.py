from sqlalchemy import func, select
from litestar import get
from litestar.response import Response

from payment_service.core.db import session_factory
from payment_service.core.observability import api_errors
from payment_service.models.operations import MetricCounter, OutboxEvent, Payment, ReconciliationIssue, Refund


@get("/internal/metrics")
async def metrics() -> Response:
    lines = []
    async with session_factory()() as session:
        for name, model in (("payments", Payment), ("refunds", Refund)):
            for state in ("pending", "unknown"):
                column = model.status if state == "pending" else model.resolution_status
                age = await session.scalar(select(func.coalesce(func.max(
                    func.extract("epoch", func.now() - model.created_at)), 0
                )).where(column == state))
                lines.append(f'payment_service_operation_age_seconds{{type="{name}",state="{state}"}} {int(age)}')
            lag = await session.scalar(select(func.coalesce(func.max(func.extract(
                "epoch", func.now() - func.coalesce(model.reconcile_claimed_at, model.created_at)
            )), 0)).where(model.status == "pending"))
            lines.append(f'payment_service_reconciliation_lag_seconds{{type="{name}"}} {int(lag)}')
        issues = await session.scalar(select(func.count()).select_from(ReconciliationIssue))
        lines.append(f"payment_service_unresolved_discrepancies {issues}")
        for name, value in (await session.execute(select(MetricCounter.name, MetricCounter.value))).all():
            lines.append(f'payment_service_worker_errors_total{{type="{name}"}} {value}')
        review = await session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.needs_review.is_(True)))
        lines.append(f"payment_service_outbox_review_events {review}")
    for code, value in sorted(api_errors.items()):
        lines.append(f'payment_service_api_errors_total{{code="{code}"}} {value}')
    return Response("\n".join(lines) + "\n", media_type="text/plain")
