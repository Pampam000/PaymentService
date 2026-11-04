import json
from uuid import uuid4

from litestar import Request, post
from litestar.response import Response
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from payment_service.api.payments import error
from payment_service.core.observability import correlation_id, log_operation
from payment_service.services.webhooks import verify_notification


MAX_WEBHOOK_BYTES = 64 * 1024


class NotificationObject(BaseModel):
    id: str


class YooNotification(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    event: str
    object: NotificationObject


@post("/webhooks/yookassa", status_code=200)
async def receive_yookassa_webhook(request: Request) -> Response:
    correlation_id.set(uuid4())
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return error(400, "invalid_request", "Expected JSON notification")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_WEBHOOK_BYTES:
            return error(413, "request_too_large", "Notification is too large")
    try:
        payload = json.loads(body)
        notification = YooNotification.model_validate(payload)
        if notification.type != "notification" or notification.event not in {
            "payment.succeeded", "payment.canceled", "refund.succeeded"
        } or not notification.object.id.strip():
            raise ValueError("Unsupported notification")
    except (ValueError, ValidationError, UnicodeDecodeError):
        return error(400, "invalid_request", "Invalid notification")
    try:
        outcome = await verify_notification(notification.event, notification.object.id)
    except (SQLAlchemyError, OSError):
        return error(503, "database_unavailable", "Notification storage unavailable")
    if outcome == "unavailable":
        log_operation(notification.event, "unavailable", error_class="verification_unavailable")
        return error(503, "verification_unavailable", "Notification verification unavailable")
    log_operation(notification.event, outcome,
                  provider_id=notification.object.id if outcome == "accepted" else None)
    return Response({"status": "accepted"}, status_code=200)
