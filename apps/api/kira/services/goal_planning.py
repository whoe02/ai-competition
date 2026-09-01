"""Persistence and snapshot assembly for the deterministic goal engine."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import (
    TXN_CONFIRMED,
    Account,
    Commitment,
    Goal,
    GoalMilestoneRecord,
    GoalPlanRecord,
    GoalScenarioRecord,
    Transaction,
    User,
)
from kira.engine import (
    AccountBalance,
    ActiveGoalReserve,
    FinancialSnapshot,
    GoalDefinition,
    GoalImpact,
    GoalMilestone,
    GoalPlan,
    GoalScenario,
    IncomePayday,
    ProtectedCommitment,
    calculate_goal_feasibility,
    classify_goal_horizon,
    evaluate_goal_impact,
    generate_goal_scenarios,
    validate_goal_definition,
)
from kira.money import Money


class GoalNotFound(Exception):
    """The requested goal does not belong to this user."""


class InvalidFundingAccount(Exception):
    """A proposed funding account does not belong to this user."""


class StalePlanVersion(Exception):
    """The approved draft was calculated from a plan that is no longer current."""


def definition_from_record(goal: Goal) -> GoalDefinition:
    if goal.target_date is None:
        raise ValueError("legacy goal has no target_date and needs replanning")
    return GoalDefinition(
        goal_id=str(goal.id),
        user_id=str(goal.user_id),
        goal_type=goal.goal_type,
        name=goal.name,
        currency=goal.currency,
        target_amount_sen=goal.target.sen,
        current_saved_sen=goal.saved.sen,
        target_date=goal.target_date,
        priority=goal.priority,
        status=goal.status,
        funding_account_ids=tuple(goal.funding_account_ids),
    )


async def owned_goal(session: AsyncSession, user: User, goal_id: uuid.UUID) -> Goal:
    goal = (
        await session.execute(select(Goal).where(Goal.id == goal_id, Goal.user_id == user.id))
    ).scalar_one_or_none()
    if goal is None:
        raise GoalNotFound(str(goal_id))
    return goal


async def load_financial_snapshot(
    session: AsyncSession, user: User, as_of_utc: datetime
) -> FinancialSnapshot:
    """Build a snapshot from confirmed records; drafts never enter the engine."""
    accounts = (
        (await session.execute(select(Account).where(Account.user_id == user.id))).scalars().all()
    )
    confirmed = (
        (
            await session.execute(
                select(Transaction).where(
                    Transaction.user_id == user.id,
                    Transaction.status == TXN_CONFIRMED,
                )
            )
        )
        .scalars()
        .all()
    )
    commitments = (
        (await session.execute(select(Commitment).where(Commitment.user_id == user.id)))
        .scalars()
        .all()
    )
    opening_sen = sum(account.opening_balance.sen for account in accounts)
    spent_sen = sum(transaction.amount.sen for transaction in confirmed)

    # Only the latest plan for each active goal can reserve money. Draft goals
    # and superseded plan versions are deliberately absent.
    active_rows = (
        await session.execute(
            select(GoalPlanRecord, Goal)
            .join(Goal, Goal.id == GoalPlanRecord.goal_id)
            .where(
                Goal.user_id == user.id,
                Goal.status.in_(("active", "at_risk", "needs_replan")),
                GoalPlanRecord.approval_status == "approved",
            )
            .order_by(GoalPlanRecord.goal_id, GoalPlanRecord.version.desc())
        )
    ).all()
    latest_by_goal: dict[uuid.UUID, tuple[GoalPlanRecord, Goal]] = {}
    for plan, goal in active_rows:
        latest_by_goal.setdefault(goal.id, (plan, goal))

    evidence = [f"account:{account.id}" for account in accounts]
    evidence.extend(f"transaction:{transaction.id}" for transaction in confirmed)
    evidence.extend(f"commitment:{commitment.id}" for commitment in commitments)
    evidence.append(f"user-payday:{user.id}")
    return FinancialSnapshot(
        user_id=str(user.id),
        as_of_utc=as_of_utc.astimezone(UTC),
        currency=user.currency,
        cash_available_sen=opening_sen - spent_sen,
        accounts=tuple(
            AccountBalance(
                account_id=str(account.id),
                balance_sen=account.opening_balance.sen,
                evidence_ref=f"account:{account.id}",
            )
            for account in accounts
        ),
        next_income_payday=IncomePayday(
            payday_date=user.next_payday,
            # The present schema records the payday but not a confirmed amount.
            # None is intentionally not converted into an optimistic estimate.
            amount_sen=None,
            evidence_ref=f"user-payday:{user.id}",
        ),
        commitments=tuple(
            ProtectedCommitment(
                commitment_id=str(commitment.id),
                name=commitment.name,
                amount_sen=commitment.amount.sen,
                due_date=commitment.due_date,
                protected=commitment.protected,
                evidence_ref=f"commitment:{commitment.id}",
            )
            for commitment in commitments
        ),
        emergency_buffer_sen=user.buffer.sen,
        active_goal_plans=tuple(
            ActiveGoalReserve(
                goal_id=str(goal.id),
                next_required_reserve_sen=plan.next_required_reserve.sen,
                priority=goal.priority,
            )
            for plan, goal in latest_by_goal.values()
        ),
        data_confidence="medium" if accounts else "low",
        evidence_refs=tuple(evidence),
        pay_cycle_days=user.cycle_days,
    )


def plan_from_record(record: GoalPlanRecord) -> GoalPlan:
    milestones = tuple(
        # Rows are explicitly sorted below so database return order cannot
        # change an API response or a reproducibility comparison.
        GoalMilestone(milestone.percentage, milestone.amount.sen, milestone.projected_date)
        for milestone in sorted(record.milestones, key=lambda row: row.percentage)
    )
    return GoalPlan(
        goal_id=str(record.goal_id),
        feasible=record.feasible,
        target_amount_sen=record.target_amount.sen,
        current_saved_sen=record.current_saved.sen,
        remaining_amount_sen=record.remaining_amount.sen,
        target_date=record.target_date,
        required_contribution_per_payday_sen=record.required_contribution_per_payday.sen,
        next_required_reserve_sen=record.next_required_reserve.sen,
        projected_completion_date=record.projected_completion_date,
        milestones=milestones,
        risk_flags=tuple(record.risk_flags),
        assumptions=tuple(record.assumptions),
        calculation_version=record.calculation_version,
        evidence_refs=tuple(record.evidence_refs),
    )


async def persist_new_plan_version(
    session: AsyncSession,
    goal: Goal,
    plan: GoalPlan,
    *,
    approval_status: str = "draft",
) -> GoalPlanRecord:
    """Append a plan version. Existing versions are never updated or deleted."""
    current_version = (
        await session.execute(
            select(func.max(GoalPlanRecord.version)).where(GoalPlanRecord.goal_id == goal.id)
        )
    ).scalar_one()
    record = GoalPlanRecord(
        goal_id=goal.id,
        version=(current_version or 0) + 1,
        approval_status=approval_status,
        feasible=plan.feasible,
        target_amount=Money(plan.target_amount_sen, goal.currency),
        current_saved=Money(plan.current_saved_sen, goal.currency),
        remaining_amount=Money(plan.remaining_amount_sen, goal.currency),
        required_contribution_per_payday=Money(
            plan.required_contribution_per_payday_sen, goal.currency
        ),
        next_required_reserve=Money(plan.next_required_reserve_sen, goal.currency),
        target_date=plan.target_date,
        projected_completion_date=plan.projected_completion_date,
        risk_flags=list(plan.risk_flags),
        assumptions=list(plan.assumptions),
        evidence_refs=list(plan.evidence_refs),
        calculation_version=plan.calculation_version,
    )
    session.add(record)
    await session.flush()
    for milestone in plan.milestones:
        session.add(
            GoalMilestoneRecord(
                plan_id=record.id,
                percentage=milestone.percentage,
                amount=Money(milestone.amount_sen, goal.currency),
                projected_date=milestone.projected_date,
            )
        )
    await session.flush()
    await session.refresh(record, attribute_names=["milestones"])
    return record


async def create_draft_goal(
    session: AsyncSession,
    user: User,
    *,
    goal_type: str,
    name: str,
    target_amount_sen: int,
    current_saved_sen: int,
    target_date: date,
    priority: str,
    funding_account_ids: tuple[uuid.UUID, ...],
    as_of_utc: datetime,
    goal_id: uuid.UUID | None = None,
) -> tuple[Goal, GoalPlanRecord]:
    if funding_account_ids:
        owned_ids = set(
            (
                await session.execute(
                    select(Account.id).where(
                        Account.user_id == user.id, Account.id.in_(funding_account_ids)
                    )
                )
            ).scalars()
        )
        if owned_ids != set(funding_account_ids):
            raise InvalidFundingAccount("one or more funding accounts are unavailable")

    goal_id = goal_id or uuid.uuid4()
    definition = GoalDefinition(
        goal_id=str(goal_id),
        user_id=str(user.id),
        goal_type=goal_type,
        name=name,
        currency=user.currency,
        target_amount_sen=target_amount_sen,
        current_saved_sen=current_saved_sen,
        target_date=target_date,
        priority=priority,
        status="draft",
        funding_account_ids=tuple(str(value) for value in funding_account_ids),
    )
    validate_goal_definition(definition, as_of_date=as_of_utc.astimezone(UTC).date())
    snapshot = await load_financial_snapshot(session, user, as_of_utc)
    plan = calculate_goal_feasibility(definition, snapshot)
    goal = Goal(
        id=goal_id,
        user_id=user.id,
        name=name.strip(),
        horizon=classify_goal_horizon(definition, as_of_utc.astimezone(UTC).date()),
        target=Money(target_amount_sen, user.currency),
        saved=Money(current_saved_sen, user.currency),
        monthly=Money(plan.required_contribution_per_payday_sen, user.currency),
        note="",
        goal_type=goal_type,
        currency=user.currency,
        target_date=target_date,
        priority=priority,
        status="draft",
        funding_account_ids=[str(value) for value in funding_account_ids],
    )
    session.add(goal)
    await session.flush()
    record = await persist_new_plan_version(session, goal, plan)
    await session.commit()
    return goal, record


async def current_plan_record(
    session: AsyncSession, user: User, goal_id: uuid.UUID
) -> GoalPlanRecord:
    await owned_goal(session, user, goal_id)
    record = (
        await session.execute(
            select(GoalPlanRecord)
            .where(GoalPlanRecord.goal_id == goal_id)
            .order_by(GoalPlanRecord.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if record is None:
        raise GoalNotFound(f"goal {goal_id} has no plan")
    return record


async def create_scenarios(
    session: AsyncSession, user: User, goal_id: uuid.UUID, as_of_utc: datetime
) -> tuple[GoalScenario, ...]:
    goal = await owned_goal(session, user, goal_id)
    definition = definition_from_record(goal)
    snapshot = await load_financial_snapshot(session, user, as_of_utc)
    scenarios = generate_goal_scenarios(definition, snapshot)
    plan_record = await current_plan_record(session, user, goal_id)
    existing = set(
        (
            await session.execute(
                select(GoalScenarioRecord.id).where(GoalScenarioRecord.plan_id == plan_record.id)
            )
        ).scalars()
    )
    for scenario in scenarios:
        scenario_id = uuid.UUID(scenario.scenario_id)
        if scenario_id in existing:
            continue
        session.add(
            GoalScenarioRecord(
                id=scenario_id,
                plan_id=plan_record.id,
                label=scenario.label,
                feasible=scenario.feasible,
                contribution_per_payday=Money(scenario.contribution_per_payday_sen, goal.currency),
                target_date=scenario.target_date,
                goal_delay_days=scenario.goal_delay_days,
                flexible_spending_delta=Money(scenario.flexible_spending_delta_sen, goal.currency),
                tradeoffs=list(scenario.tradeoffs),
                risk_flags=list(scenario.risk_flags),
                evidence_refs=list(scenario.evidence_refs),
                calculation_version=scenario.calculation_version,
            )
        )
    await session.commit()
    return scenarios


async def purchase_impact(
    session: AsyncSession,
    user: User,
    goal_id: uuid.UUID,
    proposed_spend_sen: int,
    as_of_utc: datetime,
) -> GoalImpact:
    record = await current_plan_record(session, user, goal_id)
    snapshot = await load_financial_snapshot(session, user, as_of_utc)
    return evaluate_goal_impact(proposed_spend_sen, snapshot, plan_from_record(record))


async def apply_approved_plan_change(
    session: AsyncSession,
    user: User,
    *,
    definition: GoalDefinition,
    plan: GoalPlan,
    base_plan_version: int,
    as_of_utc: datetime,
) -> GoalPlanRecord:
    """Append an approved version after an optimistic version check.

    The caller owns the surrounding transaction so the plan, approval row and
    audit event commit together. Previous approved versions are retained.
    """
    goal_id = uuid.UUID(definition.goal_id)
    goal = (
        await session.execute(
            select(Goal).where(Goal.id == goal_id, Goal.user_id == user.id).with_for_update()
        )
    ).scalar_one_or_none()
    if goal is None:
        raise GoalNotFound(str(goal_id))
    current = (
        await session.execute(
            select(GoalPlanRecord)
            .where(GoalPlanRecord.goal_id == goal_id)
            .order_by(GoalPlanRecord.version.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    current_version = current.version if current is not None else 0
    if current_version != base_plan_version:
        raise StalePlanVersion(
            f"expected plan version {base_plan_version}, found {current_version}"
        )

    goal.name = definition.name
    goal.goal_type = definition.goal_type
    goal.currency = definition.currency
    goal.target = Money(definition.target_amount_sen, definition.currency)
    goal.saved = Money(definition.current_saved_sen, definition.currency)
    goal.target_date = definition.target_date
    goal.horizon = classify_goal_horizon(definition, as_of_utc.astimezone(UTC).date())
    goal.priority = definition.priority
    if plan.remaining_amount_sen == 0:
        goal.status = "achieved"
    else:
        goal.status = "active" if plan.feasible else "at_risk"
    goal.monthly = Money(plan.required_contribution_per_payday_sen, definition.currency)
    goal.funding_account_ids = list(definition.funding_account_ids)
    record = await persist_new_plan_version(session, goal, plan, approval_status="approved")
    record.approved_at = datetime.now(tz=UTC)
    await session.flush()
    return record
