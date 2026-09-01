"""The forecast, assembled. Computed on read; nothing here is cached.

``safe_to_spend`` is a pure function of a snapshot and so is this. There is no
materialised column and no invalidation logic, which is why the entire class of
stale-derived-value bugs does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import Commitment, User
from kira.engine.projection import drivers as rank_drivers
from kira.engine.projection import run_scenarios, simulate
from kira.engine.types import Driver, Lever, ScenarioResult, Simulation, Snapshot
from kira.money import Money
from kira.services.behaviour import DEFAULT_LOOKBACK_DAYS, build_profile
from kira.services.snapshot import load_snapshot

MAX_HORIZON_DAYS = 365
DEFAULT_HORIZON_DAYS = 180

# Ranking re-simulates once per candidate, so it runs leaner than the headline
# band: twelve runs at the full trial count would cost over a second. The band
# is what the user reads; the ranking only has to get the order right.
DRIVER_TRIALS = 500

# The changes Kira is willing to propose, as deltas. Deliberately modest: a
# driver reading "put another RM500 a month in" is true and useless.
GOAL_STEPS = (4000, 10000, 20000)
SPEND_STEPS = (-500, -1500)


@dataclass(frozen=True, slots=True)
class ForesightResult:
    horizon_days: int
    bands: Simulation
    drivers: tuple[Driver, ...]
    profile_days: int
    assumption: str


def candidate_levers(
    snapshot: Snapshot, protected_ids: frozenset[str] = frozenset()
) -> tuple[Lever, ...]:
    """Every change worth simulating, and nothing the user has ruled out."""
    currency = snapshot.currency
    levers: list[Lever] = []
    for goal in snapshot.goals:
        for step in GOAL_STEPS:
            levers.append(Lever("goal_monthly", goal.id, Money(step, currency)))
    for commitment in snapshot.commitments:
        if commitment.id in protected_ids:
            continue
        levers.append(Lever("commitment_amount", commitment.id, -commitment.amount))
    for step in SPEND_STEPS:
        levers.append(Lever("daily_spend", "all", Money(step, currency)))
    return tuple(levers)


async def _protected_ids(session: AsyncSession, user: User) -> frozenset[str]:
    rows = (
        await session.execute(
            select(Commitment.id).where(
                Commitment.user_id == user.id, Commitment.protected.is_(True)
            )
        )
    ).scalars().all()
    return frozenset(str(row) for row in rows)


def _check_horizon(horizon_days: int) -> None:
    if horizon_days <= 0 or horizon_days > MAX_HORIZON_DAYS:
        raise ValueError(f"horizon_days must be in 1..{MAX_HORIZON_DAYS}")


async def foresight(
    session: AsyncSession,
    user: User,
    today: date,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    driver_goal_id: str | None = None,
) -> ForesightResult:
    """The band, the probabilities, and the changes that move the first of them."""
    _check_horizon(horizon_days)
    snapshot = await load_snapshot(session, user, today)
    profile = await build_profile(session, user, today)
    simulation = simulate(snapshot, profile, horizon_days)

    selected_outlook = next(
        (outlook for outlook in simulation.outlooks if outlook.goal_id == driver_goal_id),
        None,
    )
    if driver_goal_id is None and simulation.outlooks:
        selected_outlook = simulation.outlooks[0]

    ranked: tuple[Driver, ...] = ()
    if selected_outlook is not None:
        candidates = candidate_levers(snapshot, await _protected_ids(session, user))
        ranked = rank_drivers(
            snapshot,
            profile,
            selected_outlook.goal_id,
            candidates,
            horizon_days,
            trials=DRIVER_TRIALS,
        )

    return ForesightResult(
        horizon_days=horizon_days,
        bands=simulation,
        drivers=ranked,
        profile_days=profile.lookback_days,
        assumption=(
            f"Based on your last {DEFAULT_LOOKBACK_DAYS} days of confirmed spending. "
            "It is a projection, not a promise."
        ),
    )


async def compare(
    session: AsyncSession,
    user: User,
    today: date,
    levers: tuple[Lever, ...],
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> tuple[ScenarioResult, ...]:
    _check_horizon(horizon_days)
    snapshot = await load_snapshot(session, user, today)
    profile = await build_profile(session, user, today)
    return run_scenarios(snapshot, profile, levers, horizon_days, trials=DRIVER_TRIALS)
