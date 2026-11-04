import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_payments_order_id"),
        UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
        UniqueConstraint("provider_payment_id", name="uq_payments_provider_payment_id"),
        CheckConstraint("amount_kopecks > 0", name="ck_payments_positive_amount"),
        CheckConstraint("currency = 'RUB'", name="ck_payments_rub"),
        CheckConstraint("status IN ('pending', 'succeeded', 'canceled')", name="ck_payments_status"),
        CheckConstraint("resolution_status IN ('known', 'unknown')", name="ck_payments_resolution_status"),
        CheckConstraint("period IN ('month', 'year')", name="ck_payments_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid7)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    plan_id: Mapped[str | None] = mapped_column(String(100))
    period: Mapped[str | None] = mapped_column(String(5))
    amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB", server_default="RUB")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    resolution_status: Mapped[str] = mapped_column(String(16), nullable=False, default="known", server_default="known")
    provider_payment_id: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmation_url: Mapped[str | None] = mapped_column(String(2048))
    provider_create_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconcile_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    reconcile_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    refunds: Mapped[list["Refund"]] = relationship(back_populates="payment")


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_refunds_idempotency_key"),
        UniqueConstraint("provider_refund_id", name="uq_refunds_provider_refund_id"),
        CheckConstraint("amount_kopecks > 0", name="ck_refunds_positive_amount"),
        CheckConstraint("currency = 'RUB'", name="ck_refunds_rub"),
        CheckConstraint("status IN ('pending', 'succeeded', 'canceled')", name="ck_refunds_status"),
        CheckConstraint("resolution_status IN ('known', 'unknown')", name="ck_refunds_resolution_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid7)
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False, index=True)
    amount_kopecks: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB", server_default="RUB")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    resolution_status: Mapped[str] = mapped_column(String(16), nullable=False, default="known", server_default="known")
    provider_refund_id: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_create_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconcile_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    reconcile_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    payment: Mapped[Payment] = relationship(back_populates="refunds")


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid7)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    needs_review: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)


class ReconciliationIssue(Base):
    __tablename__ = "reconciliation_issues"

    operation_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    operation_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MetricCounter(Base):
    __tablename__ = "metric_counters"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
