"""add forecast-only part-time income and plan-owned recommendations

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "part_time_income" not in user_columns:
        op.add_column(
            "users",
            sa.Column("part_time_income", sa.BigInteger(), nullable=False, server_default="0"),
        )

    plan_columns = {column["name"] for column in inspector.get_columns("goal_plans")}
    if "part_time_recommendation_data" not in plan_columns:
        op.add_column(
            "goal_plans",
            sa.Column(
                "part_time_recommendation_data",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )


def downgrade() -> None:
    op.drop_column("goal_plans", "part_time_recommendation_data")
    op.drop_column("users", "part_time_income")
