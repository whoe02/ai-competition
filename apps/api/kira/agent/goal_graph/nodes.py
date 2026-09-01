"""Goal graph nodes. Only intake and composition call a chat model."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, replace
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import ValidationError
from sqlalchemy import select

from kira import engine as finance_engine
from kira.agent.goal_graph.prompts import GOAL_INTAKE_PROMPT, GOAL_RESPONSE_PROMPT
from kira.agent.goal_graph.schemas import (
    ApprovalDecision,
    GoalDataQuality,
    GoalExplanation,
    GoalIntent,
    PlanEdit,
)
from kira.agent.goal_graph.state import (
    GoalGraphContext,
    GoalGraphState,
    PlanChangeDraft,
)
from kira.agent.llm import get_chat_model
from kira.db.models import Goal
from kira.engine import (
    GOAL_TYPES,
    GoalDefinition,
    calculate_goal_feasibility,
    calculate_goal_plan_for_contribution,
    validate_goal_definition,
)
from kira.money import Money
from kira.services import butler_approvals
from kira.services.audit import ACTOR_BUTLER, ACTOR_USER, record
from kira.services.goal_planning import (
    GoalNotFound,
    StalePlanVersion,
    apply_approved_plan_change,
    create_draft_goal,
    current_plan_record,
    definition_from_record,
    owned_goal,
    plan_from_record,
)
from kira.services.goal_planning import (
    load_financial_snapshot as load_snapshot_service,
)

_CANONICAL_NAMES = {
    "emergency_starter_fund": "Emergency starter fund",
    "upcoming_bill_annual_expense": "Upcoming bill or annual expense",
    "travel": "Travel",
    "big_purchase": "Big purchase",
    "wedding_event_deposit": "Wedding or event deposit",
    "house_down_payment": "House down payment",
    "car_down_payment": "Car down payment",
    "wedding_fund": "Wedding fund",
    "full_emergency_fund": "Full emergency fund",
    "education_family_goal": "Education or family goal",
    "custom_goal": "Custom goal",
}


def _model(runtime: Runtime[GoalGraphContext], stage: str):
    factory = runtime.context.model_factory
    if factory is not None:
        return factory(stage=stage, streaming=False)
    return get_chat_model(streaming=False)


def _normalise_intent(intent: GoalIntent) -> GoalIntent:
    missing = set(intent.missing_fields)
    if intent.action == "create":
        for field in (
            "goal_type",
            "target_amount_sen",
            "current_saved_sen",
            "target_date",
        ):
            if getattr(intent, field) is None:
                missing.add(field)
    elif intent.action in {"replan", "impact", "select_scenario", "recalculate"}:
        if intent.goal_id is None and not intent.goal_reference:
            missing.add("goal_reference")
    if intent.action == "impact" and intent.proposed_spend_sen is None:
        missing.add("proposed_spend_sen")
    if (
        intent.action == "select_scenario"
        and intent.scenario_id is None
        and not intent.scenario_label
    ):
        missing.add("scenario_id_or_label")
    return intent.model_copy(update={"missing_fields": sorted(missing)})


async def goal_intake(state: GoalGraphState, runtime: Runtime[GoalGraphContext]) -> dict[str, Any]:
    """LLM call #1, skipped when a form/trigger already supplied structure."""
    structured = runtime.context.structured_intent
    if structured is not None:
        try:
            intent = (
                structured
                if isinstance(structured, GoalIntent)
                else GoalIntent.model_validate(structured)
            )
        except ValidationError as exc:
            return {"errors": [f"invalid structured intent: {exc}"]}
        return {"goal_intent": _normalise_intent(intent)}

    model = _model(runtime, "goal_intake").with_structured_output(GoalIntent)
    try:
        result = await model.ainvoke(
            [
                SystemMessage(content=GOAL_INTAKE_PROMPT),
                HumanMessage(content=state.get("user_message", "")),
            ]
        )
        intent = result if isinstance(result, GoalIntent) else GoalIntent.model_validate(result)
    except Exception as exc:
        return {
            "errors": [f"goal intake failed: {exc}"],
            "llm_calls": state.get("llm_calls", 0) + 1,
        }
    return {
        "goal_intent": _normalise_intent(intent),
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def _reference_words(value: str) -> set[str]:
    ignored = {"a", "an", "the", "my", "goal", "fund", "savings", "for"}
    return {
        word
        for word in "".join(character if character.isalnum() else " " for character in value)
        .casefold()
        .split()
        if word not in ignored
    }


async def resolve_goal_target(
    state: GoalGraphState, runtime: Runtime[GoalGraphContext]
) -> dict[str, Any]:
    """Resolve a human goal name to an owned UUID without asking the model to invent one."""
    intent = state.get("goal_intent")
    if intent is None or intent.action == "create" or intent.goal_id is not None:
        return {}
    reference = (intent.goal_reference or "").strip()
    goals = (
        (
            await runtime.context.session.execute(
                select(Goal)
                .where(
                    Goal.user_id == runtime.context.user.id,
                    Goal.status.in_(
                        ("active", "at_risk", "needs_replan", "paused", "achieved")
                    ),
                )
                .order_by(Goal.created_at, Goal.id)
            )
        )
        .scalars()
        .all()
    )
    if not goals:
        return {"errors": ["you do not have a goal to update yet"]}

    reference_folded = reference.casefold()
    exact = [goal for goal in goals if goal.name.casefold() == reference_folded]
    if not exact:
        wanted = _reference_words(reference)
        scored: list[tuple[int, Goal]] = []
        for goal in goals:
            searchable = f"{goal.name} {_CANONICAL_NAMES.get(goal.goal_type, goal.goal_type)}"
            score = len(wanted & _reference_words(searchable))
            if score:
                scored.append((score, goal))
        best = max((score for score, _ in scored), default=0)
        exact = [goal for score, goal in scored if score == best]
    if not reference and len(goals) == 1:
        exact = [goals[0]]
    if len(exact) == 1:
        resolved = intent.model_copy(
            update={
                "goal_id": exact[0].id,
                "goal_reference": exact[0].name,
                "missing_fields": [
                    field for field in intent.missing_fields if field != "goal_reference"
                ],
            }
        )
        return {"goal_intent": resolved}
    if len(exact) > 1:
        names = ", ".join(goal.name for goal in exact)
        return {"errors": [f"more than one goal matches '{reference}': {names}"]}
    return {"errors": [f"I could not find a goal matching '{reference}'"]}


def _definition_for_existing(goal: Goal, intent: GoalIntent) -> GoalDefinition:
    """Read a versioned goal, or safely upgrade a legacy row during replanning."""
    if goal.target_date is not None:
        return definition_from_record(goal)
    if intent.target_date is None:
        raise ValueError(f"{goal.name} needs a target date before it can be planned")
    return GoalDefinition(
        goal_id=str(goal.id),
        user_id=str(goal.user_id),
        goal_type=intent.goal_type or goal.goal_type,
        name=intent.name or goal.name,
        currency=goal.currency,
        target_amount_sen=intent.target_amount_sen or goal.target.sen,
        current_saved_sen=(
            intent.current_saved_sen
            if intent.current_saved_sen is not None
            else goal.saved.sen
        ),
        target_date=intent.target_date,
        priority=intent.priority or goal.priority,
        status=goal.status,
        funding_account_ids=tuple(goal.funding_account_ids),
    )


async def goal_policy_guard(
    state: GoalGraphState, runtime: Runtime[GoalGraphContext]
) -> dict[str, Any]:
    intent = state.get("goal_intent")
    if intent is None:
        return {"errors": [*(state.get("errors") or []), "no goal intent"]}
    if intent.missing_fields:
        return {}
    if intent.goal_type is not None and intent.goal_type not in GOAL_TYPES:
        return {"errors": [f"unsupported goal type: {intent.goal_type}"]}

    context = runtime.context
    if intent.action == "create":
        goal_type = str(intent.goal_type)
        goal_id = uuid.uuid5(uuid.NAMESPACE_URL, f"kira-goal:{state['request_id']}")
        definition = GoalDefinition(
            goal_id=str(goal_id),
            user_id=str(context.user.id),
            goal_type=goal_type,
            name=(intent.name or _CANONICAL_NAMES[goal_type]).strip(),
            currency=context.user.currency,
            target_amount_sen=int(intent.target_amount_sen),
            current_saved_sen=int(intent.current_saved_sen),
            target_date=intent.target_date,
            priority=intent.priority or "flexible",
            status="draft",
            funding_account_ids=tuple(str(value) for value in intent.funding_account_ids),
        )
        try:
            validate_goal_definition(definition, as_of_date=context.as_of_utc.date())
        except (TypeError, ValueError) as exc:
            return {"errors": [str(exc)]}
        return {"goal_definition": definition, "current_plan_version": 0}

    try:
        goal = await owned_goal(context.session, context.user, intent.goal_id)
        definition = _definition_for_existing(goal, intent)
    except (GoalNotFound, ValueError) as exc:
        return {"errors": [str(exc)]}
    definition = replace(
        definition,
        goal_type=intent.goal_type or definition.goal_type,
        name=intent.name or definition.name,
        target_amount_sen=intent.target_amount_sen or definition.target_amount_sen,
        current_saved_sen=(
            intent.current_saved_sen
            if intent.current_saved_sen is not None
            else definition.current_saved_sen
        ),
        target_date=intent.target_date or definition.target_date,
        priority=intent.priority or definition.priority,
        funding_account_ids=(
            tuple(str(value) for value in intent.funding_account_ids)
            if intent.funding_account_ids
            else definition.funding_account_ids
        ),
    )
    try:
        validate_goal_definition(definition, as_of_date=context.as_of_utc.date())
    except (TypeError, ValueError) as exc:
        return {"errors": [str(exc)]}
    updates: dict[str, Any] = {
        "goal_definition": definition,
        "base_goal_definition": (
            definition_from_record(goal) if goal.target_date is not None else None
        ),
    }
    try:
        record_ = await current_plan_record(context.session, context.user, intent.goal_id)
    except GoalNotFound:
        updates["current_plan_version"] = 0
    else:
        updates["base_goal_plan"] = plan_from_record(record_)
        updates["current_plan_version"] = record_.version
    return updates


async def load_financial_snapshot(
    state: GoalGraphState, runtime: Runtime[GoalGraphContext]
) -> dict[str, Any]:
    snapshot = await load_snapshot_service(
        runtime.context.session, runtime.context.user, runtime.context.as_of_utc
    )
    updates: dict[str, Any] = {
        "financial_snapshot": snapshot,
        "evidence_refs": snapshot.evidence_refs,
    }
    definition = state.get("goal_definition")
    if definition is not None:
        try:
            record_ = await current_plan_record(
                runtime.context.session,
                runtime.context.user,
                uuid.UUID(definition.goal_id),
            )
        except GoalNotFound:
            pass
        else:
            updates["base_goal_plan"] = plan_from_record(record_)
            updates["current_plan_version"] = record_.version
    return updates


async def goal_data_quality_gate(
    state: GoalGraphState, runtime: Runtime[GoalGraphContext]
) -> dict[str, Any]:
    del runtime
    snapshot = state.get("financial_snapshot")
    if snapshot is None:
        return {"data_quality": GoalDataQuality(status="blocked", issues=["snapshot unavailable"])}
    issues: list[str] = []
    if not snapshot.accounts:
        issues.append("no confirmed account balance")
    if snapshot.next_income_payday.amount_sen is None:
        issues.append("confirmed income amount unavailable")
    definition = state.get("goal_definition")
    available_account_ids = {account.account_id for account in snapshot.accounts}
    unknown_funding_accounts = (
        set(definition.funding_account_ids) - available_account_ids
        if definition is not None
        else set()
    )
    if unknown_funding_accounts:
        issues.append("one or more funding accounts are unavailable")
    status = "ready" if not issues else "limited"
    if (snapshot.data_confidence == "low" and not snapshot.accounts) or (unknown_funding_accounts):
        status = "blocked"
    updates: dict[str, Any] = {"data_quality": GoalDataQuality(status=status, issues=issues)}
    if unknown_funding_accounts:
        updates["errors"] = [
            *(state.get("errors") or []),
            "one or more funding accounts are unavailable",
        ]
    return updates


async def solve_goal_baseline(
    state: GoalGraphState, runtime: Runtime[GoalGraphContext]
) -> dict[str, Any]:
    del runtime
    definition = state.get("goal_definition")
    snapshot = state.get("financial_snapshot")
    if definition is None or snapshot is None:
        return {"errors": [*(state.get("errors") or []), "solver inputs unavailable"]}
    intent = state.get("goal_intent")
    override = state.get("override_contribution_sen") or (
        intent.contribution_per_payday_sen if intent is not None else None
    )
    plan = (
        calculate_goal_plan_for_contribution(definition, snapshot, override)
        if override is not None
        else calculate_goal_feasibility(definition, snapshot)
    )
    return {"current_goal_plan": plan}


async def reconcile_short_term_cashflow(
    state: GoalGraphState, runtime: Runtime[GoalGraphContext]
) -> dict[str, Any]:
    del runtime
    snapshot = state.get("financial_snapshot")
    plan = state.get("current_goal_plan")
    if snapshot is None or plan is None:
        return {"errors": [*(state.get("errors") or []), "reconciliation inputs unavailable"]}
    return {
        "reconciliation": finance_engine.reconcile_goal_with_short_term_cashflow(snapshot, plan)
    }


async def evaluate_goal_impact(
    state: GoalGraphState, runtime: Runtime[GoalGraphContext]
) -> dict[str, Any]:
    del runtime
    intent = state.get("goal_intent")
    snapshot = state.get("financial_snapshot")
    plan = state.get("base_goal_plan") or state.get("current_goal_plan")
    if intent is None or intent.proposed_spend_sen is None or snapshot is None or plan is None:
        return {"errors": [*(state.get("errors") or []), "impact inputs unavailable"]}
    return {
        "goal_impact": finance_engine.evaluate_goal_impact(
            intent.proposed_spend_sen, snapshot, plan
        )
    }


async def generate_goal_scenarios(
    state: GoalGraphState, runtime: Runtime[GoalGraphContext]
) -> dict[str, Any]:
    del runtime
    intent = state.get("goal_intent")
    definition = state.get("goal_definition")
    snapshot = state.get("financial_snapshot")
    if intent is None or definition is None or snapshot is None:
        return {"errors": [*(state.get("errors") or []), "scenario inputs unavailable"]}
    scenarios = finance_engine.generate_goal_scenarios(definition, snapshot)
    selected = None
    for scenario in scenarios:
        if intent.scenario_id is not None and scenario.scenario_id == str(intent.scenario_id):
            selected = scenario
        elif (
            intent.scenario_label and scenario.label.casefold() == intent.scenario_label.casefold()
        ):
            selected = scenario
    updates: dict[str, Any] = {"goal_scenarios": scenarios, "selected_scenario": selected}
    if intent.action == "select_scenario" and selected is None:
        updates["errors"] = ["selected scenario was not found"]
    elif selected is not None:
        plan = calculate_goal_plan_for_contribution(
            definition,
            snapshot,
            selected.contribution_per_payday_sen,
            target_date=selected.target_date,
        )
        updates["current_goal_plan"] = plan
        updates["goal_definition"] = replace(definition, target_date=selected.target_date)
        updates["reconciliation"] = finance_engine.reconcile_goal_with_short_term_cashflow(
            snapshot, plan
        )
        updates["override_contribution_sen"] = selected.contribution_per_payday_sen
    return updates


def _rm(sen: int) -> str:
    return f"RM{Money(sen).ringgit_str()}"


def _deterministic_answer(state: GoalGraphState) -> str:
    impact = state.get("goal_impact")
    if impact is not None:
        safety = "does not fit safely" if not impact.safe_to_spend else "fits safely"
        completion = (
            impact.projected_completion_date.isoformat()
            if impact.projected_completion_date
            else "unknown"
        )
        return (
            f"A {_rm(impact.proposed_spend_sen)} purchase {safety}; the projected "
            f"goal completion date is {completion}."
        )
    plan = state.get("current_goal_plan")
    if plan is None:
        return "I could not calculate a goal plan from the available confirmed data."
    feasibility = "feasible" if plan.feasible else "not feasible from confirmed cash flow"
    completion = (
        plan.projected_completion_date.isoformat() if plan.projected_completion_date else "unknown"
    )
    return (
        f"Set aside {_rm(plan.required_contribution_per_payday_sen)} per payday; "
        f"the plan is {feasibility} and projects completion on {completion}."
    )


async def compose_goal_response(
    state: GoalGraphState, runtime: Runtime[GoalGraphContext]
) -> dict[str, Any]:
    lead = _deterministic_answer(state)
    if not runtime.context.explain:
        return {"final_response": lead}
    payload = {
        "plan": asdict(state["current_goal_plan"]) if state.get("current_goal_plan") else None,
        "scenarios": [asdict(item) for item in state.get("goal_scenarios", ())],
        "reconciliation": asdict(state["reconciliation"]) if state.get("reconciliation") else None,
        "impact": asdict(state["goal_impact"]) if state.get("goal_impact") else None,
        "data_quality": state["data_quality"].model_dump() if state.get("data_quality") else None,
    }
    model = _model(runtime, "goal_response").with_structured_output(GoalExplanation)
    calls = state.get("llm_calls", 0) + 1
    try:
        result = await model.ainvoke(
            [
                SystemMessage(content=GOAL_RESPONSE_PROMPT),
                HumanMessage(content=json.dumps(payload, default=str, sort_keys=True)),
            ]
        )
        explanation = (
            result
            if isinstance(result, GoalExplanation)
            else GoalExplanation.model_validate(result)
        )
        prose = explanation.explanation
        if explanation.tradeoffs:
            prose += " " + " ".join(explanation.tradeoffs)
    except Exception:
        prose = "The calculation preserves protected commitments and the emergency buffer."
    return {"final_response": f"{lead}\n\n{prose}", "llm_calls": calls}


async def clarification_response(
    state: GoalGraphState, runtime: Runtime[GoalGraphContext]
) -> dict[str, Any]:
    del runtime
    intent = state.get("goal_intent")
    missing = intent.missing_fields if intent is not None else []
    errors = state.get("errors") or []
    if missing:
        readable = ", ".join(field.replace("_", " ") for field in missing)
        answer = f"I need {readable} before I can calculate this goal."
    else:
        answer = "I could not safely prepare this goal: " + "; ".join(errors)
    return {"final_response": answer}


def _plan_changed(state: GoalGraphState) -> bool:
    intent = state.get("goal_intent")
    after = state.get("current_goal_plan")
    if intent is None or after is None or intent.action == "impact":
        return False
    before = state.get("base_goal_plan")
    before_definition = state.get("base_goal_definition")
    if intent.action == "create" or before is None:
        return True
    plan_changed = (
        before.target_amount_sen,
        before.current_saved_sen,
        before.target_date,
        before.required_contribution_per_payday_sen,
    ) != (
        after.target_amount_sen,
        after.current_saved_sen,
        after.target_date,
        after.required_contribution_per_payday_sen,
    )
    if before_definition is None:
        return plan_changed
    after_definition = state.get("goal_definition")
    definition_changed = after_definition is not None and (
        before_definition.goal_type,
        before_definition.name,
        before_definition.priority,
        before_definition.funding_account_ids,
    ) != (
        after_definition.goal_type,
        after_definition.name,
        after_definition.priority,
        after_definition.funding_account_ids,
    )
    return plan_changed or definition_changed


async def create_plan_change_draft(
    state: GoalGraphState, runtime: Runtime[GoalGraphContext]
) -> dict[str, Any]:
    definition = state.get("goal_definition")
    plan = state.get("current_goal_plan")
    intent = state.get("goal_intent")
    if definition is None or plan is None or intent is None:
        return {"errors": [*(state.get("errors") or []), "plan draft inputs unavailable"]}
    base_version = state.get("current_plan_version", 0)
    if intent.action == "create":
        try:
            existing = await owned_goal(
                runtime.context.session, runtime.context.user, uuid.UUID(definition.goal_id)
            )
        except GoalNotFound:
            _, record_ = await create_draft_goal(
                runtime.context.session,
                runtime.context.user,
                goal_type=definition.goal_type,
                name=definition.name,
                target_amount_sen=definition.target_amount_sen,
                current_saved_sen=definition.current_saved_sen,
                target_date=definition.target_date,
                priority=definition.priority,
                funding_account_ids=tuple(
                    uuid.UUID(value) for value in definition.funding_account_ids
                ),
                as_of_utc=runtime.context.as_of_utc,
                goal_id=uuid.UUID(definition.goal_id),
            )
        else:
            record_ = await current_plan_record(
                runtime.context.session, runtime.context.user, existing.id
            )
        base_version = record_.version
    reason = (
        "Create and activate this goal plan"
        if intent.action == "create"
        else "Change the active goal plan"
    )
    draft = PlanChangeDraft(
        request_id=state["request_id"],
        goal_id=definition.goal_id,
        base_plan_version=base_version,
        before=state.get("base_goal_plan"),
        after=plan,
        definition=definition,
        reason=reason,
    )
    return {"proposed_change": draft, "current_plan_version": base_version}


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _approval_summary(draft: PlanChangeDraft) -> str:
    before = (
        "no active plan"
        if draft.before is None
        else (
            f"{_rm(draft.before.required_contribution_per_payday_sen)} per payday, "
            f"target {draft.before.target_date}"
        )
    )
    after = (
        f"{_rm(draft.after.required_contribution_per_payday_sen)} per payday, "
        f"target {draft.after.target_date}"
    )
    return f"Goal plan change — before: {before}; after: {after}."


async def approval_interrupt(
    state: GoalGraphState,
    runtime: Runtime[GoalGraphContext],
    config: RunnableConfig,
) -> dict[str, Any]:
    draft = state.get("proposed_change")
    if draft is None:
        return {"resume_action": "none"}
    graph_thread = str(config.get("configurable", {}).get("thread_id", ""))
    args = _jsonable(
        {
            "goal_id": draft.goal_id,
            "base_plan_version": draft.base_plan_version,
            "before": asdict(draft.before) if draft.before else None,
            "after": asdict(draft.after),
            "definition": asdict(draft.definition),
        }
    )
    args_digest = hashlib.sha256(
        json.dumps(args, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:20]
    approval_round = state.get("approval_round", 0)
    call_key = f"goal-plan:{draft.base_plan_version}:{approval_round}:{args_digest}"
    row = await butler_approvals.propose(
        runtime.context.session,
        runtime.context.user,
        thread_id=runtime.context.thread_id,
        tool="apply_goal_plan_change",
        args=args,
        summary=_approval_summary(draft),
        evidence=[["Evidence reference", value] for value in state.get("evidence_refs", ())],
        graph_thread_id=graph_thread,
        tool_call_id=call_key,
    )
    raw = interrupt(
        {
            "approval_id": str(row.id),
            "tool": "apply_goal_plan_change",
            "summary": row.summary,
            "base_plan_version": draft.base_plan_version,
            "before": args["before"],
            "after": args["after"],
        }
    ) or {"action": "reject"}
    try:
        decision = ApprovalDecision.model_validate(
            {"action": raw.get("action", "reject"), "edit": raw.get("edit") or raw.get("args")}
        )
    except ValidationError as exc:
        await butler_approvals.settle(
            runtime.context.session,
            row,
            applied=False,
            summary=row.summary + " Rejected because the decision was invalid.",
        )
        return {"errors": [f"invalid approval decision: {exc}"], "resume_action": "reject"}

    if decision.action == "reject":
        await butler_approvals.settle(runtime.context.session, row, applied=False)
        intent = state.get("goal_intent")
        if intent is not None and intent.action == "create":
            goal = await owned_goal(
                runtime.context.session,
                runtime.context.user,
                uuid.UUID(draft.goal_id),
            )
            if goal.status == "draft":
                goal.status = "cancelled"
        return {
            "approval": {"id": str(row.id), "status": "rejected"},
            "resume_action": "reject",
            "proposed_change": None,
        }
    if decision.action == "edit":
        edit = decision.edit or PlanEdit()
        definition = replace(
            draft.definition,
            target_amount_sen=edit.target_amount_sen or draft.definition.target_amount_sen,
            current_saved_sen=(
                edit.current_saved_sen
                if edit.current_saved_sen is not None
                else draft.definition.current_saved_sen
            ),
            target_date=edit.target_date or draft.definition.target_date,
            priority=edit.priority or draft.definition.priority,
        )
        await butler_approvals.settle(
            runtime.context.session,
            row,
            applied=False,
            summary=row.summary + " Replaced by an edited draft.",
        )
        return {
            "goal_definition": definition,
            "override_contribution_sen": edit.contribution_per_payday_sen,
            "approval": {"id": str(row.id), "status": "edited"},
            "resume_action": "edit",
            "proposed_change": None,
            "selected_scenario": None,
            "approval_round": approval_round + 1,
        }
    return {
        "approval": {"id": str(row.id), "status": "accepted"},
        "resume_action": "accept",
    }


async def apply_goal_plan(
    state: GoalGraphState, runtime: Runtime[GoalGraphContext]
) -> dict[str, Any]:
    draft = state.get("proposed_change")
    approval = state.get("approval") or {}
    if draft is None:
        return {"errors": [*(state.get("errors") or []), "no approved plan draft"]}
    row = await butler_approvals.get(
        runtime.context.session, runtime.context.user, uuid.UUID(approval["id"])
    )
    try:
        plan_record = await apply_approved_plan_change(
            runtime.context.session,
            runtime.context.user,
            definition=draft.definition,
            plan=draft.after,
            base_plan_version=draft.base_plan_version,
            as_of_utc=runtime.context.as_of_utc,
        )
    except StalePlanVersion as exc:
        await butler_approvals.settle(
            runtime.context.session,
            row,
            applied=False,
            summary=row.summary + " Rejected because the base version was stale.",
        )
        await record(
            runtime.context.session,
            runtime.context.user,
            actor=ACTOR_BUTLER,
            action="goal.plan.stale",
            detail={"request_id": state["request_id"], "reason": str(exc)},
        )
        return {
            "approval": {"id": str(row.id), "status": "stale"},
            "resume_action": "stale",
            "proposed_change": None,
            "errors": [],
            "approval_round": state.get("approval_round", 0) + 1,
        }
    event = await record(
        runtime.context.session,
        runtime.context.user,
        actor=ACTOR_USER,
        action="goal.plan.approved",
        detail={
            "request_id": state["request_id"],
            "goal_id": draft.goal_id,
            "base_plan_version": draft.base_plan_version,
            "new_plan_version": plan_record.version,
            "calculation_version": draft.after.calculation_version,
        },
    )
    await butler_approvals.settle(
        runtime.context.session,
        row,
        applied=True,
        audit_event_id=event.id,
    )
    return {
        "approval": {"id": str(row.id), "status": "applied"},
        "applied_plan_version": plan_record.version,
        "resume_action": "applied",
    }


async def audit_goal_run(
    state: GoalGraphState, runtime: Runtime[GoalGraphContext]
) -> dict[str, Any]:
    approval = state.get("approval") or {}
    action = "goal.run.completed"
    actor = ACTOR_BUTLER
    if approval.get("status") == "rejected":
        action = "goal.plan.rejected"
        actor = ACTOR_USER
    await record(
        runtime.context.session,
        runtime.context.user,
        actor=actor,
        action=action,
        detail={
            "request_id": state["request_id"],
            "goal_id": state.get("goal_definition").goal_id
            if state.get("goal_definition")
            else None,
            "llm_calls": state.get("llm_calls", 0),
            "approval": approval,
            "errors": state.get("errors") or [],
        },
    )
    return {}


def route_after_intake(state: GoalGraphState) -> str:
    intent = state.get("goal_intent")
    return "clarify" if state.get("errors") or (intent and intent.missing_fields) else "resolve"


def route_after_resolve(state: GoalGraphState) -> str:
    return "clarify" if state.get("errors") else "guard"


def route_after_guard(state: GoalGraphState) -> str:
    intent = state.get("goal_intent")
    return "clarify" if state.get("errors") or (intent and intent.missing_fields) else "snapshot"


def route_after_quality(state: GoalGraphState) -> str:
    quality = state.get("data_quality")
    return (
        "clarify"
        if state.get("errors") or quality is None or quality.status == "blocked"
        else "solve"
    )


def route_after_reconciliation(state: GoalGraphState) -> str:
    intent = state.get("goal_intent")
    if state.get("resume_action") in {"edit", "stale"}:
        return "draft"
    if intent and intent.action == "impact":
        return "impact"
    plan = state.get("current_goal_plan")
    if intent and (intent.wants_scenarios or intent.action == "select_scenario"):
        return "scenarios"
    return "scenarios" if plan is not None and not plan.feasible else "compose"


def route_after_impact(state: GoalGraphState) -> str:
    if state.get("errors"):
        return "clarify"
    impact = state.get("goal_impact")
    return "scenarios" if impact is not None and not impact.safe_to_spend else "compose"


def route_after_scenarios(state: GoalGraphState) -> str:
    return "clarify" if state.get("errors") else "compose"


def route_after_compose(state: GoalGraphState) -> str:
    if state.get("resume_action") in {"edit", "stale"}:
        return "draft"
    return "draft" if _plan_changed(state) else "audit"


def route_after_approval(state: GoalGraphState) -> str:
    action = state.get("resume_action")
    if action == "accept":
        return "apply"
    if action == "edit":
        return "snapshot"
    return "audit"


def route_after_apply(state: GoalGraphState) -> str:
    return "snapshot" if state.get("resume_action") == "stale" else "audit"
