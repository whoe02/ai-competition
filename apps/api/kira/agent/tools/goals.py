"""Read-only goal progress for Butler; plan changes use the Goal workflow."""

from __future__ import annotations

from pydantic import BaseModel

from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec, money_str
from kira.money import Money
from kira.services import goals as goal_service

MODULE = "goals"


class NoArgs(BaseModel):
    """Takes nothing."""


def _months(count: int) -> str:
    return "1 month" if count == 1 else f"{count} months"


async def _list(ctx: ToolContext, _: NoArgs) -> ToolResult:
    views = await goal_service.list_goals(ctx.session, ctx.user)
    currency = ctx.currency
    value = [
        {
            "id": str(view.id),
            "name": view.name,
            "horizon": view.horizon,
            "target_sen": view.target_sen,
            "saved_sen": view.saved_sen,
            "monthly_sen": view.monthly_sen,
            "months_left": view.months_left,
        }
        for view in views
    ]
    evidence = tuple(
        EvidenceRow(
            view.name,
            f"{money_str(Money(view.saved_sen, currency))} of "
            f"{money_str(Money(view.target_sen, currency))} · "
            f"{_months(view.months_left)} left",
        )
        for view in views
    )
    return ToolResult(value, evidence)


SPECS = (
    ToolSpec(
        name="list_goals",
        module=MODULE,
        kind="read",
        label="Reading your goals",
        description=(
            "Every goal with its target, what is saved, the monthly contribution and how "
            "many months remain."
        ),
        args_model=NoArgs,
        handler=_list,
    ),
)
