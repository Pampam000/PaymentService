"""Track bounded payment reconciliation attempts."""

from alembic import op
import sqlalchemy as sa

revision = "0004_reconciliation"
down_revision = "0003_provider_claim"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("reconcile_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("payments", sa.Column("reconcile_claimed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("payments", "reconcile_claimed_at")
    op.drop_column("payments", "reconcile_attempts")
