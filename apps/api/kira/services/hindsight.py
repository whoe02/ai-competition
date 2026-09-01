"""Kira's own track record: what she advised, against what actually happened.

Every number here comes from a ``daily_advice`` row — the exact snapshot she
advised from, persisted that morning — never from a reconstruction. Recomputing
a past day's advice from today's data would silently use today's goals and
commitments, and would flatter her.

The service does no arithmetic of its own: the scoring is
``engine.advice.score_advice`` and the counterfactual probability is a second
run of the same simulation the forecast uses.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import TXN_CONFIRMED, Commitment, DailyAdvice, Transaction, User
from kira.engine import safe_to_spend
from kira.engine.advice import score_advice
from kira.engine.projection import simulate
from kira.engine.types import AdviceRecord, TrackRecord
from kira.money import Money
from kira.services.advice import snapshot_from_json
from kira.services.behaviour import build_profile
from kira.services.foresight import DEFAULT_HORIZON_DAYS
from kira.services.snapshot import load_snapshot

DEFAULT_WINDOW_DAYS = 90
MAX_WINDOW_DAYS = 365

# The counterfactual is a comparison of two runs, not a headline band, so it
# runs at the leaner trial count for the same reason ranking does.
COUNTERFACTUAL_TRIALS = 500


@dataclass(frozen=True, slots=True)
class HindsightResult:
    window_days: int
    record: TrackRecord
    days: tuple[AdviceRecord, ...]
    goal_id: str | None
    probability_bp_now: int | None
    probability_bp_if_followed: int | None
    assumption: str


def _advised(row: DailyAdvice, currency: str) -> Money:
    """The day's allowance as Kira set it, before that day's spending.

    ``safe_today`` is stored after subtracting whatever had already been spent
    when the row was written, and the seed writes it from the whole day. Scoring
    the day against that number would score the user against their own spending.
    The stored snapshot is what makes the honest number recoverable: run the same
    engine over it with the day's spend removed.
    """
    snapshot = snapshot_from_json(row.snapshot, currency)
    return safe_to_spend(replace(snapshot, spent_today=Money.zero(currency))).safe_today


async def _actual_by_day(
    session: AsyncSession, user: User, start: date, end: date
) -> dict[date, int]:
    """Discretionary spend per day. Bills are excluded, as they are from the advice.

    ``safe_today`` reserves every commitment due before payday, so charging a
    rent payment against it would report a user who blew RM1,200 on rent day.
    """
    commitment_names = {
        name.strip().lower()
        for name in (
            await session.execute(select(Commitment.name).where(Commitment.user_id == user.id))
        )
        .scalars()
        .all()
    }
    rows = (
        await session.execute(
            select(Transaction).where(
                Transaction.user_id == user.id,
                Transaction.status == TXN_CONFIRMED,
                Transaction.occurred_on >= start,
                Transaction.occurred_on < end,
            )
        )
    ).scalars().all()

    totals: dict[date, int] = {}
    for row in rows:
        if row.merchant.strip().lower() in commitment_names:
            continue
        totals[row.occurred_on] = totals.get(row.occurred_on, 0) + row.amount.sen
    return totals


async def _counterfactual(
    session: AsyncSession, user: User, today: date, gain: Money
) -> tuple[str | None, int | None, int | None]:
    """The nearest dated goal's probability now, and with the gain in the balance.

    Both runs share a seed and a profile, so the two differ by the money and not
    by noise — the same rule the scenario comparison follows.
    """
    snapshot = await load_snapshot(session, user, today)
    profile = await build_profile(session, user, today)
    now = simulate(snapshot, profile, days=DEFAULT_HORIZON_DAYS, trials=COUNTERFACTUAL_TRIALS)
    if not now.outlooks:
        return None, None, None
    goal_id = now.outlooks[0].goal_id
    if gain.sen == 0:
        probability = now.outlooks[0].probability_bp
        return goal_id, probability, probability

    followed = simulate(
        replace(snapshot, balance=snapshot.balance + gain),
        profile,
        days=DEFAULT_HORIZON_DAYS,
        trials=COUNTERFACTUAL_TRIALS,
    )
    after = next(
        (outlook.probability_bp for outlook in followed.outlooks if outlook.goal_id == goal_id),
        None,
    )
    return goal_id, now.outlooks[0].probability_bp, after


async def hindsight(
    session: AsyncSession,
    user: User,
    today: date,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> HindsightResult:
    """Score every advised day in the window, and price what following would buy."""
    if window_days <= 0 or window_days > MAX_WINDOW_DAYS:
        raise ValueError(f"window_days must be in 1..{MAX_WINDOW_DAYS}")

    start = today - timedelta(days=window_days)
    currency = user.currency
    rows = (
        await session.execute(
            select(DailyAdvice)
            .where(
                DailyAdvice.user_id == user.id,
                DailyAdvice.on_date >= start,
                # Today is still being lived. A day is scored once it is over.
                DailyAdvice.on_date < today,
            )
            .order_by(DailyAdvice.on_date)
        )
    ).scalars().all()

    actual = await _actual_by_day(session, user, start, today)
    records = tuple(
        AdviceRecord(
            on=row.on_date,
            advised=_advised(row, currency),
            actual=Money(actual.get(row.on_date, 0), currency),
        )
        for row in rows
    )
    record = score_advice(records)
    goal_id, before, after = await _counterfactual(
        session, user, today, record.counterfactual_gain
    )

    return HindsightResult(
        window_days=window_days,
        record=record,
        days=records,
        goal_id=goal_id,
        probability_bp_now=before,
        probability_bp_if_followed=after,
        assumption=(
            "Scored against your confirmed spending on each of those days. "
            "Bills Kira had already set aside are not counted against the number."
        ),
    )
