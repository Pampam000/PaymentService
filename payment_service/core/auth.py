from hmac import compare_digest
from uuid import uuid4

from litestar import Request
from litestar.response import Response

from payment_service.core.config import settings
from payment_service.core.observability import correlation_id, count_api_error, current_correlation_id, log_operation
from payment_service.schemas.payment import ErrorResponse


def authorize_internal_request(request: Request) -> Response | None:
    correlation_id.set(uuid4())
    path = request.url.path.rstrip("/")
    if path == "/internal/metrics":
        required = settings.admin_token
    elif path == "/payments" or path.startswith("/payments/"):
        required = settings.admin_token if path.endswith("/refunds") else settings.backend_token
    elif path == "/refunds" or path.startswith("/refunds/"):
        required = settings.admin_token
    else:
        return None

    authorization = request.headers.get("authorization", "")
    scheme, separator, supplied = authorization.partition(" ")
    expected = required.get_secret_value()
    if not expected or not separator or scheme.lower() != "bearer" or not compare_digest(supplied, expected):
        count_api_error("unauthorized")
        log_operation("api_auth", "error", error_class="unauthorized")
        return Response(
            ErrorResponse(code="unauthorized", message="Invalid service credentials", request_id=current_correlation_id()),
            status_code=401,
        )
    return None
