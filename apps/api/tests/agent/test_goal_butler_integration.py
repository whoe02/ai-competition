"""The Butler owns conversation routing; the Goal graph owns planning truth."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from kira.agent.llm import route_for
from kira.agent.run import run_turn, stream_interrupted_turn
from kira.db.models import ROLE_KIRA, ROLE_USER, ButlerApproval, ButlerMemory, Goal
from kira.services import butler_thread
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


async def test_long_term_goal_asks_for_the_existing_saved_amount(
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

    assert result.approval is None
    assert "already saved" in result.answer
    assert "sen" not in result.answer.casefold()


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


async def test_a_completed_checkpoint_can_restore_an_answer_that_was_not_persisted(
    session, butler, today
):
    user, thread = butler
    message_id = uuid.uuid4()
    original = await run_turn(
        session,
        user,
        thread,
        text="Recommend part-time work to accelerate my wedding goal.",
        message_id=message_id,
        today=today,
        model_factory=declining_factory("Try freelancing."),
    )

    events = [
        event
        async for event in stream_interrupted_turn(
            session,
            user,
            thread,
            message_id=message_id,
            today=today,
            model_factory=declining_factory("Try freelancing."),
        )
    ]

    assert events[-1]["type"] == "done"
    assert events[-1]["answer"] == original.answer
    assert events[-1]["tools_used"] == ["recommend_part_time_jobs"]


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
    assert "already saved" in result.answer
    assert "target date" in result.answer
    assert (
        await session.execute(select(ButlerApproval).where(ButlerApproval.status == "pending"))
    ).scalars().all() == []


async def test_goal_follow_up_keeps_the_goal_identity_and_natural_rm_values(
    session, butler, today
):
    user, thread = butler

    first_text = "I want to create my car down payment goal."
    await butler_thread.append(session, user, thread, role=ROLE_USER, content=first_text)
    first = await run_turn(
        session, user, thread, text=first_text, today=today, model_factory=offline_factory
    )
    await butler_thread.append(session, user, thread, role=ROLE_KIRA, content=first.answer)

    follow_up = "Target is RM10,000, already saved RM5,000, target date is 4 March 2027."
    await butler_thread.append(session, user, thread, role=ROLE_USER, content=follow_up)
    result = await run_turn(
        session, user, thread, text=follow_up, today=today, model_factory=offline_factory
    )

    assert result.approval is not None
    assert result.approval["after"]["target_amount_sen"] == 1_000_000
    assert result.approval["after"]["current_saved_sen"] == 500_000
    assert result.approval["after"]["target_date"] == "2027-03-04"
