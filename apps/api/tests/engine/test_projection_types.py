"""The new vocabulary, and the promise that adding it broke nothing."""

from datetime import date

import pytest

from kira.engine.types import (
    CommitmentInput,
    DailySpendProfile,
    GoalInput,
    Lever,
    Snapshot,
)
from kira.money import CurrencyMismatch, Money


def test_goal_input_still_builds_from_id_and_monthly_alone():
    """Six golden fixtures construct it exactly this way."""
    goal = GoalInput("g1", Money(27000))
    assert goal.target == Money.zero()
    assert goal.saved == Money.zero()
    assert goal.target_date is None


def test_goal_input_carries_a_target_and_a_date():
    goal = GoalInput("g2", Money(52500), Money(800000), Money(329000), date(2027, 6, 1))
    assert goal.target.sen == 800000
    assert goal.target_date == date(2027, 6, 1)


def base_snapshot(**overrides) -> Snapshot:
    fields = dict(
        balance=Money(418040),
        buffer=Money(80000),
        spent_today=Money.zero(),
        commitments=(CommitmentInput("rent", Money(120000), date(2026, 9, 5)),),
        goals=(GoalInput("g1", Money(27000)),),
        today=date(2026, 9, 3),
        next_payday=date(2026, 9, 25),
        cycle_start=date(2026, 8, 26),
        cycle_days=30,
    )
    fields.update(overrides)
    return Snapshot(**fields)


def test_income_defaults_to_zero_so_existing_callers_are_untouched():
    assert base_snapshot().income == Money.zero()


def test_income_must_match_the_snapshot_currency():
    with pytest.raises(CurrencyMismatch):
        base_snapshot(income=Money(650000, "SGD"))


def test_profile_reports_whether_it_has_anything_to_say():
    empty = DailySpendProfile(by_weekday=tuple(() for _ in range(7)), lookback_days=0)
    assert empty.is_empty
    lived = DailySpendProfile(
        by_weekday=tuple((1500, 2000) for _ in range(7)), lookback_days=90
    )
    assert not lived.is_empty
    assert lived.median_for(0) == 2000


def test_the_median_of_nothing_is_nothing_rather_than_a_guess():
    empty = DailySpendProfile(by_weekday=tuple(() for _ in range(7)), lookback_days=0)
    assert empty.median_for(3) == 0


def test_profile_rejects_a_shape_that_is_not_seven_weekdays():
    with pytest.raises(ValueError):
        DailySpendProfile(by_weekday=((1500,), (1600,)), lookback_days=14)


def test_profile_rejects_an_observation_that_is_not_integer_sen():
    with pytest.raises(TypeError):
        DailySpendProfile(
            by_weekday=tuple((15.5,) for _ in range(7)), lookback_days=14
        )


def test_lever_kind_is_checked():
    with pytest.raises(ValueError):
        Lever(kind="sell_the_car", target_id="g1", delta=Money(1000))


def test_a_probability_outside_basis_points_is_refused():
    from kira.engine.types import GoalOutlook

    with pytest.raises(ValueError):
        GoalOutlook("g1", date(2026, 12, 1), 10001, Money.zero())
