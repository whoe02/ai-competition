"""embed goal milestones and scenarios in their plan record

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _iso(value: object) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    plan_columns = {column["name"] for column in inspector.get_columns("goal_plans")}
    if "milestones_data" not in plan_columns:
        op.add_column(
            "goal_plans",
            sa.Column("milestones_data", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )
    if "scenarios_data" not in plan_columns:
        op.add_column(
            "goal_plans",
            sa.Column("scenarios_data", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )

    metadata = sa.MetaData()
    plans = sa.Table("goal_plans", metadata, autoload_with=bind)
    milestones_by_plan: dict[object, list[dict[str, object]]] = defaultdict(list)
    scenarios_by_plan: dict[object, list[dict[str, object]]] = defaultdict(list)

    if inspector.has_table("goal_milestones"):
        milestones = sa.Table("goal_milestones", metadata, autoload_with=bind)
        for row in bind.execute(sa.select(milestones)).mappings():
            milestones_by_plan[row["plan_id"]].append(
                {
                    "percentage": row["percentage"],
                    "amount_sen": row["amount"],
                    "projected_date": _iso(row["projected_date"]),
                }
            )

    if inspector.has_table("goal_scenarios"):
        scenarios = sa.Table("goal_scenarios", metadata, autoload_with=bind)
        for row in bind.execute(sa.select(scenarios)).mappings():
            scenarios_by_plan[row["plan_id"]].append(
                {
                    "scenario_id": str(row["id"]),
                    "label": row["label"],
                    "feasible": row["feasible"],
                    "contribution_per_payday_sen": row["contribution_per_payday"],
                    "target_date": _iso(row["target_date"]),
                    "goal_delay_days": row["goal_delay_days"],
                    "flexible_spending_delta_sen": row["flexible_spending_delta"],
                    "tradeoffs": row["tradeoffs"],
                    "risk_flags": row["risk_flags"],
                    "evidence_refs": row["evidence_refs"],
                    "calculation_version": row["calculation_version"],
                }
            )

    for plan_id in set(milestones_by_plan) | set(scenarios_by_plan):
        bind.execute(
            plans.update()
            .where(plans.c.id == plan_id)
            .values(
                milestones_data=sorted(
                    milestones_by_plan[plan_id], key=lambda item: int(item["percentage"])
                ),
                scenarios_data=scenarios_by_plan[plan_id],
            )
        )

    if inspector.has_table("goal_milestones"):
        op.drop_table("goal_milestones")
    if inspector.has_table("goal_scenarios"):
        op.drop_table("goal_scenarios")


def downgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    plans = sa.Table("goal_plans", metadata, autoload_with=bind)

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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["goal_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_goal_scenarios_plan_id", "goal_scenarios", ["plan_id"])
    op.create_table(
        "goal_milestones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("percentage", sa.Integer(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("projected_date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["goal_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "percentage", name="uq_goal_milestones_plan_percentage"),
    )
    op.create_index("ix_goal_milestones_plan_id", "goal_milestones", ["plan_id"])

    scenarios = sa.Table("goal_scenarios", metadata, autoload_with=bind)
    milestones = sa.Table("goal_milestones", metadata, autoload_with=bind)
    for plan in bind.execute(sa.select(plans)).mappings():
        for item in plan["milestones_data"] or []:
            bind.execute(
                milestones.insert().values(
                    id=uuid.uuid4(),
                    plan_id=plan["id"],
                    percentage=item["percentage"],
                    amount=item["amount_sen"],
                    projected_date=date.fromisoformat(item["projected_date"]),
                )
            )
        for item in plan["scenarios_data"] or []:
            bind.execute(
                scenarios.insert().values(
                    id=uuid.UUID(str(item["scenario_id"])),
                    plan_id=plan["id"],
                    label=item["label"],
                    feasible=item["feasible"],
                    contribution_per_payday=item["contribution_per_payday_sen"],
                    target_date=date.fromisoformat(item["target_date"]),
                    goal_delay_days=item["goal_delay_days"],
                    flexible_spending_delta=item["flexible_spending_delta_sen"],
                    tradeoffs=item["tradeoffs"],
                    risk_flags=item["risk_flags"],
                    evidence_refs=item["evidence_refs"],
                    calculation_version=item["calculation_version"],
                )
            )

    op.drop_column("goal_plans", "scenarios_data")
    op.drop_column("goal_plans", "milestones_data")
