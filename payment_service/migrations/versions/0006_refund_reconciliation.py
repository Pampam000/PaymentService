"""Track refund creation and bounded reconciliation attempts."""

from alembic import op
import sqlalchemy as sa

revision = "0006_refund_reconciliation"
down_revision = "0005_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("refunds", sa.Column("provider_create_started_at", sa.DateTime(timezone=True)))
    op.add_column("refunds", sa.Column("reconcile_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("refunds", sa.Column("reconcile_claimed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("refunds", "reconcile_claimed_at")
    op.drop_column("refunds", "reconcile_attempts")
    op.drop_column("refunds", "provider_create_started_at")
