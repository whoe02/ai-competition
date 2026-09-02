"""Income recommendations: Python calculates; Butler only presents and proposes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time

from pydantic import BaseModel, Field

from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec, money_str
from kira.money import Money
from kira.services.goal_allocations import (
    IncomeNotFound,
    apply_income_allocation,
    latest_unallocated_income,
    recommend_income_allocation,
)

MODULE = "income_planning"


class NoArgs(BaseModel):
    pass


class ApplyIncomeAllocationArgs(BaseModel):
    income_transaction_id: uuid.UUID = Field(
        description="The confirmed income transaction returned by recommend_income_goal_split."
    )


def _as_of(ctx: ToolContext) -> datetime:
    return datetime.combine(ctx.today, time.min, tzinfo=UTC)


def _value(plan) -> dict:
    return {
        "income_transaction_id": plan.income_transaction_id,
        "income_amount_sen": plan.income_amount_sen,
        "available_for_goals_sen": plan.available_for_goals_sen,
        "allocated_sen": plan.allocated_sen,
        "unallocated_income_sen": plan.unallocated_income_sen,
        "allocations": [
            {
                "goal_id": item.goal_id,
                "name": item.name,
                "priority": item.priority,
                "amount_sen": item.amount_sen,
                "income_share_bp": item.income_share_bp,
                "remaining_after_sen": item.remaining_after_sen,
            }
            for item in plan.allocations
        ],
        "risk_flags": list(plan.risk_flags),
        "calculation_version": plan.calculation_version,
    }


async def _recommend(ctx: ToolContext, _: NoArgs) -> ToolResult:
    try:
        income = await latest_unallocated_income(ctx.session, ctx.user)
    except IncomeNotFound:
        return ToolResult(
            {
                "income_transaction_id": None,
                "income_amount_sen": 0,
                "available_for_goals_sen": 0,
                "allocated_sen": 0,
                "unallocated_income_sen": 0,
                "allocations": [],
                "risk_flags": ["no_confirmed_unallocated_income"],
                "calculation_version": "goal-allocation-v1",
            },
            (EvidenceRow("Confirmed income", "None waiting to allocate"),),
        )
    plan = await recommend_income_allocation(ctx.session, ctx.user, income.id, _as_of(ctx))
    evidence = [
        EvidenceRow("Confirmed income", money_str(Money(plan.income_amount_sen, ctx.currency))),
        EvidenceRow("Available for goals", money_str(Money(plan.allocated_sen, ctx.currency))),
    ]
    evidence.extend(
        EvidenceRow(item.name, money_str(Money(item.amount_sen, ctx.currency)))
        for item in plan.allocations
    )
    return ToolResult(_value(plan), tuple(evidence))


async def _apply(ctx: ToolContext, args: ApplyIncomeAllocationArgs) -> ToolResult:
    result = await apply_income_allocation(
        ctx.session, ctx.user, args.income_transaction_id, _as_of(ctx)
    )
    value = _value(result.plan) | {
        "contributions": [
            {
                "goal_id": str(item.goal_id),
                "goal_name": item.goal_name,
                "amount_sen": item.amount_sen,
                "saved_after_sen": item.saved_after_sen,
                "target_amount_sen": item.target_amount_sen,
                "plan_version": item.plan_version,
            }
            for item in result.contributions
        ]
    }
    return ToolResult(
        value,
        tuple(
            EvidenceRow(item.goal_name, money_str(Money(item.amount_sen, ctx.currency)))
            for item in result.contributions
        ),
    )


def _summary(args: ApplyIncomeAllocationArgs) -> str:
    return (
        "Earmark the deterministic goal split for confirmed income "
        f"{args.income_transaction_id}."
    )


SPECS = (
    ToolSpec(
        name="recommend_income_goal_split",
        module=MODULE,
        kind="read",
        label="Calculating a goal split",
        description=(
            "Calculate how the latest confirmed, unallocated income can contribute to active "
            "goals after protected bills and the emergency buffer. Python supplies every amount."
        ),
        args_model=NoArgs,
        handler=_recommend,
    ),
    ToolSpec(
        name="apply_income_goal_split",
        module=MODULE,
        kind="write",
        label="Earmarking goal contributions",
        description=(
            "Apply a previously calculated income split. This is a financial write and must "
            "always wait for explicit approval. The server recalculates before applying."
        ),
        args_model=ApplyIncomeAllocationArgs,
        handler=_apply,
        summarise=_summary,
    ),
)
