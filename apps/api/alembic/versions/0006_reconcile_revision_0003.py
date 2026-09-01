"""reconcile databases created by either historical revision 0003

Revision ID: 0006
Revises: 0005

Revision 0003 was briefly published for Goal planning before the merged
history assigned 0003 to Foresight and moved Goal planning to 0005. A database
that ran the earlier file has the Goal tables but not the Foresight columns.
This compatibility revision restores the schema invariant without deleting or
rewriting any existing financial records.
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if "monthly_income" not in _columns("users"):
        op.add_column(
            "users",
            sa.Column(
                "monthly_income", sa.BigInteger(), nullable=False, server_default="0"
            ),
        )

    if "target_date" not in _columns("goals"):
        op.add_column("goals", sa.Column("target_date", sa.Date(), nullable=True))
    if "ix_goals_target_date" not in _indexes("goals"):
        op.create_index("ix_goals_target_date", "goals", ["target_date"])

    if not _has_table("daily_advice"):
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
            sa.UniqueConstraint(
                "user_id", "on_date", name="uq_daily_advice_user_date"
            ),
        )
    advice_indexes = _indexes("daily_advice")
    if "ix_daily_advice_user_id" not in advice_indexes:
        op.create_index("ix_daily_advice_user_id", "daily_advice", ["user_id"])
    if "ix_daily_advice_on_date" not in advice_indexes:
        op.create_index("ix_daily_advice_on_date", "daily_advice", ["on_date"])


def downgrade() -> None:
    # These objects belong to the logical 0003 Foresight schema. Revision 0006
    # only repairs databases where that schema was skipped, so downgrading the
    # compatibility marker must not remove them.
    pass
