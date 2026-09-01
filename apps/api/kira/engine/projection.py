"""Where the money goes next. Pure: no I/O, no clock, no float.

``project`` walks the median path. ``simulate`` walks it many times with the
user's own observed variation and reports a band and a probability per goal.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from kira.engine.prng import Prng
from kira.engine.safe_to_spend import safe_to_spend
from kira.engine.types import (
    DailySpendProfile,
    Driver,
    GoalInput,
    GoalOutlook,
    Lever,
    Projection,
    ProjectionDay,
    ScenarioResult,
    Simulation,
    Snapshot,
)
from kira.money import Money, round_half_up


def _payday_dates(snapshot: Snapshot, days: int) -> frozenset[date]:
    """Payday, and every cycle length after it, within the horizon."""
    last = snapshot.today + timedelta(days=days)
    paydays: set[date] = set()
    when = snapshot.next_payday
    while when <= last:
        if when > snapshot.today:
            paydays.add(when)
        when += timedelta(days=snapshot.cycle_days)
    return frozenset(paydays)


def _daily_goal_accrual(snapshot: Snapshot) -> Money:
    """Each goal's monthly contribution, spread over the cycle and rounded once."""
    currency = snapshot.currency
    return Money.sum(
        (
            Money(round_half_up(goal.monthly.sen, snapshot.cycle_days), currency)
            for goal in snapshot.goals
        ),
        currency,
    )


def _commitments_by_day(snapshot: Snapshot, days: int) -> dict[date, Money]:
    """Every bill that falls inside the horizon, including the ones that recur.

    A commitment carries a single due date, because ``safe_to_spend`` never
    looks past one payday and so never had to decide. A projection does: rent
    is due every cycle, and charging it once would have the user living rent
    free for the rest of the horizon.
    """
    currency = snapshot.currency
    last = snapshot.today + timedelta(days=days)
    step = timedelta(days=snapshot.cycle_days)
    due: dict[date, Money] = {}
    for commitment in snapshot.commitments:
        when = commitment.due_date
        # Bills already behind us are paid; walk forward to the next occurrence.
        while when <= snapshot.today:
            when += step
        while when <= last:
            due[when] = due.get(when, Money.zero(currency)) + commitment.amount
            when += step
    return due


def project(snapshot: Snapshot, profile: DailySpendProfile, days: int) -> Projection:
    """The median path over ``days`` days, starting the day after ``snapshot.today``."""
    if isinstance(days, bool) or not isinstance(days, int):
        raise TypeError("days must be an int")
    if days <= 0:
        raise ValueError("days must be positive")

    currency = snapshot.currency
    paydays = _payday_dates(snapshot, days)
    accrual = _daily_goal_accrual(snapshot)
    due = _commitments_by_day(snapshot, days)

    walked: list[ProjectionDay] = []
    balance = snapshot.balance
    for step in range(1, days + 1):
        on = snapshot.today + timedelta(days=step)
        income = snapshot.income if on in paydays else Money.zero(currency)
        commitments_due = due.get(on, Money.zero(currency))
        spend = Money(profile.median_for(on.weekday()), currency)
        opening = balance
        balance = opening + income - commitments_due - spend
        walked.append(
            ProjectionDay(
                on=on,
                opening=opening,
                income=income,
                commitments_due=commitments_due,
                expected_spend=spend,
                goal_accrual=accrual,
                closing=balance,
            )
        )

    return Projection(days=tuple(walked))


DEFAULT_TRIALS = 2000
# One week: long enough to carry a payday-to-payday rhythm, short enough that
# ninety days of history still offer many distinct blocks to draw from.
_BLOCK_DAYS = 7
DEFAULT_SEED = 20260828

_P10, _P50, _P90 = 10, 50, 90


def _percentile(sorted_values: list[int], percentile: int) -> int:
    """The value at ``percentile`` of an ascending list, by nearest rank.

    Integer throughout: the index is rounded half-up, never divided.
    """
    if not sorted_values:
        return 0
    last = len(sorted_values) - 1
    return sorted_values[round_half_up(percentile * last, 100)]


def _datable_goals(snapshot: Snapshot, days: int) -> tuple[GoalInput, ...]:
    """Goals with a target date inside the horizon. Others get no probability:
    "will I make it" is not a question until there is a "by when"."""
    horizon_end = snapshot.today + timedelta(days=days)
    return tuple(
        goal
        for goal in snapshot.goals
        if goal.target_date is not None and snapshot.today < goal.target_date <= horizon_end
    )


def simulate(
    snapshot: Snapshot,
    profile: DailySpendProfile,
    days: int,
    trials: int = DEFAULT_TRIALS,
    seed: int = DEFAULT_SEED,
) -> Simulation:
    """Walk the horizon ``trials`` times, resampling this user's own spending.

    Each day's discretionary spend is drawn by integer index from what the user
    actually spent on that weekday — no fitted distribution, no assumption of
    symmetry, and no float anywhere in the arithmetic.

    Where the profile carries its chronology, the draw is a **block bootstrap**:
    a random run of consecutive observed days is replayed a week at a time, so
    the autocorrelation in real spending survives into the horizon instead of
    averaging out. Independent daily draws understate how wrong a plan can go.

    A goal is funded out of what is actually there: each day it takes its daily
    accrual from the balance above the buffer, less whatever this projection has
    already earmarked. Money set aside cannot be set aside twice, and a month
    that empties the account is a month the goal does not grow.
    """
    if isinstance(trials, bool) or not isinstance(trials, int):
        raise TypeError("trials must be an int")
    if trials <= 0:
        raise ValueError("trials must be positive")

    median = project(snapshot, profile, days)
    currency = snapshot.currency
    goals = _datable_goals(snapshot, days)
    accrual_for = {
        goal.id: round_half_up(goal.monthly.sen, snapshot.cycle_days) for goal in goals
    }
    buffer_sen = snapshot.buffer.sen

    closings: list[list[int]] = [[] for _ in range(days)]
    shortfalls: dict[str, list[int]] = {goal.id: [] for goal in goals}
    met: dict[str, int] = {goal.id: 0 for goal in goals}

    series = profile.series
    block = _BLOCK_DAYS if len(series) > _BLOCK_DAYS else 0

    stream = Prng(seed)
    for _ in range(trials):
        balance = snapshot.balance.sen
        saved = {goal.id: goal.saved.sen for goal in goals}
        earmarked = 0
        cursor = 0
        for index, day in enumerate(median.days):
            if block:
                if index % block == 0:
                    cursor = stream.below(len(series) - block + 1)
                spend = series[cursor + index % block]
            else:
                observed = profile.by_weekday[day.on.weekday()]
                spend = observed[stream.below(len(observed))] if observed else 0
            balance += day.income.sen - day.commitments_due.sen - spend
            closings[index].append(balance)

            for goal in goals:
                if day.on > goal.target_date:
                    continue
                available = balance - buffer_sen - earmarked
                if available <= 0:
                    continue
                take = min(accrual_for[goal.id], available)
                saved[goal.id] += take
                earmarked += take

        for goal in goals:
            gap = goal.target.sen - saved[goal.id]
            if gap <= 0:
                met[goal.id] += 1
                shortfalls[goal.id].append(0)
            else:
                shortfalls[goal.id].append(gap)

    for column in closings:
        column.sort()
    for values in shortfalls.values():
        values.sort()

    bands = Projection(
        days=median.days,
        p10=tuple(Money(_percentile(column, _P10), currency) for column in closings),
        p50=tuple(Money(_percentile(column, _P50), currency) for column in closings),
        p90=tuple(Money(_percentile(column, _P90), currency) for column in closings),
    )
    outlooks = tuple(
        GoalOutlook(
            goal_id=goal.id,
            target_date=goal.target_date,
            probability_bp=round_half_up(met[goal.id] * 10000, trials),
            median_shortfall=Money(_percentile(shortfalls[goal.id], _P50), currency),
        )
        for goal in goals
    )

    return Simulation(bands=bands, outlooks=outlooks, trials=trials, seed=seed)


def apply_lever(
    snapshot: Snapshot, profile: DailySpendProfile, lever: Lever
) -> tuple[Snapshot, DailySpendProfile]:
    """One change to the plan, returned as new inputs. Neither argument is mutated."""
    if lever.kind == "goal_monthly":
        if not any(goal.id == lever.target_id for goal in snapshot.goals):
            raise KeyError(f"no goal {lever.target_id!r}")
        goals = tuple(
            replace(goal, monthly=goal.monthly + lever.delta)
            if goal.id == lever.target_id
            else goal
            for goal in snapshot.goals
        )
        return replace(snapshot, goals=goals), profile

    if lever.kind == "commitment_amount":
        if not any(c.id == lever.target_id for c in snapshot.commitments):
            raise KeyError(f"no commitment {lever.target_id!r}")
        commitments = tuple(
            replace(c, amount=c.amount + lever.delta) if c.id == lever.target_id else c
            for c in snapshot.commitments
        )
        return replace(snapshot, commitments=commitments), profile

    # daily_spend: shift every observation, floored at zero. Spending less than
    # nothing is not a plan.
    shifted = tuple(
        tuple(max(0, amount + lever.delta.sen) for amount in day)
        for day in profile.by_weekday
    )
    shifted_series = tuple(max(0, amount + lever.delta.sen) for amount in profile.series)
    return snapshot, replace(profile, by_weekday=shifted, series=shifted_series)


def run_scenarios(
    snapshot: Snapshot,
    profile: DailySpendProfile,
    levers: tuple[Lever, ...],
    days: int,
    trials: int = DEFAULT_TRIALS,
    seed: int = DEFAULT_SEED,
) -> tuple[ScenarioResult, ...]:
    """Each lever, simulated under the same seed so only the lever differs.

    Two runs that differed by noise as well as by the change would not be a
    comparison.
    """
    results: list[ScenarioResult] = []
    for lever in levers:
        moved_snapshot, moved_profile = apply_lever(snapshot, profile, lever)
        simulation = simulate(moved_snapshot, moved_profile, days, trials=trials, seed=seed)
        results.append(
            ScenarioResult(
                lever=lever,
                outlooks=simulation.outlooks,
                safe_today_after=safe_to_spend(moved_snapshot).safe_today,
            )
        )
    return tuple(results)


def _probability_for(outlooks: tuple[GoalOutlook, ...], goal_id: str) -> int | None:
    for outlook in outlooks:
        if outlook.goal_id == goal_id:
            return outlook.probability_bp
    return None


def drivers(
    snapshot: Snapshot,
    profile: DailySpendProfile,
    goal_id: str,
    candidates: tuple[Lever, ...],
    days: int,
    trials: int = DEFAULT_TRIALS,
    seed: int = DEFAULT_SEED,
) -> tuple[Driver, ...]:
    """Rank candidate changes by basis points of probability bought per ringgit.

    Per-ringgit rather than absolute on purpose: "put another RM500 a month in"
    is true, and useless.
    """
    baseline = simulate(snapshot, profile, days, trials=trials, seed=seed)
    before = _probability_for(baseline.outlooks, goal_id)
    if before is None:
        return ()

    ranked: list[Driver] = []
    for lever in candidates:
        moved_snapshot, moved_profile = apply_lever(snapshot, profile, lever)
        after = _probability_for(
            simulate(moved_snapshot, moved_profile, days, trials=trials, seed=seed).outlooks,
            goal_id,
        )
        if after is None:
            continue
        ringgit = abs(lever.delta.sen) // 100
        ranked.append(
            Driver(
                lever=lever,
                probability_bp_before=before,
                probability_bp_after=after,
                bp_per_ringgit=(after - before) // ringgit if ringgit else 0,
            )
        )

    return tuple(sorted(ranked, key=lambda driver: driver.bp_per_ringgit, reverse=True))
