"""Store operational counters and unresolved reconciliation issues."""

from alembic import op
import sqlalchemy as sa

revision = "0007_observability"
down_revision = "0006_refund_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reconciliation_issues",
        sa.Column("operation_type", sa.String(16), primary_key=True),
        sa.Column("operation_id", sa.Uuid(), primary_key=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "metric_counters",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("value", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("metric_counters")
    op.drop_table("reconciliation_issues")
