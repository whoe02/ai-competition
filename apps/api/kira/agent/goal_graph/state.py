"""Typed checkpointed state and non-checkpointed runtime context."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from kira.agent.goal_graph.schemas import GoalDataQuality, GoalIntent
from kira.db.models import User
from kira.engine import (
    CashflowReconciliation,
    FinancialSnapshot,
    GoalDefinition,
    GoalImpact,
    GoalPlan,
    GoalScenario,
)


@dataclass(frozen=True, slots=True)
class PlanChangeDraft:
    request_id: str
    goal_id: str
    base_plan_version: int
    before: GoalPlan | None
    after: GoalPlan
    definition: GoalDefinition
    reason: str


class GoalGraphState(TypedDict, total=False):
    request_id: str
    thread_id: str
    user_id: str
    user_message: str
    goal_intent: GoalIntent | None
    goal_definition: GoalDefinition | None
    base_goal_definition: GoalDefinition | None
    financial_snapshot: FinancialSnapshot | None
    data_quality: GoalDataQuality | None
    current_goal_plan: GoalPlan | None
    base_goal_plan: GoalPlan | None
    current_plan_version: int
    goal_scenarios: tuple[GoalScenario, ...]
    selected_scenario: GoalScenario | None
    reconciliation: CashflowReconciliation | None
    goal_impact: GoalImpact | None
    proposed_change: PlanChangeDraft | None
    approval: dict[str, Any] | None
    final_response: str
    evidence_refs: tuple[str, ...]
    errors: list[str]
    llm_calls: int
    override_contribution_sen: int | None
    resume_action: str | None
    applied_plan_version: int | None
    approval_round: int


@dataclass(frozen=True, slots=True)
class GoalGraphContext:
    session: AsyncSession
    user: User
    as_of_utc: datetime
    thread_id: uuid.UUID
    model_factory: Callable[..., Any] | None = None
    structured_intent: GoalIntent | dict[str, Any] | None = None
    explain: bool = True


def initial_goal_state(
    *, request_id: uuid.UUID, thread_id: uuid.UUID, user_id: uuid.UUID, message: str
) -> GoalGraphState:
    return GoalGraphState(
        request_id=str(request_id),
        thread_id=str(thread_id),
        user_id=str(user_id),
        user_message=message,
        goal_intent=None,
        goal_definition=None,
        base_goal_definition=None,
        financial_snapshot=None,
        data_quality=None,
        current_goal_plan=None,
        base_goal_plan=None,
        current_plan_version=0,
        goal_scenarios=(),
        selected_scenario=None,
        reconciliation=None,
        goal_impact=None,
        proposed_change=None,
        approval=None,
        final_response="",
        evidence_refs=(),
        errors=[],
        llm_calls=0,
        override_contribution_sen=None,
        resume_action=None,
        applied_plan_version=None,
        approval_round=0,
    )
