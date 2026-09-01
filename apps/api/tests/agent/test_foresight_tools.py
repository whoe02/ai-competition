"""The forecast, reachable by the agent — and only readable."""

import pytest

from kira.agent.tools import REGISTRY, ToolContext
from kira.seed.demo import DEMO_TODAY, seed_demo_user
from kira.services.dashboard import today_dashboard
from kira.services.snapshot import load_snapshot

TOOL_NAMES = ("project_future", "compare_scenarios", "explain_probability")


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_the_tool_is_registered(name):
    assert REGISTRY.get(name) is not None


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_the_tool_is_a_read(name):
    assert REGISTRY.get(name).kind == "read"


async def context(session, user) -> ToolContext:
    return ToolContext(
        session=session,
        user=user,
        today=DEMO_TODAY,
        snapshot=await load_snapshot(session, user, DEMO_TODAY),
        dashboard=await today_dashboard(session, user, DEMO_TODAY),
    )


async def test_project_future_returns_evidence_a_person_can_check(session):
    user = await seed_demo_user(session)
    await session.flush()
    spec = REGISTRY.get("project_future")

    result = await spec.handler(
        await context(session, user), spec.args_model.model_validate({"horizon_days": 90})
    )

    assert result.evidence, "an answer without evidence is a guess"
    labels = " ".join(row.label for row in result.evidence).lower()
    assert "90" in labels or "probability" in labels


async def test_compare_scenarios_reports_what_each_change_buys(session):
    user = await seed_demo_user(session)
    await session.flush()
    ctx = await context(session, user)
    spec = REGISTRY.get("compare_scenarios")

    result = await spec.handler(
        ctx,
        spec.args_model.model_validate(
            {
                "horizon_days": 180,
                "levers": [
                    {
                        "kind": "goal_monthly",
                        "target_id": ctx.snapshot.goals[0].id,
                        "delta_sen": 5000,
                    }
                ],
            }
        ),
    )

    assert len(result.value["results"]) == 1
    assert "→" in result.evidence[0].value


async def test_explain_probability_states_its_assumption(session):
    user = await seed_demo_user(session)
    await session.flush()
    spec = REGISTRY.get("explain_probability")

    result = await spec.handler(await context(session, user), spec.args_model())

    assert "not a promise" in result.value["summary"].lower()


async def test_a_goal_change_from_the_plan_still_stops_at_approval(session, butler, today):
    """The Plan never writes: its plain-language handoff reaches the usual boundary."""
    from kira.agent.run import run_turn

    user, thread = butler
    result = await run_turn(
        session,
        user,
        thread,
        text=(
            "Please replan my Emergency top-up goal with target date December 2026 "
            "using the latest forecast. "
            "Calculate safe deterministic options and ask for approval before changing it."
        ),
        today=today,
    )

    assert result.approval is not None
    assert result.approval["tool"] == "apply_goal_plan_change"
    assert result.approval["after"]["required_contribution_per_payday_sen"] > 0
