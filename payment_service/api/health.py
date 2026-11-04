from uuid import uuid4

from litestar import get
from litestar.response import Response

from payment_service.core.db import database_available
from payment_service.schemas.payment import ErrorResponse, HealthResponse


@get("/health/live")
async def live() -> HealthResponse:
    return HealthResponse()


@get("/health/ready")
async def ready() -> HealthResponse | Response:
    if not await database_available():
        return Response(
            ErrorResponse(code="unavailable", message="Database unavailable", request_id=uuid4()),
            status_code=503,
        )
    return HealthResponse()
