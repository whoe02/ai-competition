"""Read-only goal progress for Butler; plan changes use the Goal workflow."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time
from typing import Literal

from pydantic import BaseModel, Field

from kira.agent.llm import get_chat_model
from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec, money_str
from kira.config import get_settings
from kira.money import Money
from kira.services import goals as goal_service
from kira.services.goal_planning import GoalNotFound as PlannedGoalNotFound
from kira.services.goal_planning import owned_goal
from kira.services.part_time_recommendations import (
    PartTimeRecommendationError,
    create_part_time_recommendation,
)

MODULE = "goals"


class NoArgs(BaseModel):
    """Takes nothing."""


class PartTimeRecommendationArgs(BaseModel):
    goal_id: uuid.UUID | None = None
    goal_reference: str = Field(default="", max_length=80)
    available_hours_per_week: int | None = Field(default=None, ge=1, le=40)
    work_mode: Literal["remote", "on_site", "either"] | None = None
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
    currency = ctx.currency
    try:
        goal = (
            await owned_goal(ctx.session, ctx.user, args.goal_id)
            if args.goal_id is not None
            else await goal_service.resolve_owned_goal_reference(
                ctx.session, ctx.user, args.goal_reference
            )
        )
    except (
        goal_service.GoalNotFound,
        goal_service.AmbiguousGoal,
        PlannedGoalNotFound,
    ) as exc:
        value = {
            "status": "needs_input",
            "missing_fields": ["goal_reference"],
            "reason": str(exc),
        }
        return ToolResult(value, (EvidenceRow("Recommendation status", str(exc)),))

    missing: list[str] = []
    if args.available_hours_per_week is None:
        missing.append("available_hours_per_week")
    if args.work_mode is None:
        missing.append("work_mode")
    if missing:
        value = {
            "status": "needs_input",
            "goal_id": str(goal.id),
            "goal_name": goal.name,
            "missing_fields": missing,
            "reason": (
                "Weekly availability and work preference are needed for relevant suggestions."
            ),
        }
        return ToolResult(
            value,
            (
                EvidenceRow("Goal", goal.name),
                EvidenceRow("Recommendation status", "Needs your availability"),
            ),
        )

    try:
        value = await create_part_time_recommendation(
            ctx.session,
            ctx.user,
            goal.id,
            datetime.combine(ctx.today, time.min, tzinfo=UTC),
            available_hours_per_week=args.available_hours_per_week,
            work_mode=args.work_mode,
            model=get_chat_model(
                temperature=0.2,
                timeout_seconds=get_settings().part_time_model_timeout_seconds,
                max_retries=get_settings().part_time_model_max_retries,
                max_tokens=get_settings().part_time_model_max_tokens,
                extra_body={
                    "enable_thinking": get_settings().part_time_model_enable_thinking,
                },
            ),
            transport_limitations=args.transport_limitations,
        )
        # The recommendation itself is stored by the shared service. The name
        # is presentation context for this Butler turn, so it is kept out of
        # the persisted plan payload and derived from the owned goal here.
        value["goal_name"] = goal.name
    except PlannedGoalNotFound:
        value = {
            "status": "not_available",
            "reason": "Recalculate this goal first so Kira can use its current plan.",
            "recommendations": [],
        }
        return ToolResult(
            value,
            (
                EvidenceRow("Goal", goal.name),
                EvidenceRow("Recommendation status", str(value["reason"])),
            ),
        )
    except PartTimeRecommendationError as exc:
        value = {"status": "error", "reason": str(exc), "recommendations": []}
        return ToolResult(
            value,
            (
                EvidenceRow("Goal", goal.name),
                EvidenceRow("Recommendation status", str(exc)),
            ),
        )
    status = str(value.get("status", "not_available"))
    ratio = value.get("contribution_ratio_before_bp")
    affordability = str(value.get("affordability_status", "income unavailable")).replace(
        "_", " "
    )
    contribution_share = (
        f" · {round(ratio / 100)}% of income" if isinstance(ratio, int) else ""
    )
    recommendation_status = (
        f"{len(value.get('recommendations', []))} live ideas ready"
        if status == "available"
        else str(value.get("reason") or "Unavailable")
    )
    evidence: tuple[EvidenceRow, ...] = (
        EvidenceRow("Goal", goal.name),
        EvidenceRow("Current job", ctx.user.job_title or "Not provided"),
        EvidenceRow(
            "Availability",
            f"{args.available_hours_per_week} hours per week · {args.work_mode.replace('_', ' ')}",
        ),
        EvidenceRow(
            "Goal affordability",
            affordability + contribution_share,
        ),
        EvidenceRow("Recommendation status", recommendation_status),
    )
    if status == "available":
        for index, item in enumerate(value.get("recommendations", []), start=1):
            if not isinstance(item, dict):
                continue
            hourly_min = money_str(
                Money(int(item.get("estimated_hourly_rate_min_sen", 0)), currency)
            )
            hourly_max = money_str(
                Money(int(item.get("estimated_hourly_rate_max_sen", 0)), currency)
            )
            monthly_min = money_str(
                Money(int(item.get("estimated_monthly_income_min_sen", 0)), currency)
            )
            monthly_max = money_str(
                Money(int(item.get("estimated_monthly_income_max_sen", 0)), currency)
            )
            evidence += (
                EvidenceRow(
                    f"Work idea {index}",
                    f"{item.get('role_title')} · {item.get('suggested_hours_per_week')} "
                    f"hours/week · {hourly_min}–{hourly_max}/hour · estimated "
                    f"{monthly_min}–{monthly_max}/month · {item.get('why_relevant')}",
                ),
                EvidenceRow(
                    f"Apply for {item.get('role_title')}",
                    str(item.get("apply_url") or "Application link unavailable"),
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
            "Return up to three suitable read-only AI part-time job recommendations for one "
            "goal, using the "
            "user's profile job title, weekly availability, work-mode preference and "
            "transport limits. Each includes an AI-estimated hourly pay range and "
            "backend-calculated daily, weekly, monthly and goal-timeline effects. Ask for "
            "weekly hours and work mode if the user did not provide them. Never use this "
            "to edit income or Safe to Spend."
        ),
        args_model=PartTimeRecommendationArgs,
        handler=_recommend_part_time,
    ),
)
