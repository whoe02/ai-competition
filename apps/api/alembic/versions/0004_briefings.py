"""durable, idempotent nightly briefings

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "briefings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("proposal_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "on_date", name="uq_briefings_user_date"),
    )
    op.create_index("ix_briefings_user_id", "briefings", ["user_id"])
    op.create_index("ix_briefings_on_date", "briefings", ["on_date"])


def downgrade() -> None:
    op.drop_index("ix_briefings_on_date", table_name="briefings")
    op.drop_index("ix_briefings_user_id", table_name="briefings")
    op.drop_table("briefings")
