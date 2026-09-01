"""Turns the confirmed ledger into the shape the forecast resamples.

A day is one observation, including the days nothing was spent — dropping the
quiet days would forecast a life the user does not live.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import TXN_CONFIRMED, Commitment, Transaction, User
from kira.engine.types import DailySpendProfile

DEFAULT_LOOKBACK_DAYS = 90


async def build_profile(
    session: AsyncSession,
    user: User,
    today: date,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> DailySpendProfile:
    """What this user spends, by weekday, over the days before ``today``."""
    start = today - timedelta(days=lookback_days)

    commitment_names = {
        name.strip().lower()
        for name in (
            await session.execute(
                select(Commitment.name).where(Commitment.user_id == user.id)
            )
        ).scalars().all()
    }

    rows = (
        await session.execute(
            select(Transaction).where(
                Transaction.user_id == user.id,
                Transaction.status == TXN_CONFIRMED,
                Transaction.occurred_on >= start,
                Transaction.occurred_on < today,
            )
        )
    ).scalars().all()

    totals: dict[date, int] = {}
    day = start
    while day < today:
        totals[day] = 0
        day += timedelta(days=1)

    for row in rows:
        # The projection lands commitments on their due dates itself; a matching
        # ledger row would otherwise be spent twice.
        if row.merchant.strip().lower() in commitment_names:
            continue
        totals[row.occurred_on] = totals.get(row.occurred_on, 0) + row.amount.sen

    buckets: list[list[int]] = [[] for _ in range(7)]
    ordered = sorted(totals.items())
    for on, total in ordered:
        buckets[on.weekday()].append(total)

    return DailySpendProfile(
        by_weekday=tuple(tuple(bucket) for bucket in buckets),
        lookback_days=lookback_days,
        series=tuple(total for _, total in ordered),
    )
