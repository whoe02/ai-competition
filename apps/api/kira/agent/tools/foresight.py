"""The Butler's view of the forecast: read-only, evidence-first answers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec, money_str
from kira.engine.types import Driver, Lever
from kira.money import Money
from kira.services.foresight import DEFAULT_HORIZON_DAYS, compare, foresight

MODULE = "foresight"


class ProjectFutureArgs(BaseModel):
    horizon_days: int = Field(
        default=DEFAULT_HORIZON_DAYS,
        ge=1,
        le=365,
        description="How many days to project ahead; 180 is the default demo horizon.",
    )


class LeverArgs(BaseModel):
    kind: Literal["goal_monthly", "commitment_amount", "daily_spend"]
    target_id: str
    delta_sen: int = Field(description="The change in sen; negative means less.")


class CompareScenariosArgs(ProjectFutureArgs):
    levers: list[LeverArgs] = Field(min_length=1, max_length=12)


class ExplainProbabilityArgs(BaseModel):
    goal_id: str | None = Field(
        default=None,
        description="The goal to explain. Omit it to explain the nearest dated goal.",
    )


def _percent(basis_points: int) -> str:
    return f"{basis_points // 100}%"


def _goal_name(ctx: ToolContext, goal_id: str) -> str:
    for goal in ctx.dashboard.goals:
        if str(goal.id) == goal_id:
            return goal.name
    return goal_id


def _lever_label(lever: Lever) -> str:
    amount = money_str(Money(abs(lever.delta.sen), lever.delta.currency))
    if lever.kind == "goal_monthly":
        return f"Save {amount} more each month"
    if lever.kind == "daily_spend":
        direction = "less" if lever.delta.sen < 0 else "more"
        return f"Spend {amount} {direction} each day"
    direction = "reduce" if lever.delta.sen < 0 else "raise"
    return f"{direction.capitalize()} a commitment by {amount}"


def _driver_value(driver: Driver) -> dict[str, int | str]:
    return {
        "kind": driver.lever.kind,
        "target_id": driver.lever.target_id,
        "delta_sen": driver.lever.delta.sen,
        "probability_bp_before": driver.probability_bp_before,
        "probability_bp_after": driver.probability_bp_after,
        "bp_per_ringgit": driver.bp_per_ringgit,
    }


async def _project(ctx: ToolContext, args: ProjectFutureArgs) -> ToolResult:
    forecast = await foresight(ctx.session, ctx.user, ctx.today, args.horizon_days)
    closing = forecast.bands.bands.p50[-1]
    value = {
        "horizon_days": forecast.horizon_days,
        "median_closing_sen": closing.sen,
        "outlooks": [
            {
                "goal_id": outlook.goal_id,
                "target_date": outlook.target_date.isoformat(),
                "probability_bp": outlook.probability_bp,
                "median_shortfall_sen": outlook.median_shortfall.sen,
            }
            for outlook in forecast.bands.outlooks
        ],
        "drivers": [_driver_value(driver) for driver in forecast.drivers],
        "assumption": forecast.assumption,
    }
    evidence = [
        EvidenceRow(
            f"Median balance in {forecast.horizon_days} days",
            money_str(closing),
        )
    ]
    evidence.extend(
        EvidenceRow(
            f"{_goal_name(ctx, outlook.goal_id)} by {outlook.target_date.isoformat()}",
            _percent(outlook.probability_bp),
        )
        for outlook in forecast.bands.outlooks
    )
    evidence.append(EvidenceRow("Forecast assumption", forecast.assumption))
    return ToolResult(value, tuple(evidence))


async def _compare(ctx: ToolContext, args: CompareScenariosArgs) -> ToolResult:
    levers = tuple(
        Lever(item.kind, item.target_id, Money(item.delta_sen, ctx.currency))
        for item in args.levers
    )
    baseline = await foresight(ctx.session, ctx.user, ctx.today, args.horizon_days)
    results = await compare(ctx.session, ctx.user, ctx.today, levers, args.horizon_days)
    before = {outlook.goal_id: outlook.probability_bp for outlook in baseline.bands.outlooks}
    primary_id = next(iter(before), None)

    rows: list[EvidenceRow] = []
    values: list[dict] = []
    for result in results:
        goal_id = result.lever.target_id if result.lever.kind == "goal_monthly" else primary_id
        after = next(
            (outlook.probability_bp for outlook in result.outlooks if outlook.goal_id == goal_id),
            None,
        )
        prior = before.get(goal_id) if goal_id is not None else None
        probability = (
            f"{_percent(prior)} → {_percent(after)}"
            if prior is not None and after is not None
            else "No dated goal falls within this horizon"
        )
        rows.append(EvidenceRow(_lever_label(result.lever), probability))
        values.append(
            {
                "kind": result.lever.kind,
                "target_id": result.lever.target_id,
                "delta_sen": result.lever.delta.sen,
                "probability_bp_before": prior,
                "probability_bp_after": after,
                "safe_today_after_sen": result.safe_today_after.sen,
            }
        )

    return ToolResult({"horizon_days": args.horizon_days, "results": values}, tuple(rows))


async def _explain(ctx: ToolContext, args: ExplainProbabilityArgs) -> ToolResult:
    forecast = await foresight(
        ctx.session, ctx.user, ctx.today, driver_goal_id=args.goal_id
    )
    outlook = next(
        (outlook for outlook in forecast.bands.outlooks if outlook.goal_id == args.goal_id),
        None,
    )
    if args.goal_id is None and forecast.bands.outlooks:
        outlook = forecast.bands.outlooks[0]

    if outlook is None:
        summary = (
            "There is no dated goal inside this forecast horizon yet. "
            f"{forecast.assumption}"
        )
        return ToolResult(
            {"summary": summary, "outlook": None, "drivers": []},
            (EvidenceRow("Forecast assumption", forecast.assumption),),
        )

    summary = (
        f"{_goal_name(ctx, outlook.goal_id)} has a {_percent(outlook.probability_bp)} chance "
        f"by {outlook.target_date.isoformat()}. {forecast.assumption}"
    )
    evidence = [
        EvidenceRow(
            f"{_goal_name(ctx, outlook.goal_id)} by {outlook.target_date.isoformat()}",
            _percent(outlook.probability_bp),
        )
    ]
    evidence.extend(
        EvidenceRow(
            _lever_label(driver.lever),
            f"{_percent(driver.probability_bp_before)} → {_percent(driver.probability_bp_after)}",
        )
        for driver in forecast.drivers
    )
    evidence.append(EvidenceRow("Forecast assumption", forecast.assumption))
    return ToolResult(
        {
            "summary": summary,
            "goal_id": outlook.goal_id,
            "target_date": outlook.target_date.isoformat(),
            "probability_bp": outlook.probability_bp,
            "median_shortfall_sen": outlook.median_shortfall.sen,
            "drivers": [_driver_value(driver) for driver in forecast.drivers],
        },
        tuple(evidence),
    )


SPECS = (
    ToolSpec(
        name="project_future",
        module=MODULE,
        kind="read",
        label="Projecting your next months",
        description=(
            "Project the user's balance and dated goals from confirmed spending history. "
            "Returns a median closing balance, goal probabilities, useful changes and "
            "its assumption."
        ),
        args_model=ProjectFutureArgs,
        handler=_project,
    ),
    ToolSpec(
        name="compare_scenarios",
        module=MODULE,
        kind="read",
        label="Comparing plan changes",
        description=(
            "Compare possible changes to goal saving, a commitment, or daily spending. "
            "This changes nothing and reports the probability each change buys."
        ),
        args_model=CompareScenariosArgs,
        handler=_compare,
    ),
    ToolSpec(
        name="explain_probability",
        module=MODULE,
        kind="read",
        label="Explaining a goal probability",
        description=(
            "Explain the forecast probability for a dated goal and the ranked changes that "
            "would move it. This is a projection, never a promise."
        ),
        args_model=ExplainProbabilityArgs,
        handler=_explain,
    ),
)
