"""remove goal funding priority

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("goals")}
    if "priority" not in columns:
        return
    indexes = {index["name"] for index in inspector.get_indexes("goals")}
    if "ix_goals_priority" in indexes:
        op.drop_index("ix_goals_priority", table_name="goals")
    op.drop_column("goals", "priority")


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("goals")}
    if "priority" not in columns:
        op.add_column(
            "goals",
            sa.Column("priority", sa.String(length=12), server_default="flexible", nullable=False),
        )
        op.create_index("ix_goals_priority", "goals", ["priority"])
