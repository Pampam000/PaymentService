from payment_service.adapters import yookassa
from payment_service.adapters.base import PaymentAdapter
from payment_service.core.config import settings


def get_adapter() -> PaymentAdapter:
    return {"yookassa": yookassa}[settings.payment_provider]
