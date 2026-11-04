import asyncio
from uuid import uuid4

from payment_service.adapters.yookassa import YooKassaError, create_payment
from payment_service.schemas.payment import ProviderPaymentCreate


async def main():
    payment = ProviderPaymentCreate(
        id=uuid4(),
        order_id=uuid4(),
        amount_kopecks=10000,
        plan_id="test",
        period="month",
    )
    print("Локальный ID:", payment.id, flush=True)
    try:
        result = await create_payment(payment)
    except YooKassaError as exc:
        response = getattr(exc.__cause__, "response", None)
        if response is not None:
            details = response.json()
            print("HTTP:", response.status_code)
            for field in ("code", "parameter", "description"):
                if field in details:
                    print(f"{field}: {details[field]}")
        else:
            print("Ошибка соединения или настроек:", exc)
        return
    print("ID ЮKassa:", result.provider_id)
    print("Ссылка:", result.confirmation_url)


asyncio.run(main())
