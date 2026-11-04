"""Operator command: python -m payment_service.reconcile_refunds REFUND_ID."""

import argparse
import asyncio
from uuid import UUID

from payment_service.repositories.refunds import list_pending_refunds
from payment_service.services.refunds import reconcile_refund


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile one uncertain refund")
    parser.add_argument("refund_id", type=UUID, nargs="?")
    args = parser.parse_args()
    if args.refund_id is None:
        for refund_id in asyncio.run(list_pending_refunds()):
            print(refund_id)
    else:
        print(asyncio.run(reconcile_refund(args.refund_id)))


if __name__ == "__main__":
    main()
