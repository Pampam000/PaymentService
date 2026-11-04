"""Operator command: python -m payment_service.reconcile_refunds REFUND_ID."""

import argparse
import asyncio
from uuid import UUID

from payment_service.repositories.refunds import get_refund_details, list_pending_refunds, list_reconciliation_candidates
from payment_service.services.refunds import reconcile_refund
from payment_service.core.observability import increment_counter, log_operation, record_issue


async def run_one(refund_id: UUID) -> str:
    result = await reconcile_refund(refund_id)
    if result == "manual_review":
        await record_issue("refund", refund_id, True)
    elif result in ("known", "resolved"):
        await record_issue("refund", refund_id, False)
    if result == "unknown":
        await increment_counter("reconciliation")
    details = await get_refund_details(refund_id)
    log_operation("refund_reconciliation", result, local_id=refund_id,
                  provider_id=details[0].provider_refund_id if details else None,
                  error_class=result if result in ("unknown", "manual_review") else None)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile one uncertain refund")
    parser.add_argument("refund_id", type=UUID, nargs="?")
    parser.add_argument("--run", action="store_true", help="Reconcile pending and recent operations")
    args = parser.parse_args()
    if args.run:
        async def run() -> None:
            for refund_id in await list_reconciliation_candidates():
                print(refund_id, await run_one(refund_id))
        asyncio.run(run())
    elif args.refund_id is None:
        for refund_id in asyncio.run(list_pending_refunds()):
            print(refund_id)
    else:
        print(asyncio.run(run_one(args.refund_id)))


if __name__ == "__main__":
    main()
