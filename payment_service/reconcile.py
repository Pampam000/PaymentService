"""Operator command: python -m payment_service.reconcile PAYMENT_ID."""

import argparse
import asyncio
from uuid import UUID

from payment_service.repositories.payments import list_unknown_payments
from payment_service.services.reconciliation import reconcile_payment


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile one uncertain payment")
    parser.add_argument("payment_id", type=UUID, nargs="?")
    args = parser.parse_args()
    if args.payment_id is None:
        for payment in asyncio.run(list_unknown_payments()):
            print(payment)
    else:
        print(asyncio.run(reconcile_payment(args.payment_id)))


if __name__ == "__main__":
    main()
