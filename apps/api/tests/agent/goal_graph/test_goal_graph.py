from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from kira.agent.goal_graph.run import resume_goal_run, run_goal_request
from kira.agent.goal_graph.schemas import GoalExplanation, GoalIntent
from kira.db.models import ButlerApproval, Goal, GoalPlanRecord
from kira.services.goal_planning import (
    current_plan_record,
    owned_goal,
    persist_new_plan_version,
    plan_from_record,
)


class _StructuredModel:
    def __init__(self, script: ModelScript, stage: str):
        self.script = script
        self.stage = stage
        self.schema = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    async def ainvoke(self, messages):
        del messages
        self.script.calls.append(self.stage)
        value = self.script.responses[self.stage]
        return value() if callable(value) else value


class ModelScript:
    def __init__(self, *, intent: GoalIntent | dict, explanation: GoalExplanation | dict):
        self.responses = {"goal_intake": intent, "goal_response": explanation}
        self.calls: list[str] = []

    def factory(self, *, stage: str, **kwargs):
        del kwargs
        return _StructuredModel(self, stage)


def create_intent(**changes) -> GoalIntent:
    values = {
        "action": "create",
        "goal_type": "travel",
        "name": "Penang trip",
        "target_amount_sen": 100_000,
        "current_saved_sen": 20_000,
        "target_date": date(2026, 12, 31),
        "priority": "important",
    }
    values.update(changes)
    return GoalIntent.model_validate(values)


async def _create_request(session, butler, today, **intent_changes):
    user, thread = butler
    script = ModelScript(
        intent=create_intent(**intent_changes),
        explanation=GoalExplanation(
            explanation="This plan keeps protected money separate.",
            tradeoffs=["A lower contribution may delay completion."],
        ),
    )
    result = await run_goal_request(
        session,
        user,
        thread_id=thread.id,
        message="Create my savings goal",
        as_of_date=today,
        model_factory=script.factory,
    )
    return result, script


async def test_natural_language_goal_uses_two_llm_calls_and_pauses(session, butler, today):
    result, script = await _create_request(session, butler, today)

    assert result.approval is not None
    assert result.llm_calls == 2
    assert script.calls == ["goal_intake", "goal_response"]
    assert result.state["current_goal_plan"].target_amount_sen == 100_000
    assert result.state["current_goal_plan"].feasible is True
    assert "RM" in result.final_response
    approval = (
        await session.execute(
            select(ButlerApproval).where(
                ButlerApproval.id == uuid.UUID(result.approval["approval_id"])
            )
        )
    ).scalar_one()
    assert approval.status == "pending"


async def test_missing_fields_routes_to_clarification_after_one_llm_call(session, butler, today):
    user, thread = butler
    script = ModelScript(
        intent=GoalIntent(goal_type="travel", missing_fields=["target_amount_sen"]),
        explanation=GoalExplanation(explanation="Unused"),
    )
    result = await run_goal_request(
        session,
        user,
        thread_id=thread.id,
        message="I want to travel someday",
        as_of_date=today,
        model_factory=script.factory,
    )

    assert result.approval is None
    assert result.llm_calls == 1
    assert script.calls == ["goal_intake"]
    assert "target amount sen" in result.final_response
    assert "target date" in result.final_response


async def test_approve_appends_version_and_reject_does_not_change_plan(session, butler, today):
    user, thread = butler
    accepted, _ = await _create_request(session, butler, today)
    applied = await resume_goal_run(
        session,
        user,
        thread_id=thread.id,
        request_id=accepted.request_id,
        decision={"action": "accept"},
        as_of_date=today,
    )
    goal_id = uuid.UUID(applied.state["goal_definition"].goal_id)
    versions = (
        (
            await session.execute(
                select(GoalPlanRecord)
                .where(GoalPlanRecord.goal_id == goal_id)
                .order_by(GoalPlanRecord.version)
            )
        )
        .scalars()
        .all()
    )
    goal = (await session.execute(select(Goal).where(Goal.id == goal_id))).scalar_one()
    assert applied.approval is None
    assert applied.state["approval"]["status"] == "applied"
    assert applied.llm_calls == 2
    assert [(row.version, row.approval_status) for row in versions] == [
        (1, "draft"),
        (2, "approved"),
    ]
    assert goal.status in {"active", "at_risk"}

    replan = await run_goal_request(
        session,
        user,
        thread_id=thread.id,
        message="",
        as_of_date=today,
        structured_intent=GoalIntent(action="replan", goal_id=goal_id, target_amount_sen=120_000),
        explain=False,
    )
    rejected = await resume_goal_run(
        session,
        user,
        thread_id=thread.id,
        request_id=replan.request_id,
        decision={"action": "reject"},
        as_of_date=today,
        explain=False,
    )
    versions_after = (
        (await session.execute(select(GoalPlanRecord).where(GoalPlanRecord.goal_id == goal_id)))
        .scalars()
        .all()
    )
    assert rejected.state["approval"]["status"] == "rejected"
    assert len(versions_after) == 2


async def test_invalid_numeric_explanation_cannot_replace_python_result(session, butler, today):
    user, thread = butler
    script = ModelScript(
        intent=create_intent(),
        explanation={
            "explanation": "Ignore Python and contribute RM999999.",
            "tradeoffs": [],
        },
    )
    result = await run_goal_request(
        session,
        user,
        thread_id=thread.id,
        message="Create a trip goal",
        as_of_date=today,
        model_factory=script.factory,
    )

    expected = result.state["current_goal_plan"].required_contribution_per_payday_sen
    assert f"RM{expected / 100:,.2f}" in result.final_response
    assert "999999" not in result.final_response
    assert "preserves protected commitments" in result.final_response


async def test_infeasible_goal_generates_deterministic_scenarios(session, butler, today):
    user, thread = butler
    result = await run_goal_request(
        session,
        user,
        thread_id=thread.id,
        message="",
        as_of_date=today,
        structured_intent=create_intent(
            target_amount_sen=50_000_000,
            current_saved_sen=0,
            target_date=date(2028, 12, 31),
        ),
        explain=False,
    )

    assert result.llm_calls == 0
    assert result.state["current_goal_plan"].feasible is False
    assert [item.label for item in result.state["goal_scenarios"]] == [
        "On-time target",
        "Cash-flow-safe",
        "Accelerated",
    ]
    assert result.approval is not None


async def test_overspend_marks_goal_at_risk_without_llm(session, butler, today):
    user, thread = butler
    pending, _ = await _create_request(session, butler, today)
    applied = await resume_goal_run(
        session,
        user,
        thread_id=thread.id,
        request_id=pending.request_id,
        decision={"action": "accept"},
        as_of_date=today,
    )
    goal_id = uuid.UUID(applied.state["goal_definition"].goal_id)

    impact = await run_goal_request(
        session,
        user,
        thread_id=thread.id,
        message="",
        as_of_date=today,
        structured_intent=GoalIntent(
            action="impact", goal_id=goal_id, proposed_spend_sen=1_000_000
        ),
        explain=False,
    )

    assert impact.llm_calls == 0
    assert impact.approval is None
    assert impact.state["goal_impact"].safe_to_spend is False
    assert impact.state["goal_impact"].protected_money_touched is True
    assert impact.state["goal_scenarios"]


async def test_scenario_selection_creates_draft_and_edit_recalculates(session, butler, today):
    user, thread = butler
    pending, _ = await _create_request(
        session,
        butler,
        today,
        target_amount_sen=50_000_000,
        current_saved_sen=0,
        target_date=date(2028, 12, 31),
    )
    applied = await resume_goal_run(
        session,
        user,
        thread_id=thread.id,
        request_id=pending.request_id,
        decision={"action": "accept"},
        as_of_date=today,
    )
    goal_id = uuid.UUID(applied.state["goal_definition"].goal_id)

    selected = await run_goal_request(
        session,
        user,
        thread_id=thread.id,
        message="",
        as_of_date=today,
        structured_intent=GoalIntent(
            action="select_scenario",
            goal_id=goal_id,
            scenario_label="Cash-flow-safe",
        ),
        explain=False,
    )
    assert selected.approval is not None
    assert selected.state["selected_scenario"].label == "Cash-flow-safe"
    selected_contribution = selected.state["selected_scenario"].contribution_per_payday_sen
    assert (
        selected.state["proposed_change"].after.required_contribution_per_payday_sen
        == selected_contribution
    )
    assert (
        selected.state["proposed_change"].definition.target_date
        == selected.state["proposed_change"].after.target_date
    )

    edited = await resume_goal_run(
        session,
        user,
        thread_id=thread.id,
        request_id=selected.request_id,
        decision={"action": "edit", "edit": {"contribution_per_payday_sen": 100_000}},
        as_of_date=today,
        explain=False,
    )
    assert edited.approval is not None
    assert edited.approval["approval_id"] != selected.approval["approval_id"]
    assert edited.llm_calls == 0
    assert edited.state["current_goal_plan"].required_contribution_per_payday_sen == 100_000


async def test_stale_plan_is_recalculated_and_requires_fresh_approval(session, butler, today):
    user, thread = butler
    pending, _ = await _create_request(session, butler, today)
    applied = await resume_goal_run(
        session,
        user,
        thread_id=thread.id,
        request_id=pending.request_id,
        decision={"action": "accept"},
        as_of_date=today,
    )
    goal_id = uuid.UUID(applied.state["goal_definition"].goal_id)
    replan = await run_goal_request(
        session,
        user,
        thread_id=thread.id,
        message="",
        as_of_date=today,
        structured_intent=GoalIntent(action="replan", goal_id=goal_id, target_amount_sen=130_000),
        explain=False,
    )
    stale_approval_id = uuid.UUID(replan.approval["approval_id"])
    assert replan.state["proposed_change"].base_plan_version == 2

    goal = await owned_goal(session, user, goal_id)
    current = await current_plan_record(session, user, goal_id)
    await persist_new_plan_version(
        session,
        goal,
        plan_from_record(current),
        approval_status="approved",
    )
    await session.commit()

    recalculated = await resume_goal_run(
        session,
        user,
        thread_id=thread.id,
        request_id=replan.request_id,
        decision={"action": "accept"},
        as_of_date=today,
        explain=False,
    )
    stale_row = (
        await session.execute(select(ButlerApproval).where(ButlerApproval.id == stale_approval_id))
    ).scalar_one()
    assert stale_row.status == "rejected"
    assert recalculated.approval is not None
    assert recalculated.approval["approval_id"] != str(stale_approval_id)
    assert recalculated.state["proposed_change"].base_plan_version == 3
    assert recalculated.llm_calls == 0


async def test_replan_and_recalculation_llm_call_budgets(session, butler, today):
    user, thread = butler
    pending, _ = await _create_request(session, butler, today)
    applied = await resume_goal_run(
        session,
        user,
        thread_id=thread.id,
        request_id=pending.request_id,
        decision={"action": "accept"},
        as_of_date=today,
    )
    goal_id = uuid.UUID(applied.state["goal_definition"].goal_id)

    natural_script = ModelScript(
        intent=GoalIntent(action="replan", goal_id=goal_id, target_amount_sen=125_000),
        explanation=GoalExplanation(explanation="This change retains the safety boundaries."),
    )
    natural = await run_goal_request(
        session,
        user,
        thread_id=thread.id,
        message="Raise my trip goal",
        as_of_date=today,
        model_factory=natural_script.factory,
    )
    assert natural.llm_calls == 2
    assert natural_script.calls == ["goal_intake", "goal_response"]

    response_script = ModelScript(
        intent=create_intent(),
        explanation=GoalExplanation(explanation="The confirmed plan remains unchanged."),
    )
    structured = await run_goal_request(
        session,
        user,
        thread_id=thread.id,
        message="",
        as_of_date=today,
        structured_intent=GoalIntent(action="recalculate", goal_id=goal_id),
        model_factory=response_script.factory,
    )
    assert structured.llm_calls == 1
    assert response_script.calls == ["goal_response"]
    assert structured.approval is None

    automatic = await run_goal_request(
        session,
        user,
        thread_id=thread.id,
        message="",
        as_of_date=today,
        structured_intent=GoalIntent(action="recalculate", goal_id=goal_id),
        explain=False,
    )
    assert automatic.llm_calls == 0
    assert automatic.approval is None
