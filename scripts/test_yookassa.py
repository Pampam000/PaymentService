"""Local test-shop flow without Backend: create, payment-status, refund, refund-status."""

import argparse
import asyncio
from uuid import UUID, uuid4

from payment_service.adapters import get_adapter
from payment_service.core.config import settings
from payment_service.repositories.payments import (
    claim_provider_create, finish_provider_create, get_payment, reserve_payment,
)
from payment_service.repositories.refunds import get_refund, reserve_full_refund
from payment_service.repositories.webhooks import confirm_status
from payment_service.schemas.payment import OrderSnapshot, ProviderPaymentCreate
from payment_service.services.payments import request_fingerprint
from payment_service.services.refunds import reconcile_refund, start_refund


def require_test_shop() -> None:
    if settings.environment != "development" or settings.yoo_mode != "test":
        raise SystemExit("This script requires APP_ENV=development and YOO_MODE=test")
    if not settings.database_url.get_secret_value() or not settings.yoo_shop_id:
        raise SystemExit("DATABASE_URL and test YooKassa credentials are required")


async def create_payment(amount: int) -> None:
    order_id = uuid4()
    order = OrderSnapshot(
        order_id=order_id, user_id=uuid4(), plan_id="local-test", period="month",
        amount_kopecks=amount, currency="RUB", status="awaiting_payment",
    )
    payment, created = await reserve_payment(str(uuid4()), request_fingerprint(order_id), order)
    if not created or not await claim_provider_create(payment.id):
        raise RuntimeError("Could not reserve test payment")
    print(f"Payment ID: {payment.id}", flush=True)
    result = await get_adapter().create_payment(ProviderPaymentCreate.model_validate(payment))
    await finish_provider_create(payment.id, result.provider_id, result.confirmation_url)
    print(f"Confirmation URL: {result.confirmation_url}")


async def payment_status(payment_id: UUID) -> None:
    payment = await get_payment(payment_id)
    if payment is None:
        raise SystemExit("Payment not found")
    if payment.provider_payment_id is None:
        raise SystemExit("Provider payment ID is unknown; use payment reconciliation")
    result = await get_adapter().get_payment(payment.provider_payment_id)
    if (result.provider_id != payment.provider_payment_id or result.payment_id != payment_id
            or result.amount_kopecks != payment.amount_kopecks):
        raise SystemExit("Provider payment does not match the local payment")
    if result.status in ("succeeded", "canceled"):
        await confirm_status("payment." + result.status, result.provider_id, result.status)
    print(f"Payment status: {(await get_payment(payment_id)).status}")


async def create_refund(payment_id: UUID) -> None:
    refund, created, outcome = await reserve_full_refund(payment_id, str(uuid4()), "local test")
    if not created:
        raise SystemExit(f"Refund not created: {outcome}")
    print(f"Refund ID: {refund.id}", flush=True)
    refund = await start_refund(refund.id)
    print(f"Refund status: {refund.status}, resolution: {refund.resolution_status}")


async def refund_status(refund_id: UUID) -> None:
    outcome = await reconcile_refund(refund_id)
    refund = await get_refund(refund_id)
    if refund is None:
        raise SystemExit("Refund not found")
    print(f"Reconciliation: {outcome}")
    print(f"Refund status: {refund.status}, resolution: {refund.resolution_status}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise PaymentService with a YooKassa test shop, without Backend")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create").add_argument("amount_kopecks", type=int)
    commands.add_parser("payment-status").add_argument("payment_id", type=UUID)
    commands.add_parser("refund").add_argument("payment_id", type=UUID)
    commands.add_parser("refund-status").add_argument("refund_id", type=UUID)
    args = parser.parse_args()
    require_test_shop()
    if args.command == "create":
        if args.amount_kopecks <= 0:
            parser.error("amount_kopecks must be positive")
        asyncio.run(create_payment(args.amount_kopecks))
    elif args.command == "payment-status":
        asyncio.run(payment_status(args.payment_id))
    elif args.command == "refund":
        asyncio.run(create_refund(args.payment_id))
    else:
        asyncio.run(refund_status(args.refund_id))


if __name__ == "__main__":
    main()
