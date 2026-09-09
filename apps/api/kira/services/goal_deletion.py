"""Recoverable goal deletion and its deterministic cash-flow preview."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import Goal, GoalContributionRecord, GoalPlanRecord, User
from kira.engine import safe_to_spend
from kira.money import Money
from kira.services.audit import ACTOR_USER, record
from kira.services.goal_planning import GoalNotFound, recalculate_active_goal_plans
from kira.services.snapshot import load_snapshot


async def _impact(
    session: AsyncSession, user: User, goal: Goal, as_of_utc: datetime
) -> dict[str, object]:
    if goal.status == "deleted":
        raise GoalNotFound(str(goal.id))

    snapshot = await load_snapshot(session, user, as_of_utc.astimezone(UTC).date())
    before = safe_to_spend(snapshot)
    contributions = (
        await session.execute(
            select(GoalContributionRecord).where(
                GoalContributionRecord.user_id == user.id,
                GoalContributionRecord.goal_id == goal.id,
            )
        )
    ).scalars().all()
    released_contributions_sen = sum(item.amount.sen for item in contributions)
    simulated = replace(
        snapshot,
        goals=tuple(item for item in snapshot.goals if item.id != str(goal.id)),
        contributed_goal_reserve=Money(
            max(0, snapshot.contributed_goal_reserve.sen - released_contributions_sen),
            user.currency,
        ),
    )
    after = safe_to_spend(simulated)
    current = (
        await session.execute(
            select(GoalPlanRecord)
            .where(GoalPlanRecord.goal_id == goal.id)
            .order_by(GoalPlanRecord.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    return {
        "goal_id": goal.id,
        "goal_name": goal.name,
        "contribution_per_payday_released_sen": (
            current.next_required_reserve.sen
            if current is not None
            and goal.status in ("active", "at_risk", "needs_replan")
            else 0
        ),
        "safe_today_before_sen": before.safe_today.sen,
        "safe_today_after_sen": after.safe_today.sen,
        "safe_today_increase_sen": max(0, after.safe_today.sen - before.safe_today.sen),
    }


async def deletion_impact(
    session: AsyncSession, user: User, goal_id: uuid.UUID, as_of_utc: datetime
) -> dict[str, object]:
    goal = (
        await session.execute(
            select(Goal).where(Goal.id == goal_id, Goal.user_id == user.id)
        )
    ).scalar_one_or_none()
    if goal is None:
        raise GoalNotFound(str(goal_id))
    return await _impact(session, user, goal, as_of_utc)


async def delete_goal(
    session: AsyncSession, user: User, goal_id: uuid.UUID, as_of_utc: datetime
) -> dict[str, object]:
    goal = (
        await session.execute(
            select(Goal)
            .where(Goal.id == goal_id, Goal.user_id == user.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if goal is None or goal.status == "deleted":
        raise GoalNotFound(str(goal_id))

    impact = await _impact(session, user, goal, as_of_utc)
    deleted_at = datetime.now(tz=UTC)
    goal.status = "deleted"
    goal.deleted_at = deleted_at
    await session.flush()

    # The remaining plans may become feasible once this goal stops competing
    # for capacity. Historical plans and contribution rows remain untouched.
    await recalculate_active_goal_plans(session, user, as_of_utc)
    await record(
        session,
        user,
        actor=ACTOR_USER,
        action="goal.deleted",
        detail={
            "goal_id": str(goal.id),
            "goal_name": goal.name,
            "safe_today_increase_sen": impact["safe_today_increase_sen"],
            "contribution_per_payday_released_sen": impact[
                "contribution_per_payday_released_sen"
            ],
        },
    )
    await session.commit()
    return {**impact, "status": "deleted", "deleted_at": deleted_at}
