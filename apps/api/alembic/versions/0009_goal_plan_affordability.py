"""store deterministic goal affordability alongside each plan version

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("goal_plans")}
    if "affordability_data" not in columns:
        op.add_column(
            "goal_plans",
            sa.Column(
                "affordability_data",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )


def downgrade() -> None:
    op.drop_column("goal_plans", "affordability_data")
