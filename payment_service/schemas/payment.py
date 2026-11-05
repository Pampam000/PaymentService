from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class CreatePayment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: UUID


class CreateRefund(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, min_length=1, max_length=500)


class RefundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payment_id: UUID
    status: Literal["pending", "succeeded", "canceled"]
    resolution_status: Literal["known", "unknown"]
    amount_kopecks: StrictInt = Field(ge=1)
    currency: Literal["RUB"]


class OrderSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: UUID
    user_id: UUID
    plan_id: str = Field(min_length=1, max_length=100)
    period: Literal["month", "year"]
    amount_kopecks: StrictInt = Field(ge=1, le=9_223_372_036_854_775_807)
    currency: Literal["RUB"]
    status: Literal["awaiting_payment"]

    @property
    def description(self) -> str:
        return f"Subscription {self.plan_id}: {self.period}"


class PaymentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    order_id: UUID
    status: Literal["pending", "succeeded", "canceled"]
    resolution_status: Literal["known", "unknown"]
    amount_kopecks: StrictInt = Field(ge=1)
    currency: Literal["RUB"]
    confirmation_url: str | None


class PaymentRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    status: Literal["pending", "succeeded", "canceled"]
    resolution_status: Literal["known", "unknown"]
    amount_kopecks: StrictInt = Field(ge=1)
    currency: Literal["RUB"]
    confirmation_url: str | None
    user_id: UUID | None
    plan_id: str | None
    period: Literal["month", "year"] | None
    provider_payment_id: str | None
    idempotency_key: str
    request_fingerprint: str
    provider_create_started_at: datetime | None
    reconcile_attempts: int
    reconcile_claimed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UnknownPayment(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    provider_payment_id: str | None
    provider_create_started_at: datetime | None
    reconcile_attempts: int
    reconcile_claimed_at: datetime | None


class ProviderPaymentCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    amount_kopecks: StrictInt = Field(ge=1)
    plan_id: str = Field(min_length=1, max_length=100)
    period: Literal["month", "year"]


class ProviderRefundCreate(BaseModel):
    id: UUID
    amount_kopecks: StrictInt = Field(ge=1)


class ProviderPaymentResult(BaseModel):
    provider_id: str = Field(min_length=1, max_length=128)
    confirmation_url: str | None = Field(default=None, max_length=2048, pattern=r"^https://")
    status: Literal["pending", "waiting_for_capture", "succeeded", "canceled"] = "pending"


class ProviderPaymentStatus(BaseModel):
    provider_id: str = Field(min_length=1, max_length=128)
    status: Literal["pending", "waiting_for_capture", "succeeded", "canceled"]
    amount_kopecks: StrictInt = Field(ge=1)
    payment_id: UUID
    confirmation_url: str | None = None


class ProviderRefundStatus(BaseModel):
    provider_id: str = Field(min_length=1, max_length=128)
    provider_payment_id: str = Field(min_length=1, max_length=128)
    status: Literal["pending", "succeeded", "canceled"]
    amount_kopecks: StrictInt = Field(ge=1)


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: UUID


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class YooAmount(BaseModel):
    value: str
    currency: Literal["RUB"] = "RUB"


class YooConfirmation(BaseModel):
    type: Literal["redirect"] = "redirect"
    return_url: str


class YooPaymentPayload(BaseModel):
    amount: YooAmount
    capture: bool = True
    confirmation: YooConfirmation
    description: str = Field(max_length=128)
    metadata: dict[str, str]


class YooRefundPayload(BaseModel):
    payment_id: str
    amount: YooAmount


class YooPaymentAmount(BaseModel):
    value: str = Field(pattern=r"^\d+\.\d{2}$")
    currency: Literal["RUB"]


class YooPaymentMetadata(BaseModel):
    payment_id: UUID


class YooPaymentConfirmation(BaseModel):
    confirmation_url: str | None = Field(default=None, max_length=2048, pattern=r"^https://")


class YooPaymentDetails(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    status: Literal["pending", "waiting_for_capture", "succeeded", "canceled"]
    amount: YooPaymentAmount
    metadata: YooPaymentMetadata
    confirmation: YooPaymentConfirmation | None = None


class YooRefundDetails(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    payment_id: str = Field(min_length=1, max_length=128)
    status: Literal["pending", "succeeded", "canceled"]
    amount: YooPaymentAmount
