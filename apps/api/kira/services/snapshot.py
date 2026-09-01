"""Turn persisted financial rows into the pure engine's complete Snapshot."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import TXN_CONFIRMED, Account, Commitment, Goal, Transaction, User
from kira.engine.types import CommitmentInput, GoalInput, Snapshot
from kira.money import Money


async def load_snapshot(session: AsyncSession, user: User, today: date) -> Snapshot:
    """Load a user's finance picture, deliberately excluding every draft transaction."""
    currency = user.currency
    accounts = (
        await session.execute(select(Account).where(Account.user_id == user.id))
    ).scalars().all()
    opening = Money.sum((account.opening_balance for account in accounts), currency)

    confirmed = (
        await session.execute(
            select(Transaction).where(
                Transaction.user_id == user.id,
                Transaction.status == TXN_CONFIRMED,
            )
        )
    ).scalars().all()
    spent_all_time = Money.sum((txn.amount for txn in confirmed), currency)
    spent_today = Money.sum(
        (txn.amount for txn in confirmed if txn.occurred_on == today), currency
    )

    commitments = (
        await session.execute(select(Commitment).where(Commitment.user_id == user.id))
    ).scalars().all()
    goals = (
        await session.execute(
            select(Goal).where(
                Goal.user_id == user.id,
                Goal.status.in_(("active", "at_risk", "needs_replan")),
            )
        )
    ).scalars().all()

    return Snapshot(
        balance=opening - spent_all_time,
        buffer=user.buffer,
        spent_today=spent_today,
        commitments=tuple(
            CommitmentInput(str(commitment.id), commitment.amount, commitment.due_date)
            for commitment in commitments
        ),
        goals=tuple(
            GoalInput(
                str(goal.id),
                goal.monthly,
                goal.target,
                goal.saved,
                goal.target_date,
            )
            for goal in goals
        ),
        today=today,
        next_payday=user.next_payday,
        cycle_start=user.cycle_start,
        cycle_days=user.cycle_days,
        income=user.monthly_income,
    )
