"""income ledger direction and confirmed goal contributions

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("direction", sa.String(length=8), nullable=False, server_default="expense"),
    )
    op.add_column(
        "transactions",
        sa.Column(
            "goal_allocation_applied", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "transactions", sa.Column("income_type", sa.String(length=16), nullable=True)
    )
    op.add_column(
        "transactions",
        sa.Column(
            "updates_income_profile", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_index("ix_transactions_direction", "transactions", ["direction"])
    op.create_index("ix_transactions_income_type", "transactions", ["income_type"])

    op.create_table(
        "goal_contributions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("income_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("contributed_on", sa.Date(), nullable=False),
        sa.Column(
            "source",
            sa.String(length=24),
            nullable=False,
            server_default="income_allocation",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["income_transaction_id"], ["transactions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "goal_id", "income_transaction_id", name="uq_goal_contribution_income"
        ),
    )
    op.create_index("ix_goal_contributions_user_id", "goal_contributions", ["user_id"])
    op.create_index("ix_goal_contributions_goal_id", "goal_contributions", ["goal_id"])
    op.create_index(
        "ix_goal_contributions_income_transaction_id",
        "goal_contributions",
        ["income_transaction_id"],
    )
    op.create_index(
        "ix_goal_contributions_contributed_on", "goal_contributions", ["contributed_on"]
    )


def downgrade() -> None:
    op.drop_table("goal_contributions")
    op.drop_index("ix_transactions_income_type", table_name="transactions")
    op.drop_index("ix_transactions_direction", table_name="transactions")
    op.drop_column("transactions", "updates_income_profile")
    op.drop_column("transactions", "goal_allocation_applied")
    op.drop_column("transactions", "income_type")
    op.drop_column("transactions", "direction")
