"""Create payment and refund operations."""

from alembic import op
import sqlalchemy as sa


revision = "0001_operations"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="RUB"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("resolution_status", sa.String(16), nullable=False, server_default="known"),
        sa.Column("provider_payment_id", sa.String(128)),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("confirmation_url", sa.String(2048)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("order_id", name="uq_payments_order_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
        sa.UniqueConstraint("provider_payment_id", name="uq_payments_provider_payment_id"),
        sa.CheckConstraint("amount_kopecks > 0", name="ck_payments_positive_amount"),
        sa.CheckConstraint("currency = 'RUB'", name="ck_payments_rub"),
        sa.CheckConstraint("status IN ('pending', 'succeeded', 'canceled')", name="ck_payments_status"),
        sa.CheckConstraint("resolution_status IN ('known', 'unknown')", name="ck_payments_resolution_status"),
    )
    op.create_table(
        "refunds",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("payment_id", sa.Uuid(), sa.ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount_kopecks", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="RUB"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("resolution_status", sa.String(16), nullable=False, server_default="known"),
        sa.Column("provider_refund_id", sa.String(128)),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_refunds_idempotency_key"),
        sa.UniqueConstraint("provider_refund_id", name="uq_refunds_provider_refund_id"),
        sa.CheckConstraint("amount_kopecks > 0", name="ck_refunds_positive_amount"),
        sa.CheckConstraint("currency = 'RUB'", name="ck_refunds_rub"),
        sa.CheckConstraint("status IN ('pending', 'succeeded', 'canceled')", name="ck_refunds_status"),
        sa.CheckConstraint("resolution_status IN ('known', 'unknown')", name="ck_refunds_resolution_status"),
    )
    op.create_index("ix_refunds_payment_id", "refunds", ["payment_id"])


def downgrade() -> None:
    op.drop_index("ix_refunds_payment_id", table_name="refunds")
    op.drop_table("refunds")
    op.drop_table("payments")
