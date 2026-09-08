"""AI-written, user-approved part-time reminders for at-risk goal plans.

The model selects and explains a work *type*. It never supplies financial
inputs: the required extra income and every before/after figure are calculated
from the versioned goal plan and the deterministic engine.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.agent.llm import get_chat_model
from kira.db.models import Goal, GoalPlanRecord, User
from kira.engine import GoalPlan, IncomePayday, calculate_goal_feasibility
from kira.money import Money
from kira.services.audit import ACTOR_USER, record as record_audit
from kira.services.goal_planning import (
    GoalNotFound,
    apply_approved_plan_change,
    current_plan_record,
    definition_from_record,
    load_financial_snapshot,
    owned_goal,
    plan_from_record,
    recalculate_active_goal_plans,
)


PART_TIME_RECOMMENDER_PROMPT = """You are Kira's part-time work recommender.

Suggest one realistic, entry-level and flexible part-time work TYPE that could
help a Malaysian user improve an at-risk savings goal. You know no skills,
availability, transport, health, or work-right details about the user, so do
not claim the role is a personal fit, available, guaranteed, safe, legal, or
enough to meet a target. Do not name a real employer or job listing. Do not ask
for sensitive information. Do not give financial, legal, tax, employment, or
health advice.

The deterministic planner has already calculated the extra monthly income
needed. Do not state, estimate, repeat, or alter any money, hours, dates,
salary, contribution, ratio, or completion claim. Return only the requested
structured copy: a concise role title, why it may be worth exploring, one
low-risk first step, and up to three practical cautions. Keep the wording
supportive and non-coercive. The user must explicitly approve before any
forecast changes.
"""


class PartTimeJobCopy(BaseModel):
    role_title: str = Field(min_length=3, max_length=80)
    summary: str = Field(min_length=10, max_length=280)
    first_step: str = Field(min_length=8, max_length=180)
    cautions: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("role_title", "summary", "first_step")
    @classmethod
    def no_numbers_or_currency(cls, value: str) -> str:
        if any(character.isdigit() for character in value) or re.search(r"\\b(?:rm|myr)\\b", value, re.I):
            raise ValueError("job copy must not make financial claims")
        return value.strip()

    @field_validator("cautions")
    @classmethod
    def clean_cautions(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            value = value.strip()
            if not value:
                continue
            if any(character.isdigit() for character in value) or re.search(r"\\b(?:rm|myr)\\b", value, re.I):
                raise ValueError("job copy must not make financial claims")
            cleaned.append(value)
        return cleaned


class PartTimeRecommendationError(Exception):
    """A recommendation cannot be generated or is no longer safe to approve."""


def _ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def _needs_reminder(plan: GoalPlan) -> bool:
    return (
        not plan.feasible
        or plan.affordability_status in {"high_risk", "unsustainable", "impossible"}
        or (
            plan.projected_completion_date is not None
            and plan.projected_completion_date > plan.target_date
        )
    )


def _additional_income_needed(plan: GoalPlan) -> int | None:
    """Income needed to get total goal saving down to a safer 40% of income."""
    if plan.monthly_income_sen is None or plan.monthly_goal_contributions_sen <= 0:
        return None
    target_income = max(
        _ceil_div(plan.monthly_goal_contributions_sen * 10_000, 4_000),
        plan.monthly_goal_contributions_sen + plan.monthly_protected_commitments_sen,
    )
    return max(0, target_income - plan.monthly_income_sen)


def _fallback_copy(goal: Goal) -> PartTimeJobCopy:
    type_hint = {
        "travel": "Flexible event support",
        "big_purchase": "Flexible retail support",
        "education_family_goal": "Tutoring or study support",
        "house_down_payment": "Flexible customer support",
        "car_down_payment": "Flexible delivery support",
    }.get(goal.goal_type, "Flexible customer support")
    return PartTimeJobCopy(
        role_title=type_hint,
        summary="A flexible role may be worth exploring if it fits your schedule and existing commitments.",
        first_step="Compare nearby or remote options and check the work expectations before applying.",
        cautions=[
            "Confirm the schedule will not displace essential commitments.",
            "Check the employer and contract terms before sharing personal details.",
        ],
    )


async def _job_copy(goal: Goal, plan: GoalPlan, *, model: Any | None = None) -> tuple[PartTimeJobCopy, str]:
    prompt_input = {
        "goal_name": goal.name,
        "goal_type": goal.goal_type,
        "plan_health": plan.affordability_status,
        "goal_is_currently_feasible": plan.feasible,
    }
    try:
        chat = model or get_chat_model(streaming=False, temperature=0.2)
        result = await chat.with_structured_output(PartTimeJobCopy).ainvoke(
            [
                SystemMessage(content=PART_TIME_RECOMMENDER_PROMPT),
                HumanMessage(content=str(prompt_input)),
            ]
        )
        return (
            result if isinstance(result, PartTimeJobCopy) else PartTimeJobCopy.model_validate(result),
            "llm",
        )
    except Exception:
        # Development/offline operation should still preserve the exact same
        # deterministic projection and explicit approval boundary.
        return _fallback_copy(goal), "fallback"


def _response_data(
    *,
    goal: Goal,
    record: GoalPlanRecord,
    before: GoalPlan,
    after: GoalPlan | None,
    additional_income_sen: int | None,
    copy: PartTimeJobCopy | None,
    source: str | None,
    status: str,
    reason: str | None = None,
) -> dict[str, object]:
    return {
        "goal_id": str(goal.id),
        "plan_version": record.version,
        "status": status,
        "eligible": additional_income_sen is not None and additional_income_sen > 0,
        "reason": reason,
        "role_title": copy.role_title if copy else None,
        "summary": copy.summary if copy else None,
        "first_step": copy.first_step if copy else None,
        "cautions": copy.cautions if copy else [],
        "source": source,
        "additional_monthly_income_sen": additional_income_sen,
        "monthly_income_before_sen": before.monthly_income_sen,
        "monthly_income_after_sen": after.monthly_income_sen if after else None,
        "contribution_ratio_before_bp": before.contribution_ratio_bp,
        "contribution_ratio_after_bp": after.contribution_ratio_bp if after else None,
        "feasible_before": before.feasible,
        "feasible_after": after.feasible if after else None,
        "projected_completion_before": (
            before.projected_completion_date.isoformat()
            if before.projected_completion_date
            else None
        ),
        "projected_completion_after": (
            after.projected_completion_date.isoformat() if after and after.projected_completion_date else None
        ),
        "safe_to_spend_changes": False,
        "cash_effect": "Forecast only. Safe to Spend changes only when income is confirmed.",
    }


async def create_part_time_recommendation(
    session: AsyncSession,
    user: User,
    goal_id,
    as_of_utc: datetime,
    *,
    model: Any | None = None,
) -> dict[str, object]:
    goal = await owned_goal(session, user, goal_id)
    record = await current_plan_record(session, user, goal_id)
    before = plan_from_record(record)
    if not _needs_reminder(before):
        data = _response_data(
            goal=goal,
            record=record,
            before=before,
            after=None,
            additional_income_sen=None,
            copy=None,
            source=None,
            status="not_needed",
            reason="This plan is already on track without an extra-work reminder.",
        )
        record.part_time_recommendation_data = data
        await session.commit()
        return data

    additional = _additional_income_needed(before)
    if additional is None or additional == 0:
        data = _response_data(
            goal=goal,
            record=record,
            before=before,
            after=None,
            additional_income_sen=None,
            copy=None,
            source=None,
            status="not_available",
            reason="A recurring-income estimate is needed before Kira can model this option.",
        )
        record.part_time_recommendation_data = data
        await session.commit()
        return data

    snapshot = await load_financial_snapshot(session, user, as_of_utc)
    projected_snapshot = replace(
        snapshot,
        next_income_payday=IncomePayday(
            payday_date=snapshot.next_income_payday.payday_date,
            amount_sen=(snapshot.next_income_payday.amount_sen or 0) + additional,
            evidence_ref=snapshot.next_income_payday.evidence_ref,
        ),
    )
    after = calculate_goal_feasibility(definition_from_record(goal), projected_snapshot)
    copy, source = await _job_copy(goal, before, model=model)
    data = _response_data(
        goal=goal,
        record=record,
        before=before,
        after=after,
        additional_income_sen=additional,
        copy=copy,
        source=source,
        status="available",
    )
    record.part_time_recommendation_data = data
    await session.commit()
    return data


async def approve_part_time_recommendation(
    session: AsyncSession, user: User, goal_id, as_of_utc: datetime
) -> dict[str, object]:
    """Start a forecast only after a direct user approval, then replan safely."""
    goal = await owned_goal(session, user, goal_id)
    current = await current_plan_record(session, user, goal_id)
    data = dict(current.part_time_recommendation_data or {})
    if data.get("status") != "available" or data.get("plan_version") != current.version:
        raise PartTimeRecommendationError("Generate a current recommendation before approving it.")
    additional = data.get("additional_monthly_income_sen")
    if isinstance(additional, bool) or not isinstance(additional, int) or additional <= 0:
        raise PartTimeRecommendationError("This recommendation has no safe income projection to approve.")

    locked_user = (
        await session.execute(select(User).where(User.id == user.id).with_for_update())
    ).scalar_one()
    # The recommendation is a plan, not a transaction. It improves future
    # feasibility only; current cash and Safe to Spend are intentionally intact.
    locked_user.part_time_income = Money(
        locked_user.part_time_income.sen + additional, locked_user.currency
    )
    snapshot = await load_financial_snapshot(session, locked_user, as_of_utc)
    after = calculate_goal_feasibility(definition_from_record(goal), snapshot)
    approved = await apply_approved_plan_change(
        session,
        locked_user,
        definition=definition_from_record(goal),
        plan=after,
        base_plan_version=current.version,
        as_of_utc=as_of_utc,
    )
    approved_data = dict(data)
    approved_data.update(
        _response_data(
            goal=goal,
            record=approved,
            before=plan_from_record(current),
            after=after,
            additional_income_sen=additional,
            copy=PartTimeJobCopy.model_validate(
                {
                    "role_title": data.get("role_title"),
                    "summary": data.get("summary"),
                    "first_step": data.get("first_step"),
                    "cautions": data.get("cautions", []),
                }
            ),
            source=str(data.get("source") or "llm"),
            status="approved",
        )
    )
    approved_data["approved_at"] = datetime.now(tz=UTC).isoformat()
    approved.part_time_recommendation_data = approved_data
    await recalculate_active_goal_plans(session, locked_user, as_of_utc)
    await record_audit(
        session,
        locked_user,
        actor=ACTOR_USER,
        action="approve_part_time_income_forecast",
        detail={
            "goal_id": str(goal.id),
            "additional_monthly_income_sen": additional,
            "role_title": data.get("role_title"),
            "safe_to_spend_changes": False,
        },
    )
    await session.commit()
    return approved_data
