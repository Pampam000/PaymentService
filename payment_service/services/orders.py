from uuid import UUID

import httpx
from pydantic import ValidationError

from payment_service.core.config import settings
from payment_service.schemas.payment import OrderSnapshot


class OrderLookupError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code


async def get_order_snapshot(order_id: UUID) -> OrderSnapshot:
    base_url = settings.backend_base_url
    token = settings.order_lookup_token.get_secret_value()
    if base_url is None or not token:
        raise OrderLookupError(503)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{str(base_url).rstrip('/')}/internal/billing/orders/{order_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.RequestError as exc:
        raise OrderLookupError(503) from exc
    if response.status_code == 404:
        raise OrderLookupError(404)
    if response.status_code == 409:
        raise OrderLookupError(409)
    if response.status_code != 200:
        raise OrderLookupError(503)
    try:
        order = OrderSnapshot.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise OrderLookupError(502) from exc
    if order.order_id != order_id:
        raise OrderLookupError(502)
    return order
