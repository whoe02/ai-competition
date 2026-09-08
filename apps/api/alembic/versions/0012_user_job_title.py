"""add user job title for relevant work recommendations

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "job_title" not in columns:
        op.add_column("users", sa.Column("job_title", sa.String(length=100), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("users", "job_title")
