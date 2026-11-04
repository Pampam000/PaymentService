from uuid import UUID, uuid4

from litestar import Request, get, post
from litestar.response import Response
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from payment_service.api.payments import error
from payment_service.core.observability import correlation_id, log_operation
from payment_service.repositories.refunds import reserve_full_refund
from payment_service.schemas.payment import CreateRefund, RefundResponse
from payment_service.services.refunds import RefundUnavailable, read_refund as load_refund, start_refund


@get("/refunds/{id:uuid}")
async def read_refund(id: UUID) -> Response[RefundResponse]:
    correlation_id.set(uuid4())
    try:
        refund = await load_refund(id)
    except RefundUnavailable:
        return error(503, "database_unavailable", "Refund storage unavailable")
    if refund is None:
        return error(404, "refund_not_found", "Refund not found")
    log_operation("refund_read", "ok", local_id=id)
    return Response(refund, status_code=200)


@post("/payments/{id:uuid}/refunds", status_code=201)
async def create_refund(id: UUID, request: Request) -> Response[RefundResponse]:
    correlation_id.set(uuid4())
    key = request.headers.get("idempotency-key", "")
    if not key or len(key) > 64 or key.strip() != key:
        return error(400, "invalid_idempotency_key", "Invalid Idempotency-Key")
    try:
        data = CreateRefund.model_validate(await request.json())
    except (ValidationError, ValueError):
        return error(400, "invalid_request", "Invalid refund request")
    try:
        refund, created, outcome = await reserve_full_refund(id, key, data.reason)
    except IntegrityError:
        return error(409, "refund_conflict", "Idempotency key already used")
    except (SQLAlchemyError, OSError, TimeoutError, ValueError):
        return error(503, "database_unavailable", "Refund storage unavailable")
    if outcome == "not_found":
        return error(404, "payment_not_found", "Payment not found")
    if outcome != "ok":
        return error(409, "refund_conflict", "Payment cannot be refunded")
    try:
        refund = await start_refund(refund.id)
    except RefundUnavailable:
        return error(503, "database_unavailable", "Refund storage unavailable")
    log_operation("refund_create", "unknown" if refund.resolution_status == "unknown" else "ok", local_id=refund.id)
    return Response(refund, status_code=202 if refund.resolution_status == "unknown" else 201 if created else 200)
