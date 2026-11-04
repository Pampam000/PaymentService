import asyncio
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from payment_service.core.config import settings


@lru_cache(maxsize=1)
def _session_factory(url: str) -> async_sessionmaker:
    engine = create_async_engine(url, poolclass=NullPool, connect_args={"timeout": 3})
    return async_sessionmaker(engine, expire_on_commit=False)


def session_factory() -> async_sessionmaker:
    url = settings.database_url.get_secret_value().replace("postgresql://", "postgresql+asyncpg://", 1)
    return _session_factory(url)


async def database_available() -> bool:
    if not settings.database_url.get_secret_value():
        return False
    try:
        async def probe() -> None:
            async with session_factory()() as session:
                await session.execute(text("SELECT 1"))

        await asyncio.wait_for(probe(), timeout=2)
    except (SQLAlchemyError, OSError, TimeoutError, ValueError):
        return False
    return True
