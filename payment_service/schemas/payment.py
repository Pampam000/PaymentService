from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class CreatePayment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: UUID


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
    model_config = ConfigDict(extra="forbid")

    id: UUID
    order_id: UUID
    status: Literal["pending", "succeeded", "canceled"]
    resolution_status: Literal["known", "unknown"]
    amount_kopecks: StrictInt = Field(ge=1)
    currency: Literal["RUB"]
    confirmation_url: str | None


class ProviderPaymentCreate(BaseModel):
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
    confirmation_url: str = Field(min_length=1, max_length=2048, pattern=r"^https://")


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
