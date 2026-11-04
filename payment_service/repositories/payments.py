import asyncpg

from payment_service.core.config import settings
from payment_service.schemas.payment import OrderSnapshot


async def find_by_key(key: str) -> dict | None:
    connection = await asyncpg.connect(settings.database_url.get_secret_value(), timeout=3)
    try:
        row = await connection.fetchrow("SELECT * FROM payments WHERE idempotency_key = $1", key)
        return dict(row) if row else None
    finally:
        await connection.close()


async def reserve_payment(key: str, fingerprint: str, order: OrderSnapshot) -> tuple[dict | None, bool]:
    connection = await asyncpg.connect(settings.database_url.get_secret_value(), timeout=3)
    try:
        row = await connection.fetchrow(
            """INSERT INTO payments
               (id, order_id, user_id, plan_id, period, amount_kopecks, currency,
                idempotency_key, request_fingerprint)
               VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7, $8)
               ON CONFLICT DO NOTHING RETURNING *""",
            order.order_id, order.user_id, order.plan_id, order.period,
            order.amount_kopecks, order.currency, key, fingerprint,
        )
        if row:
            return dict(row), True
        row = await connection.fetchrow("SELECT * FROM payments WHERE idempotency_key = $1", key)
        return (dict(row), False) if row else (None, False)
    finally:
        await connection.close()


async def claim_provider_create(payment_id) -> bool:
    connection = await asyncpg.connect(settings.database_url.get_secret_value(), timeout=3)
    try:
        row = await connection.fetchrow(
            """UPDATE payments SET provider_create_started_at = now(), resolution_status = 'unknown'
               WHERE id = $1 AND provider_create_started_at IS NULL RETURNING id""",
            payment_id,
        )
        return row is not None
    finally:
        await connection.close()


async def finish_provider_create(payment_id, provider_id: str, confirmation_url: str) -> dict:
    connection = await asyncpg.connect(settings.database_url.get_secret_value(), timeout=3)
    try:
        row = await connection.fetchrow(
            """UPDATE payments SET provider_payment_id = $2, confirmation_url = $3,
               resolution_status = 'known', updated_at = now() WHERE id = $1 RETURNING *""",
            payment_id, provider_id, confirmation_url,
        )
        return dict(row)
    finally:
        await connection.close()
