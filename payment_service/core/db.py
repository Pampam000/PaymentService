import asyncio

import asyncpg

from payment_service.core.config import settings


async def database_available() -> bool:
    database_url = settings.database_url.get_secret_value()
    if not database_url:
        return False
    try:
        connection = await asyncpg.connect(database_url, timeout=2)
        try:
            await asyncio.wait_for(connection.execute("SELECT 1"), timeout=2)
        finally:
            await connection.close()
    except (asyncpg.PostgresError, OSError, TimeoutError, ValueError):
        return False
    return True
