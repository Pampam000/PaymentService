from uuid import uuid4

from litestar import get
from litestar.response import Response

from payment_service.core.db import database_available


@get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@get("/health/ready")
async def ready() -> dict[str, str] | Response:
    if not await database_available():
        return Response(
            {"code": "unavailable", "message": "Database unavailable", "request_id": str(uuid4())},
            status_code=503,
        )
    return {"status": "ok"}
