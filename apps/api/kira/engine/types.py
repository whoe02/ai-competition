"""Inputs and outputs of the finance engine. Plain data, no behaviour."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from kira.money import CurrencyMismatch, Money


@dataclass(frozen=True, slots=True)
class GoalInput:
    """A savings goal. ``monthly`` is its claim on the cycle; the rest is its arc.

    ``target``, ``saved`` and ``target_date`` default to empty so that
    ``safe_to_spend`` and every golden fixture — which know only about the
    monthly claim — construct this unchanged.
    """

    id: str
    monthly: Money
    target: Money = Money(0)
    saved: Money = Money(0)
    target_date: date | None = None


@dataclass(frozen=True, slots=True)
class CommitmentInput:
    """A known bill and the day it falls due."""

    id: str
    amount: Money
    due_date: date


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Everything the engine needs. Assembled by the caller; the engine reads no clock."""

    balance: Money
    buffer: Money
    spent_today: Money
    commitments: tuple[CommitmentInput, ...]
    goals: tuple[GoalInput, ...]
    today: date
    next_payday: date
    cycle_start: date
    cycle_days: int
    # What lands on each payday. Zero by default, so safe_to_spend and every
    # golden fixture — none of which look past the next payday — are untouched.
    income: Money = Money(0)

    def __post_init__(self) -> None:
        if self.cycle_days <= 0:
            raise ValueError("cycle_days must be positive")
        currency = self.balance.currency
        others = [self.buffer, self.spent_today, self.income]
        others += [c.amount for c in self.commitments]
        others += [g.monthly for g in self.goals]
        for amount in others:
            if amount.currency != currency:
                raise CurrencyMismatch(
                    f"snapshot mixes {currency} with {amount.currency}"
                )

    @property
    def currency(self) -> str:
        return self.balance.currency


@dataclass(frozen=True, slots=True)
class SafeToSpend:
    """The engine's answer, with every intermediate the UI shows in 'the working'."""

    days_to_payday: int
    cycle_elapsed: int
    balance: Money
    reserved: Money
    buffer: Money
    goal_reserve: Money
    unclaimed: Money
    per_day: Money
    spent_today: Money
    safe_today: Money


@dataclass(frozen=True, slots=True)
class DailySpendProfile:
    """What this user actually spends, by weekday. Observed amounts, integer sen.

    Not a distribution fitted to the data — the data itself, resampled. A user
    with three RM180 Sundays and one RM40 Sunday should see all four futures.
    """

    by_weekday: tuple[tuple[int, ...], ...]
    lookback_days: int
    # The same days in the order they happened. Spending is autocorrelated — a
    # heavy week follows a heavy week — and independent daily draws average that
    # away, which understates how wrong a plan can go. Empty means the caller
    # has only weekday buckets, and the simulation falls back to daily draws.
    series: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if len(self.by_weekday) != 7:
            raise ValueError("by_weekday must hold one tuple per weekday")
        for amounts in self.by_weekday:
            for amount in amounts:
                if isinstance(amount, bool) or not isinstance(amount, int):
                    raise TypeError("observed amounts are integer sen")
        for amount in self.series:
            if isinstance(amount, bool) or not isinstance(amount, int):
                raise TypeError("observed amounts are integer sen")

    @property
    def is_empty(self) -> bool:
        return all(len(amounts) == 0 for amounts in self.by_weekday)

    def median_for(self, weekday: int) -> int:
        """The middle observation, the upper of the two when the count is even."""
        amounts = sorted(self.by_weekday[weekday])
        if not amounts:
            return 0
        return amounts[len(amounts) // 2]


@dataclass(frozen=True, slots=True)
class ProjectionDay:
    on: date
    opening: Money
    income: Money
    commitments_due: Money
    expected_spend: Money
    goal_accrual: Money
    closing: Money


@dataclass(frozen=True, slots=True)
class Projection:
    """A path, and the band around it. The bands are empty for a median-only walk."""

    days: tuple[ProjectionDay, ...]
    p10: tuple[Money, ...] = ()
    p50: tuple[Money, ...] = ()
    p90: tuple[Money, ...] = ()


@dataclass(frozen=True, slots=True)
class GoalOutlook:
    """Whether a goal lands, as a share of simulated futures."""

    goal_id: str
    target_date: date
    probability_bp: int
    median_shortfall: Money

    def __post_init__(self) -> None:
        if not 0 <= self.probability_bp <= 10000:
            raise ValueError("probability_bp is basis points, 0..10000")


@dataclass(frozen=True, slots=True)
class Simulation:
    """What a Monte Carlo run answers: the bands, and a probability per goal."""

    bands: Projection
    outlooks: tuple[GoalOutlook, ...]
    trials: int
    seed: int


LEVER_KINDS = ("goal_monthly", "commitment_amount", "daily_spend")


@dataclass(frozen=True, slots=True)
class Lever:
    """One change to the plan, expressed as a delta. Negative means less."""

    kind: str
    target_id: str
    delta: Money

    def __post_init__(self) -> None:
        if self.kind not in LEVER_KINDS:
            raise ValueError(f"lever kind must be one of {LEVER_KINDS}, got {self.kind!r}")


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    lever: Lever
    outlooks: tuple[GoalOutlook, ...]
    safe_today_after: Money


@dataclass(frozen=True, slots=True)
class Driver:
    """A ranked change: what it costs, and what it buys, in basis points."""

    lever: Lever
    probability_bp_before: int
    probability_bp_after: int
    bp_per_ringgit: int


@dataclass(frozen=True, slots=True)
class AdviceRecord:
    """What Kira said on a day, and what actually happened."""

    on: date
    advised: Money
    actual: Money


@dataclass(frozen=True, slots=True)
class TrackRecord:
    """How Kira's advice actually did, over a stretch of days."""

    days: int
    followed: int
    follow_rate_bp: int
    mean_abs_deviation: Money
    counterfactual_gain: Money
