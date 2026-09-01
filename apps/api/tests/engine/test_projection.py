"""The median walk: where the money goes if nothing surprising happens."""

from datetime import date, timedelta

import pytest

from kira.engine.projection import project
from kira.engine.types import CommitmentInput, DailySpendProfile, GoalInput, Snapshot
from kira.money import Money

FLAT = DailySpendProfile(by_weekday=tuple((1000,) for _ in range(7)), lookback_days=90)
NOTHING = DailySpendProfile(by_weekday=tuple(() for _ in range(7)), lookback_days=0)


def snapshot(**overrides) -> Snapshot:
    fields = dict(
        balance=Money(100000),
        buffer=Money(0),
        spent_today=Money.zero(),
        commitments=(),
        goals=(),
        today=date(2026, 9, 3),
        next_payday=date(2026, 9, 25),
        cycle_start=date(2026, 8, 26),
        cycle_days=30,
        income=Money.zero(),
    )
    fields.update(overrides)
    return Snapshot(**fields)


def test_walks_one_day_per_horizon_day():
    result = project(snapshot(), FLAT, 30)
    assert len(result.days) == 30
    assert result.days[0].on == date(2026, 9, 4)
    assert result.days[-1].on == date(2026, 9, 3) + timedelta(days=30)


def test_spend_comes_off_the_balance_each_day():
    result = project(snapshot(), FLAT, 3)
    assert [d.closing.sen for d in result.days] == [99000, 98000, 97000]


def test_an_empty_profile_spends_nothing_rather_than_guessing():
    result = project(snapshot(), NOTHING, 3)
    assert [d.closing.sen for d in result.days] == [100000, 100000, 100000]


def test_a_commitment_lands_on_its_due_date_and_only_then():
    result = project(
        snapshot(commitments=(CommitmentInput("rent", Money(50000), date(2026, 9, 5)),)),
        FLAT,
        3,
    )
    assert [d.commitments_due.sen for d in result.days] == [0, 50000, 0]
    assert [d.closing.sen for d in result.days] == [99000, 48000, 47000]


def test_two_commitments_on_one_day_land_together():
    result = project(
        snapshot(
            commitments=(
                CommitmentInput("rent", Money(50000), date(2026, 9, 5)),
                CommitmentInput("phone", Money(8900), date(2026, 9, 5)),
            )
        ),
        NOTHING,
        3,
    )
    assert [d.commitments_due.sen for d in result.days] == [0, 58900, 0]


def test_income_arrives_on_payday_and_every_cycle_after():
    result = project(
        snapshot(income=Money(650000), next_payday=date(2026, 9, 5)), NOTHING, 40
    )
    paid = [d.on for d in result.days if d.income.sen > 0]
    assert paid == [date(2026, 9, 5), date(2026, 10, 5)]


def test_a_commitment_before_today_is_already_paid_and_does_not_land_again():
    result = project(
        snapshot(commitments=(CommitmentInput("old", Money(50000), date(2026, 8, 30)),)),
        NOTHING,
        3,
    )
    assert all(d.commitments_due.sen == 0 for d in result.days)


def test_goals_accrue_daily_at_their_monthly_rate():
    result = project(snapshot(goals=(GoalInput("g1", Money(30000)),)), NOTHING, 3)
    assert [d.goal_accrual.sen for d in result.days] == [1000, 1000, 1000]


def test_the_walk_is_a_pure_function_of_its_inputs():
    args = (snapshot(income=Money(650000)), FLAT, 45)
    assert project(*args) == project(*args)


def test_a_horizon_must_be_positive():
    with pytest.raises(ValueError):
        project(snapshot(), FLAT, 0)


def test_a_horizon_must_be_an_int():
    with pytest.raises(TypeError):
        project(snapshot(), FLAT, "90")


def test_a_commitment_recurs_every_cycle_across_the_horizon():
    """Rent is due every month. Charging it once would forecast a rent-free life."""
    result = project(
        snapshot(commitments=(CommitmentInput("rent", Money(120000), date(2026, 9, 5)),)),
        NOTHING,
        95,
    )
    landed = [d.on for d in result.days if d.commitments_due.sen > 0]
    assert landed == [date(2026, 9, 5), date(2026, 10, 5), date(2026, 11, 4), date(2026, 12, 4)]


def test_a_commitment_already_past_recurs_from_its_next_occurrence():
    result = project(
        snapshot(commitments=(CommitmentInput("old", Money(50000), date(2026, 8, 30)),)),
        NOTHING,
        35,
    )
    landed = [d.on for d in result.days if d.commitments_due.sen > 0]
    assert landed == [date(2026, 9, 29)]
