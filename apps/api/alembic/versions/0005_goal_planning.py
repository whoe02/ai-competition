"""versioned deterministic goal planning

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
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
    # Before the Foresight merge, Goal planning was also published as revision
    # 0003. Existing developer databases therefore report 0003 while already
    # containing this schema. Check each object rather than attempting to add
    # it twice; PostgreSQL migrations are transactional, so an old 0003 is
    # either fully present or absent, but the per-object checks also make a
    # partially restored development database repairable.
    columns = _columns("goals")
    if "goal_type" not in columns:
        op.add_column(
            "goals",
            sa.Column(
                "goal_type",
                sa.String(length=40),
                server_default="custom_goal",
                nullable=False,
            ),
        )
    if "currency" not in columns:
        op.add_column(
            "goals",
            sa.Column(
                "currency", sa.String(length=3), server_default="MYR", nullable=False
            ),
        )
    # goals.target_date already arrived with 0003; the planner only needs it
    # indexed. Legacy goals keep it null and stay readable by the old dashboard.
    if "priority" not in columns:
        op.add_column(
            "goals",
            sa.Column(
                "priority", sa.String(length=12), server_default="flexible", nullable=False
            ),
        )
    if "status" not in columns:
        op.add_column(
            "goals",
            sa.Column(
                "status", sa.String(length=16), server_default="active", nullable=False
            ),
        )
    if "funding_account_ids" not in columns:
        op.add_column(
            "goals",
            sa.Column(
                "funding_account_ids", sa.JSON(), server_default="[]", nullable=False
            ),
        )
    if "created_at" not in columns:
        op.add_column(
            "goals",
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
    if "updated_at" not in columns:
        op.add_column(
            "goals",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    goal_indexes = _indexes("goals")
    for name, column in (
        ("ix_goals_goal_type", "goal_type"),
        ("ix_goals_target_date", "target_date"),
        ("ix_goals_priority", "priority"),
        ("ix_goals_status", "status"),
    ):
        if name not in goal_indexes:
            op.create_index(name, "goals", [column])

    if not _has_table("goal_plans"):
        op.create_table(
            "goal_plans",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("goal_id", sa.Uuid(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("approval_status", sa.String(length=12), nullable=False),
            sa.Column("feasible", sa.Boolean(), nullable=False),
            sa.Column("target_amount", sa.BigInteger(), nullable=False),
            sa.Column("current_saved", sa.BigInteger(), nullable=False),
            sa.Column("remaining_amount", sa.BigInteger(), nullable=False),
            sa.Column("required_contribution_per_payday", sa.BigInteger(), nullable=False),
            sa.Column("next_required_reserve", sa.BigInteger(), nullable=False),
            sa.Column("target_date", sa.Date(), nullable=False),
            sa.Column("projected_completion_date", sa.Date(), nullable=True),
            sa.Column("risk_flags", sa.JSON(), nullable=False),
            sa.Column("assumptions", sa.JSON(), nullable=False),
            sa.Column("evidence_refs", sa.JSON(), nullable=False),
            sa.Column("calculation_version", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["goal_id"],
                ["goals.id"],
                name="fk_goal_plans_goal_id_goals",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_goal_plans"),
            sa.UniqueConstraint("goal_id", "version", name="uq_goal_plans_goal_version"),
        )
    plan_indexes = _indexes("goal_plans")
    if "ix_goal_plans_goal_id" not in plan_indexes:
        op.create_index("ix_goal_plans_goal_id", "goal_plans", ["goal_id"])
    if "ix_goal_plans_approval_status" not in plan_indexes:
        op.create_index(
            "ix_goal_plans_approval_status", "goal_plans", ["approval_status"]
        )

    if not _has_table("goal_scenarios"):
        op.create_table(
            "goal_scenarios",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("plan_id", sa.Uuid(), nullable=False),
            sa.Column("label", sa.String(length=60), nullable=False),
            sa.Column("feasible", sa.Boolean(), nullable=False),
            sa.Column("contribution_per_payday", sa.BigInteger(), nullable=False),
            sa.Column("target_date", sa.Date(), nullable=False),
            sa.Column("goal_delay_days", sa.Integer(), nullable=False),
            sa.Column("flexible_spending_delta", sa.BigInteger(), nullable=False),
            sa.Column("tradeoffs", sa.JSON(), nullable=False),
            sa.Column("risk_flags", sa.JSON(), nullable=False),
            sa.Column("evidence_refs", sa.JSON(), nullable=False),
            sa.Column("calculation_version", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["plan_id"],
                ["goal_plans.id"],
                name="fk_goal_scenarios_plan_id_goal_plans",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_goal_scenarios"),
        )
    if "ix_goal_scenarios_plan_id" not in _indexes("goal_scenarios"):
        op.create_index("ix_goal_scenarios_plan_id", "goal_scenarios", ["plan_id"])

    if not _has_table("goal_milestones"):
        op.create_table(
            "goal_milestones",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("plan_id", sa.Uuid(), nullable=False),
            sa.Column("percentage", sa.Integer(), nullable=False),
            sa.Column("amount", sa.BigInteger(), nullable=False),
            sa.Column("projected_date", sa.Date(), nullable=False),
            sa.ForeignKeyConstraint(
                ["plan_id"],
                ["goal_plans.id"],
                name="fk_goal_milestones_plan_id_goal_plans",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_goal_milestones"),
            sa.UniqueConstraint(
                "plan_id", "percentage", name="uq_goal_milestones_plan_percentage"
            ),
        )
    if "ix_goal_milestones_plan_id" not in _indexes("goal_milestones"):
        op.create_index("ix_goal_milestones_plan_id", "goal_milestones", ["plan_id"])


def downgrade() -> None:
    op.drop_table("goal_milestones")
    op.drop_table("goal_scenarios")
    op.drop_table("goal_plans")
    op.drop_index("ix_goals_status", table_name="goals")
    op.drop_index("ix_goals_priority", table_name="goals")
    op.drop_index("ix_goals_target_date", table_name="goals")
    op.drop_index("ix_goals_goal_type", table_name="goals")
    for column in (
        "updated_at",
        "created_at",
        "funding_account_ids",
        "status",
        "priority",
        "currency",
        "goal_type",
    ):
        op.drop_column("goals", column)
