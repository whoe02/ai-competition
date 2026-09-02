"""Deterministic income-to-goal recommendations and approved contributions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import (
    TXN_CONFIRMED,
    TXN_INCOME,
    Goal,
    GoalContributionRecord,
    GoalPlanRecord,
    Transaction,
    User,
)
from kira.engine import (
    GoalFundingNeed,
    IncomeAllocationPlan,
    allocate_income_to_goals,
    calculate_goal_feasibility,
)
from kira.money import Money
from kira.services.goal_planning import (
    apply_approved_plan_change,
    definition_from_record,
    load_financial_snapshot,
)


class IncomeNotFound(Exception):
    pass


class IncomeNotConfirmed(Exception):
    pass


class IncomeAlreadyAllocated(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AppliedGoalContribution:
    contribution_id: uuid.UUID
    goal_id: uuid.UUID
    goal_name: str
    amount_sen: int
    saved_after_sen: int
    target_amount_sen: int
    plan_version: int


@dataclass(frozen=True, slots=True)
class AppliedIncomeAllocation:
    plan: IncomeAllocationPlan
    contributions: tuple[AppliedGoalContribution, ...]


async def _confirmed_income(
    session: AsyncSession,
    user: User,
    transaction_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Transaction:
    query = select(Transaction).where(
        Transaction.id == transaction_id,
        Transaction.user_id == user.id,
        Transaction.direction == TXN_INCOME,
    )
    if for_update:
        query = query.with_for_update()
    transaction = (await session.execute(query)).scalar_one_or_none()
    if transaction is None:
        raise IncomeNotFound(str(transaction_id))
    if transaction.status != TXN_CONFIRMED:
        raise IncomeNotConfirmed(transaction.status)
    return transaction


async def _goal_needs(
    session: AsyncSession, user: User
) -> tuple[GoalFundingNeed, ...]:
    rows = (
        await session.execute(
            select(Goal, GoalPlanRecord)
            .join(GoalPlanRecord, GoalPlanRecord.goal_id == Goal.id)
            .where(
                Goal.user_id == user.id,
                Goal.status.in_(("active", "at_risk", "needs_replan")),
                GoalPlanRecord.approval_status == "approved",
            )
            .order_by(Goal.id, GoalPlanRecord.version.desc())
        )
    ).all()
    latest: dict[uuid.UUID, tuple[Goal, GoalPlanRecord]] = {}
    for goal, plan in rows:
        latest.setdefault(goal.id, (goal, plan))
    return tuple(
        GoalFundingNeed(
            goal_id=str(goal.id),
            name=goal.name,
            priority=goal.priority,
            target_date=goal.target_date or plan.target_date,
            remaining_amount_sen=max(0, goal.target.sen - goal.saved.sen),
            required_contribution_sen=min(
                max(0, goal.target.sen - goal.saved.sen),
                plan.next_required_reserve.sen,
            ),
        )
        for goal, plan in latest.values()
        if goal.saved.sen < goal.target.sen
    )


async def recommend_income_allocation(
    session: AsyncSession,
    user: User,
    transaction_id: uuid.UUID,
    as_of_utc: datetime,
) -> IncomeAllocationPlan:
    transaction = await _confirmed_income(session, user, transaction_id)
    if transaction.goal_allocation_applied:
        raise IncomeAlreadyAllocated(str(transaction.id))
    existing = (
        await session.execute(
            select(GoalContributionRecord.id).where(
                GoalContributionRecord.income_transaction_id == transaction.id
            )
        )
    ).first()
    if existing is not None:
        raise IncomeAlreadyAllocated(str(transaction.id))
    snapshot = await load_financial_snapshot(session, user, as_of_utc)
    return allocate_income_to_goals(
        income_transaction_id=str(transaction.id),
        income_amount_sen=transaction.amount.sen,
        snapshot=snapshot,
        goals=await _goal_needs(session, user),
    )


async def latest_unallocated_income(
    session: AsyncSession, user: User
) -> Transaction:
    transaction = (
        await session.execute(
            select(Transaction)
            .where(
                Transaction.user_id == user.id,
                Transaction.direction == TXN_INCOME,
                Transaction.status == TXN_CONFIRMED,
                Transaction.goal_allocation_applied.is_(False),
            )
            .order_by(Transaction.occurred_on.desc(), Transaction.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if transaction is None:
        raise IncomeNotFound("no confirmed unallocated income")
    return transaction


async def apply_income_allocation(
    session: AsyncSession,
    user: User,
    transaction_id: uuid.UUID,
    as_of_utc: datetime,
) -> AppliedIncomeAllocation:
    """Recompute and apply the server plan atomically after explicit approval."""
    transaction = await _confirmed_income(session, user, transaction_id, for_update=True)
    plan = await recommend_income_allocation(session, user, transaction_id, as_of_utc)
    goal_rows: list[tuple[Goal, GoalContributionRecord, int]] = []
    for allocation in plan.allocations:
        goal = (
            await session.execute(
                select(Goal)
                .where(
                    Goal.id == uuid.UUID(allocation.goal_id),
                    Goal.user_id == user.id,
                )
                .with_for_update()
            )
        ).scalar_one()
        current_version = (
            await session.execute(
                select(GoalPlanRecord.version)
                .where(GoalPlanRecord.goal_id == goal.id)
                .order_by(GoalPlanRecord.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none() or 0
        contribution = GoalContributionRecord(
            user_id=user.id,
            goal_id=goal.id,
            income_transaction_id=transaction_id,
            amount=Money(allocation.amount_sen, user.currency),
            contributed_on=as_of_utc.astimezone(UTC).date(),
            source="income_allocation",
        )
        session.add(contribution)
        goal.saved = Money(
            min(goal.target.sen, goal.saved.sen + allocation.amount_sen), user.currency
        )
        goal_rows.append((goal, contribution, current_version))
    await session.flush()
    transaction.goal_allocation_applied = True

    # Progress changes the remaining amount, so each affected plan receives a
    # new immutable approved version. This is an automatic deterministic
    # recalculation, not a second user-selected plan mutation.
    snapshot = await load_financial_snapshot(session, user, as_of_utc)
    applied: list[AppliedGoalContribution] = []
    for goal, contribution, base_version in goal_rows:
        definition = definition_from_record(goal)
        recalculated = calculate_goal_feasibility(definition, snapshot)
        record = await apply_approved_plan_change(
            session,
            user,
            definition=definition,
            plan=recalculated,
            base_plan_version=base_version,
            as_of_utc=as_of_utc,
        )
        applied.append(
            AppliedGoalContribution(
                contribution_id=contribution.id,
                goal_id=goal.id,
                goal_name=goal.name,
                amount_sen=contribution.amount.sen,
                saved_after_sen=goal.saved.sen,
                target_amount_sen=goal.target.sen,
                plan_version=record.version,
            )
        )
    await session.commit()
    return AppliedIncomeAllocation(plan=plan, contributions=tuple(applied))
