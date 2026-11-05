"""Operator command: python -m payment_service.reconcile PAYMENT_ID."""

import argparse
import asyncio
from uuid import UUID

from payment_service.repositories.payments import get_payment, list_reconciliation_candidates, list_unknown_payments
from payment_service.services.reconciliation import reconcile_payment
from payment_service.core.observability import increment_counter, log_operation, record_issue


async def run_one(payment_id: UUID) -> str:
    result = await reconcile_payment(payment_id)
    if result == "manual_review":
        await record_issue("payment", payment_id, True)
    elif result in ("known", "resolved"):
        await record_issue("payment", payment_id, False)
    if result == "unknown":
        await increment_counter("reconciliation")
    payment = await get_payment(payment_id)
    log_operation("payment_reconciliation", result, local_id=payment_id,
                  provider_id=payment.provider_payment_id if payment else None,
                  error_class=result if result in ("unknown", "manual_review") else None)
    return (f"{payment_id} outcome={result} status={payment.status if payment else '-'} "
            f"resolution_status={payment.resolution_status if payment else '-'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile one uncertain payment")
    parser.add_argument("payment_id", type=UUID, nargs="?")
    parser.add_argument("--run", action="store_true", help="Reconcile pending and recent operations")
    args = parser.parse_args()
    if args.run:
        async def run() -> None:
            for payment_id in await list_reconciliation_candidates():
                print(await run_one(payment_id))
        asyncio.run(run())
    elif args.payment_id is None:
        for payment in asyncio.run(list_unknown_payments()):
            print(payment.model_dump())
    else:
        print(asyncio.run(run_one(args.payment_id)))


if __name__ == "__main__":
    main()
