from typing import Protocol

from payment_service.schemas.payment import ProviderPaymentCreate, ProviderPaymentResult, ProviderPaymentStatus, ProviderRefundCreate, ProviderRefundStatus


class ProviderError(Exception):
    pass


class PaymentAdapter(Protocol):
    async def create_payment(self, payment: ProviderPaymentCreate) -> ProviderPaymentResult: ...

    async def get_payment(self, provider_id: str) -> ProviderPaymentStatus: ...

    async def create_refund(self, refund: ProviderRefundCreate, provider_payment_id: str) -> ProviderRefundStatus: ...

    async def get_refund(self, provider_id: str) -> ProviderRefundStatus: ...
