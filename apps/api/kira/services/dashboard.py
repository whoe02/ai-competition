"""Assemble the Today screen DTO using persisted facts and the pure engine."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import TXN_DRAFT, Commitment, Goal, Transaction, User
from kira.engine import months_to_goal, safe_to_spend
from kira.services.snapshot import load_snapshot


@dataclass(frozen=True, slots=True)
class NextCommitment:
    id: uuid.UUID
    name: str
    amount_sen: int
    due_date: date
    days_until: int
    protected: bool


@dataclass(frozen=True, slots=True)
class GoalSummary:
    id: uuid.UUID
    name: str
    horizon: str
    target_sen: int
    saved_sen: int
    monthly_sen: int
    months_left: int
    note: str


@dataclass(frozen=True, slots=True)
class DashboardToday:
    date: date
    display_name: str
    currency: str
    balance_sen: int
    reserved_sen: int
    buffer_sen: int
    goal_reserve_sen: int
    unclaimed_sen: int
    per_day_sen: int
    spent_today_sen: int
    safe_today_sen: int
    days_to_payday: int
    cycle_elapsed: int
    commitment_count: int
    drafts_waiting: int
    next_commitment: NextCommitment | None
    goals: tuple[GoalSummary, ...]


async def today_dashboard(
    session: AsyncSession, user: User, today: date
) -> DashboardToday:
    snapshot = await load_snapshot(session, user, today)
    result = safe_to_spend(snapshot)

    drafts_waiting = (
        await session.execute(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.user_id == user.id, Transaction.status == TXN_DRAFT)
        )
    ).scalar_one()

    commitments = (
        await session.execute(
            select(Commitment)
            .where(Commitment.user_id == user.id)
            .order_by(Commitment.due_date)
        )
    ).scalars().all()
    upcoming = next(
        (commitment for commitment in commitments if commitment.due_date >= today),
        None,
    )
    next_commitment = (
        NextCommitment(
            id=upcoming.id,
            name=upcoming.name,
            amount_sen=upcoming.amount.sen,
            due_date=upcoming.due_date,
            days_until=(upcoming.due_date - today).days,
            protected=upcoming.protected,
        )
        if upcoming
        else None
    )

    goals = (
        await session.execute(
            select(Goal)
            .where(Goal.user_id == user.id, Goal.status != "draft", Goal.status != "cancelled")
            .order_by(Goal.name)
        )
    ).scalars().all()

    return DashboardToday(
        date=today,
        display_name=user.display_name,
        currency=user.currency,
        balance_sen=result.balance.sen,
        reserved_sen=result.reserved.sen,
        buffer_sen=result.buffer.sen,
        goal_reserve_sen=result.goal_reserve.sen,
        unclaimed_sen=result.unclaimed.sen,
        per_day_sen=result.per_day.sen,
        spent_today_sen=result.spent_today.sen,
        safe_today_sen=result.safe_today.sen,
        days_to_payday=result.days_to_payday,
        cycle_elapsed=result.cycle_elapsed,
        commitment_count=len(commitments),
        drafts_waiting=drafts_waiting,
        next_commitment=next_commitment,
        goals=tuple(
            GoalSummary(
                id=goal.id,
                name=goal.name,
                horizon=goal.horizon,
                target_sen=goal.target.sen,
                saved_sen=goal.saved.sen,
                monthly_sen=goal.monthly.sen,
                months_left=months_to_goal(goal.target, goal.saved, goal.monthly),
                note=goal.note,
            )
            for goal in goals
        ),
    )
