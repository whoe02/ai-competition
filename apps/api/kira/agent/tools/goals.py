"""Read-only goal progress for Butler; plan changes use the Goal workflow."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time
from typing import Literal

from pydantic import BaseModel, Field

from kira.agent.llm import get_chat_model
from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec, money_str
from kira.money import Money
from kira.services import goals as goal_service
from kira.services.part_time_recommendations import create_part_time_recommendation

MODULE = "goals"


class NoArgs(BaseModel):
    """Takes nothing."""


class PartTimeRecommendationArgs(BaseModel):
    goal_id: uuid.UUID
    available_hours_per_week: int = Field(ge=1, le=40)
    work_mode: Literal["remote", "on_site", "either"] = "either"
    transport_limitations: str = Field(default="", max_length=200)


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


async def _recommend_part_time(ctx: ToolContext, args: PartTimeRecommendationArgs) -> ToolResult:
    value = await create_part_time_recommendation(
        ctx.session,
        ctx.user,
        args.goal_id,
        datetime.combine(ctx.today, time.min, tzinfo=UTC),
        available_hours_per_week=args.available_hours_per_week,
        work_mode=args.work_mode,
        model=get_chat_model(streaming=False, temperature=0.2),
        transport_limitations=args.transport_limitations,
    )
    evidence = (
        EvidenceRow("Current job", ctx.user.job_title or "Not provided"),
        EvidenceRow(
            "Availability",
            f"{args.available_hours_per_week} hours per week · {args.work_mode.replace('_', ' ')}",
        ),
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
    ToolSpec(
        name="recommend_part_time_jobs",
        module=MODULE,
        kind="read",
        label="Finding relevant part-time work",
        description=(
            "Return three read-only AI part-time job recommendations for one goal, using the "
            "user's profile job title, weekly availability, work-mode preference and "
            "transport limits. Ask for weekly hours and work mode if the user did not "
            "provide them. Never use this to edit income."
        ),
        args_model=PartTimeRecommendationArgs,
        handler=_recommend_part_time,
    ),
)
