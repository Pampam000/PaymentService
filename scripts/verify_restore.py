"""Read-only comparison of a restored database with the YooKassa test shop."""

import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from payment_service.adapters import get_adapter
from payment_service.adapters.base import ProviderError
from payment_service.core.config import settings
from payment_service.models.operations import Payment, Refund


async def verify(database_url: str) -> int:
    source = make_url(settings.database_url.get_secret_value().replace("postgresql://", "postgresql+asyncpg://", 1))
    target = make_url(database_url.replace("postgresql://", "postgresql+asyncpg://", 1))
    if (source.host, source.port, source.database) == (target.host, target.port, target.database):
        raise ValueError("Restore database must differ from the source database")
    engine = create_async_engine(target)
    try:
        async with async_sessionmaker(engine)() as session:
            payments = (await session.scalars(select(Payment))).all()
            refunds = (await session.scalars(select(Refund))).all()
        adapter = get_adapter()
        failures = 0
        for payment in payments:
            if not payment.provider_payment_id:
                print("payment", payment.id, "unverifiable_no_provider_id")
                failures += 1
                continue
            try:
                result = await adapter.get_payment(payment.provider_payment_id)
                matches = (result.provider_id == payment.provider_payment_id
                           and result.payment_id == payment.id
                           and result.amount_kopecks == payment.amount_kopecks)
                provider_status = "pending" if result.status == "waiting_for_capture" else result.status
                outcome = "matched" if matches and provider_status == payment.status else "mismatch"
            except ProviderError:
                outcome = "provider_unavailable"
            print("payment", payment.id, outcome)
            failures += outcome != "matched"
        for refund in refunds:
            payment = next((item for item in payments if item.id == refund.payment_id), None)
            if not refund.provider_refund_id or payment is None:
                print("refund", refund.id, "unverifiable_no_provider_id")
                failures += 1
                continue
            try:
                result = await adapter.get_refund(refund.provider_refund_id)
                matches = (result.provider_id == refund.provider_refund_id
                           and result.provider_payment_id == payment.provider_payment_id
                           and result.amount_kopecks == refund.amount_kopecks)
                outcome = "matched" if matches and result.status == refund.status else "mismatch"
            except ProviderError:
                outcome = "provider_unavailable"
            print("refund", refund.id, outcome)
            failures += outcome != "matched"
        return failures
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare restored operations with the YooKassa test shop")
    parser.add_argument("database_name", help="Name of a separate restored PostgreSQL database")
    args = parser.parse_args()
    if settings.yoo_mode != "test":
        parser.error("Only the YooKassa test shop is supported")
    source = make_url(settings.database_url.get_secret_value().replace("postgresql://", "postgresql+asyncpg://", 1))
    target = os.environ.get("RESTORE_DATABASE_URL") or source.set(database=args.database_name).render_as_string(hide_password=False)
    raise SystemExit(1 if asyncio.run(verify(target)) else 0)


if __name__ == "__main__":
    main()
