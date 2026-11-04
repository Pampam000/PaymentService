"""Claim provider creation before the network call."""

from alembic import op
import sqlalchemy as sa

revision = "0003_provider_claim"
down_revision = "0002_order_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("provider_create_started_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("payments", "provider_create_started_at")
