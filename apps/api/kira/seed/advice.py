"""Backfills what Kira would have advised on each past day.

Every row is produced by running the real engine over that day's reconstructed
picture. A hand-written track record would score Kira near 100%, which is both
false and obviously false — so nothing here is written by hand.

The reconstruction is deliberate rather than a call to ``load_snapshot``: that
function answers "what is true now", summing every confirmed transaction
regardless of date. Asked about a day in June it would return June's date with
September's balance.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import (
    ADVICE_SOURCE_SEED,
    TXN_CONFIRMED,
    Account,
    Commitment,
    DailyAdvice,
    Goal,
    Transaction,
    User,
)
from kira.engine import safe_to_spend
from kira.engine.types import CommitmentInput, GoalInput, Snapshot
from kira.money import Money
from kira.services.advice import snapshot_json


def cycle_for(
    day: date, cycle_start: date, next_payday: date, cycle_days: int
) -> tuple[date, date]:
    """The pay cycle containing ``day``, stepped back from the user's current one."""
    start, payday = cycle_start, next_payday
    step = timedelta(days=cycle_days)
    while start > day:
        start -= step
        payday -= step
    while payday <= day:
        start += step
        payday += step
    return start, payday


def _due_in_cycle(due_date: date, cycle_start: date, cycle_days: int) -> date:
    """Slide a monthly bill into the cycle being reconstructed."""
    step = timedelta(days=cycle_days)
    due = due_date
    while due >= cycle_start + step:
        due -= step
    while due < cycle_start:
        due += step
    return due


async def backfill_advice(
    session: AsyncSession, user: User, start: date, end: date
) -> int:
    """Write one advice row per day in ``[start, end)``. Idempotent per user."""
    await session.execute(delete(DailyAdvice).where(DailyAdvice.user_id == user.id))

    currency = user.currency
    accounts = (
        await session.execute(select(Account).where(Account.user_id == user.id))
    ).scalars().all()
    opening = Money.sum((account.opening_balance for account in accounts), currency)

    confirmed = (
        await session.execute(
            select(Transaction).where(
                Transaction.user_id == user.id, Transaction.status == TXN_CONFIRMED
            )
        )
    ).scalars().all()
    spent_by_day: dict[date, int] = {}
    for txn in confirmed:
        spent_by_day[txn.occurred_on] = spent_by_day.get(txn.occurred_on, 0) + txn.amount.sen

    commitments = (
        await session.execute(select(Commitment).where(Commitment.user_id == user.id))
    ).scalars().all()
    goals = (
        await session.execute(select(Goal).where(Goal.user_id == user.id))
    ).scalars().all()
    goal_inputs = tuple(GoalInput(str(goal.id), goal.monthly) for goal in goals)

    written = 0
    # Anything confirmed before the window has already left the balance.
    running = sum(sen for on, sen in spent_by_day.items() if on < start)
    day = start
    while day < end:
        spent_today = spent_by_day.get(day, 0)
        running += spent_today
        cycle_start, next_payday = cycle_for(
            day, user.cycle_start, user.next_payday, user.cycle_days
        )
        snapshot = Snapshot(
            balance=opening - Money(running, currency),
            buffer=user.buffer,
            spent_today=Money(spent_today, currency),
            commitments=tuple(
                CommitmentInput(
                    str(commitment.id),
                    commitment.amount,
                    _due_in_cycle(commitment.due_date, cycle_start, user.cycle_days),
                )
                for commitment in commitments
            ),
            goals=goal_inputs,
            today=day,
            next_payday=next_payday,
            cycle_start=cycle_start,
            cycle_days=user.cycle_days,
            income=user.monthly_income,
        )
        session.add(
            DailyAdvice(
                user_id=user.id,
                on_date=day,
                safe_today=safe_to_spend(snapshot).safe_today,
                snapshot=snapshot_json(snapshot),
                source=ADVICE_SOURCE_SEED,
            )
        )
        written += 1
        day += timedelta(days=1)

    return written
