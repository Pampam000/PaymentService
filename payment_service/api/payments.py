from uuid import UUID, uuid4

from litestar import Request, get, post
from litestar.response import Response
from pydantic import ValidationError

from payment_service.schemas.payment import CreatePayment, ErrorResponse, PaymentResponse
from payment_service.core.observability import correlation_id, count_api_error, current_correlation_id, log_operation
from payment_service.services.orders import OrderLookupError
from payment_service.services.payments import PaymentConflict, PaymentUnavailable, create_or_get_payment, read_payment as load_payment


def error(status: int, code: str, message: str) -> Response:
    count_api_error(code)
    log_operation("api", "error", error_class=code)
    return Response(ErrorResponse(code=code, message=message, request_id=current_correlation_id()), status_code=status)


@get("/payments/{id:uuid}")
async def read_payment(id: UUID) -> Response[PaymentResponse]:
    correlation_id.set(uuid4())
    try:
        payment = await load_payment(id)
    except PaymentUnavailable:
        return error(503, "database_unavailable", "Payment storage unavailable")
    if payment is None:
        return error(404, "payment_not_found", "Payment not found")
    log_operation("payment_read", "ok", local_id=id, provider_id=payment.provider_payment_id)
    return Response(PaymentResponse.model_validate(payment), status_code=200)


@post("/payments", status_code=201)
async def create_payment(request: Request) -> Response[PaymentResponse]:
    correlation_id.set(uuid4())
    key = request.headers.get("idempotency-key", "")
    if not key or len(key) > 64 or key.strip() != key:
        return error(400, "invalid_idempotency_key", "Invalid Idempotency-Key")
    try:
        data = CreatePayment.model_validate(await request.json())
    except (ValidationError, ValueError):
        return error(400, "invalid_request", "Invalid payment request")
    try:
        payment, created = await create_or_get_payment(key, data.order_id)
    except PaymentConflict:
        return error(409, "payment_conflict", "Payment already exists or key was reused")
    except PaymentUnavailable:
        return error(503, "database_unavailable", "Payment storage unavailable")
    except OrderLookupError as exc:
        status = exc.status_code if exc.status_code in (404, 409) else 503
        return error(status, "order_unavailable", "Order cannot be used for payment")
    response = PaymentResponse.model_validate(payment)
    log_operation("payment_create", "unknown" if response.resolution_status == "unknown" else "ok",
                  local_id=payment.id, provider_id=payment.provider_payment_id)
    return Response(response, status_code=202 if response.resolution_status == "unknown" else 201 if created else 200)
