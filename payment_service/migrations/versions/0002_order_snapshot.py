"""Keep the immutable Backend order details on each payment."""

from alembic import op
import sqlalchemy as sa


revision = "0002_order_snapshot"
down_revision = "0001_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("user_id", sa.Uuid()))
    op.add_column("payments", sa.Column("plan_id", sa.String(100)))
    op.add_column("payments", sa.Column("period", sa.String(5)))
    op.create_check_constraint("ck_payments_period", "payments", "period IN ('month', 'year')")


def downgrade() -> None:
    op.drop_constraint("ck_payments_period", "payments", type_="check")
    op.drop_column("payments", "period")
    op.drop_column("payments", "plan_id")
    op.drop_column("payments", "user_id")
