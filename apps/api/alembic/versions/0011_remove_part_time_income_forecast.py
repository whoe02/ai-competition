"""remove writable part-time income forecasts

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "part_time_income" in columns:
        op.drop_column("users", "part_time_income")


def downgrade() -> None:
    op.add_column("users", sa.Column("part_time_income", sa.BigInteger(), nullable=False, server_default="0"))
