"""The Butler owns conversation routing; the Goal graph owns planning truth."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from kira.agent.llm import route_for
from kira.agent.run import run_turn
from kira.db.models import ButlerApproval, ButlerMemory, Goal
from tests.agent.conftest import declining_factory, offline_factory


@pytest.mark.parametrize(
    ("subject", "expected_type"),
    [
        ("emergency starter fund", "emergency_starter_fund"),
        ("upcoming annual bill", "upcoming_bill_annual_expense"),
        ("travel", "travel"),
        ("big purchase", "big_purchase"),
        ("wedding event deposit", "wedding_event_deposit"),
        ("house down payment", "house_down_payment"),
        ("car down payment", "car_down_payment"),
        ("wedding fund", "wedding_fund"),
        ("full emergency fund", "full_emergency_fund"),
        ("education family goal", "education_family_goal"),
        ("custom goal", "custom_goal"),
    ],
)
def test_every_supported_goal_type_enters_the_typed_workflow(subject, expected_type):
    message = (
        f"I want RM1,000 for a {subject} by December 2026. "
        "I already saved RM200."
    )

    route = route_for(message)
    args = route.arguments(message, None)["start_goal_planning"]

    assert route.tools == ("start_goal_planning",)
    assert args["goal_type"] == expected_type


async def test_natural_goal_is_handed_to_goal_graph_without_third_llm_call(
    session, butler, today
):
    user, thread = butler

    result = await run_turn(
        session,
        user,
        thread,
        text=(
            "I want RM1,000 for a Penang trip by December 2026. "
            "I already saved RM200."
        ),
        today=today,
        model_factory=offline_factory,
    )

    assert result.tools_used == ["start_goal_planning"]
    assert result.llm_calls == 2
    assert result.approval is not None
    assert result.approval["tool"] == "apply_goal_plan_change"
    assert result.approval["before"] is None
    assert result.approval["after"]["target_amount_sen"] == 100_000
    assert "RM" in result.answer
    assert (await session.execute(select(Goal).where(Goal.name == "Travel"))).scalar_one()
    assert (await session.execute(select(ButlerMemory))).scalars().all() == []


async def test_goal_creation_still_opens_review_when_online_model_declines_tools(
    session, butler, today
):
    user, thread = butler

    result = await run_turn(
        session,
        user,
        thread,
        text=(
            "I want RM1,000 for a Penang trip by December 2026. "
            "I already saved RM200."
        ),
        today=today,
        model_factory=declining_factory("I can help you plan that."),
    )

    assert result.tools_used == ["start_goal_planning"]
    assert result.approval is not None
    assert result.approval["tool"] == "apply_goal_plan_change"
    assert result.approval["after"]["affordability_status"]
    assert result.approval["after"]["contribution_ratio_bp"] is not None


async def test_long_term_goal_reaches_the_same_approval_boundary_as_a_ledger_write(
    session, butler, today
):
    user, thread = butler

    result = await run_turn(
        session,
        user,
        thread,
        text="Set a 1 million savings goal as a long-term goal.",
        today=today,
        model_factory=offline_factory,
    )

    assert result.approval is not None
    assert result.approval["tool"] == "apply_goal_plan_change"
    assert result.approval["after"]["target_amount_sen"] == 100_000_000
    assert result.approval["after"]["current_saved_sen"] == 0
    assert result.approval["after"]["target_date"] == today.replace(year=today.year + 5).isoformat()
    assert "start_goal_planning" not in result.answer


async def test_part_time_request_in_butler_asks_for_missing_availability(
    session, butler, today
):
    user, thread = butler

    result = await run_turn(
        session,
        user,
        thread,
        text="Recommend part-time work to accelerate my wedding goal.",
        today=today,
        model_factory=declining_factory("Try freelancing."),
    )

    assert result.tools_used == ["recommend_part_time_jobs"]
    assert dict(result.evidence)["Goal"] == "Wedding"
    assert "hours" in result.answer.lower()
    assert "remote" in result.answer.lower()


async def test_incomplete_goal_request_clarifies_without_creating_a_draft(
    session, butler, today
):
    user, thread = butler

    result = await run_turn(
        session,
        user,
        thread,
        text="I want to save for a trip.",
        today=today,
        model_factory=offline_factory,
    )

    assert result.approval is None
    assert "target amount" in result.answer
    assert "target date" in result.answer
    assert (
        await session.execute(select(ButlerApproval).where(ButlerApproval.status == "pending"))
    ).scalars().all() == []
