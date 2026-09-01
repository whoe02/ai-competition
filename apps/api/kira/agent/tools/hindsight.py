"""The Butler grading her own homework: read-only, and unflattering by design."""

from __future__ import annotations

from pydantic import BaseModel, Field

from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec, money_str
from kira.services.hindsight import DEFAULT_WINDOW_DAYS, MAX_WINDOW_DAYS, hindsight

MODULE = "hindsight"


class ReviewMyAdviceArgs(BaseModel):
    window_days: int = Field(
        default=DEFAULT_WINDOW_DAYS,
        ge=1,
        le=MAX_WINDOW_DAYS,
        description="How many past days to score; 90 is the default.",
    )


def _percent(basis_points: int) -> str:
    return f"{basis_points // 100}%"


def _goal_name(ctx: ToolContext, goal_id: str) -> str:
    for goal in ctx.dashboard.goals:
        if str(goal.id) == goal_id:
            return goal.name
    return goal_id


async def _review(ctx: ToolContext, args: ReviewMyAdviceArgs) -> ToolResult:
    result = await hindsight(ctx.session, ctx.user, ctx.today, args.window_days)
    record = result.record

    if record.days == 0:
        summary = "I have no advised days to score yet, so I have no record to show."
        return ToolResult(
            {"days": 0, "summary": summary},
            (EvidenceRow("Days recorded", "0"),),
        )

    summary = (
        f"You took my number on {record.followed} of {record.days} days. "
        f"On the days you went over, following it would have left you "
        f"{money_str(record.counterfactual_gain)} better off."
    )
    evidence = [
        EvidenceRow("Days scored", str(record.days)),
        EvidenceRow(
            "Days you stayed under",
            f"{record.followed} ({_percent(record.follow_rate_bp)})",
        ),
        EvidenceRow("Average distance from my number", money_str(record.mean_abs_deviation)),
        EvidenceRow("Had you followed it every day", money_str(record.counterfactual_gain)),
    ]
    if (
        result.goal_id is not None
        and result.probability_bp_now is not None
        and result.probability_bp_if_followed is not None
    ):
        evidence.append(
            EvidenceRow(
                _goal_name(ctx, result.goal_id),
                f"{_percent(result.probability_bp_now)} → "
                f"{_percent(result.probability_bp_if_followed)}",
            )
        )
    evidence.append(EvidenceRow("Scoring assumption", result.assumption))

    return ToolResult(
        {
            "window_days": result.window_days,
            "days": record.days,
            "followed": record.followed,
            "follow_rate_bp": record.follow_rate_bp,
            "mean_abs_deviation_sen": record.mean_abs_deviation.sen,
            "counterfactual_gain_sen": record.counterfactual_gain.sen,
            "goal_id": result.goal_id,
            "probability_bp_now": result.probability_bp_now,
            "probability_bp_if_followed": result.probability_bp_if_followed,
            "summary": summary,
            "assumption": result.assumption,
        },
        tuple(evidence),
    )


SPECS = (
    ToolSpec(
        name="review_my_advice",
        module=MODULE,
        kind="read",
        label="Reviewing my own advice",
        description=(
            "Score Kira's past daily advice against what the user actually spent. "
            "Returns how often it was followed, how far off it was, and what following "
            "it every day would have been worth."
        ),
        args_model=ReviewMyAdviceArgs,
        handler=_review,
    ),
)
