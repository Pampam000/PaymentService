from uuid import uuid4

from litestar import Request, post
from litestar.response import Response
from pydantic import ValidationError

from payment_service.schemas.payment import CreatePayment, PaymentResponse
from payment_service.services.orders import OrderLookupError
from payment_service.services.payments import PaymentConflict, PaymentUnavailable, create_or_get_payment


def error(status: int, code: str, message: str) -> Response:
    return Response({"code": code, "message": message, "request_id": str(uuid4())}, status_code=status)


@post("/payments", status_code=201)
async def create_payment(request: Request) -> Response[PaymentResponse]:
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
    response = PaymentResponse(
        id=payment["id"], order_id=payment["order_id"],
        status=payment["status"], resolution_status=payment["resolution_status"],
        amount_kopecks=payment["amount_kopecks"], currency=payment["currency"],
        confirmation_url=payment["confirmation_url"],
    )
    return Response(response, status_code=202 if response.resolution_status == "unknown" else 201 if created else 200)
