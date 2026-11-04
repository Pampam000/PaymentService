from typing import Any, Protocol

from payment_service.schemas.payment import ProviderPaymentCreate, ProviderPaymentResult, ProviderRefundCreate


class ProviderError(Exception):
    pass


class PaymentAdapter(Protocol):
    async def create_payment(self, payment: ProviderPaymentCreate) -> ProviderPaymentResult: ...

    async def get_payment(self, provider_id: str) -> dict[str, Any]: ...

    async def create_refund(self, refund: ProviderRefundCreate, provider_payment_id: str) -> dict[str, Any]: ...

    async def get_refund(self, provider_id: str) -> dict[str, Any]: ...
