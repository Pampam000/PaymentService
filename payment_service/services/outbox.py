import httpx

from payment_service.core.config import settings
from payment_service.repositories.outbox import claim_event, finish_event


async def deliver_pending(limit: int = 100) -> int:
    base_url = settings.backend_base_url
    token = settings.payment_event_token.get_secret_value()
    if base_url is None or not token:
        raise ValueError("Backend event delivery is not configured")
    delivered = 0
    for _ in range(limit):
        event = await claim_event()
        if event is None:
            break
        event_id, payload = event
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{str(base_url).rstrip('/')}/internal/billing/payment-events",
                    headers={"Authorization": f"Bearer {token}"}, json=payload,
                )
        except httpx.RequestError:
            break
        if response.status_code == 200:
            await finish_event(event_id, delivered=True)
            delivered += 1
        elif response.status_code == 409:
            await finish_event(event_id, review=True)
        else:
            break
    return delivered
