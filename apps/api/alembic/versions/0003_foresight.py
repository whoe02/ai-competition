"""daily advice, monthly income, goal target dates

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("monthly_income", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column("goals", sa.Column("target_date", sa.Date(), nullable=True))
    op.create_table(
        "daily_advice",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("safe_today", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "on_date", name="uq_daily_advice_user_date"),
    )
    op.create_index("ix_daily_advice_user_id", "daily_advice", ["user_id"])
    op.create_index("ix_daily_advice_on_date", "daily_advice", ["on_date"])


def downgrade() -> None:
    op.drop_index("ix_daily_advice_on_date", table_name="daily_advice")
    op.drop_index("ix_daily_advice_user_id", table_name="daily_advice")
    op.drop_table("daily_advice")
    op.drop_column("goals", "target_date")
    op.drop_column("users", "monthly_income")
