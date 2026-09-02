from datetime import date

import pytest

from kira.engine import safe_to_spend
from kira.engine.types import CommitmentInput, GoalInput, Snapshot
from kira.money import CurrencyMismatch, Money

TODAY = date(2026, 9, 3)
PAYDAY = date(2026, 9, 25)
CYCLE_START = date(2026, 8, 26)

DEMO_COMMITMENTS = (
    CommitmentInput("rent", Money(120000), date(2026, 9, 5)),
    CommitmentInput("phone", Money(8900), date(2026, 9, 8)),
    CommitmentInput("loan", Money(52000), date(2026, 9, 10)),
    CommitmentInput("sub", Money(5500), date(2026, 9, 14)),
    CommitmentInput("net", Money(13900), date(2026, 9, 18)),
)

DEMO_GOALS = (
    GoalInput("g1", Money(27000)),
    GoalInput("g2", Money(52500)),
)


def snapshot(**overrides) -> Snapshot:
    base = dict(
        balance=Money(418040),
        buffer=Money(80000),
        spent_today=Money(0),
        commitments=DEMO_COMMITMENTS,
        goals=DEMO_GOALS,
        today=TODAY,
        next_payday=PAYDAY,
        cycle_start=CYCLE_START,
        cycle_days=30,
    )
    base.update(overrides)
    return Snapshot(**base)


class TestDemoBaseline:
    def test_matches_the_prototype_numbers(self):
        r = safe_to_spend(snapshot())
        assert r.days_to_payday == 22
        assert r.cycle_elapsed == 8
        assert r.reserved == Money(200300)
        assert r.goal_reserve == Money(21200)
        assert r.unclaimed == Money(116540)
        assert r.per_day == Money(5297)
        assert r.safe_today == Money(5297)


class TestCommitmentWindow:
    def test_commitment_due_after_payday_is_not_reserved(self):
        later = DEMO_COMMITMENTS[:-1] + (
            CommitmentInput("net", Money(13900), date(2026, 9, 30)),
        )
        r = safe_to_spend(snapshot(commitments=later))
        assert r.reserved == Money(186400)

    def test_commitment_due_on_payday_is_not_reserved(self):
        on_payday = (CommitmentInput("rent", Money(120000), PAYDAY),)
        r = safe_to_spend(snapshot(commitments=on_payday))
        assert r.reserved == Money.zero()

    def test_commitment_already_past_is_still_reserved(self):
        # Week 1 has no payment tracking; anything dated before payday is held.
        past = (CommitmentInput("rent", Money(120000), date(2026, 9, 1)),)
        r = safe_to_spend(snapshot(commitments=past))
        assert r.reserved == Money(120000)


class TestGoalReserve:
    def test_accrues_only_the_elapsed_part_of_the_cycle(self):
        r = safe_to_spend(snapshot(goals=(GoalInput("g", Money(30000)),)))
        # 30000 * 8 / 30 = 8000
        assert r.goal_reserve == Money(8000)

    def test_rounds_halves_up(self):
        r = safe_to_spend(
            snapshot(
                goals=(GoalInput("g", Money(100)),),
                cycle_start=date(2026, 8, 31),  # 3 days elapsed
                cycle_days=8,
            )
        )
        # 100 * 3 / 8 = 37.5 -> 38
        assert r.goal_reserve == Money(38)

    def test_rounds_each_goal_separately_and_once(self):
        r = safe_to_spend(
            snapshot(
                goals=(GoalInput("a", Money(100)), GoalInput("b", Money(100))),
                cycle_start=date(2026, 8, 31),
                cycle_days=8,
            )
        )
        assert r.goal_reserve == Money(76)

    def test_no_goals_reserves_nothing(self):
        assert safe_to_spend(snapshot(goals=())).goal_reserve == Money.zero()

    def test_confirmed_contribution_is_reserved_without_double_accruing_today(self):
        r = safe_to_spend(
            snapshot(
                goals=(
                    GoalInput(
                        "g",
                        Money(30_000),
                        last_contributed_on=TODAY,
                    ),
                ),
                contributed_goal_reserve=Money(10_000),
            )
        )
        assert r.goal_reserve == Money(10_000)

    def test_cycle_elapsed_is_clamped_to_the_cycle_length(self):
        r = safe_to_spend(snapshot(cycle_start=date(2026, 6, 1)))
        assert r.cycle_elapsed == 30
        assert r.goal_reserve == Money(79500)

    def test_cycle_elapsed_is_never_negative(self):
        r = safe_to_spend(snapshot(cycle_start=date(2026, 9, 10)))
        assert r.cycle_elapsed == 0
        assert r.goal_reserve == Money.zero()


class TestSpentToday:
    def test_spending_reduces_the_room_left(self):
        r = safe_to_spend(snapshot(spent_today=Money(1890)))
        assert r.safe_today == Money(3407)

    def test_overspending_floors_at_zero(self):
        r = safe_to_spend(snapshot(spent_today=Money(6000)))
        assert r.per_day == Money(5297)
        assert r.safe_today == Money.zero()


class TestDeficit:
    def test_negative_unclaimed_floors_toward_negative_infinity(self):
        r = safe_to_spend(snapshot(balance=Money(100000)))
        assert r.unclaimed == Money(-201500)
        assert r.per_day == Money(-9160)
        assert r.safe_today == Money.zero()


class TestDaysToPayday:
    def test_payday_today_still_divides_by_one_day(self):
        r = safe_to_spend(snapshot(next_payday=TODAY, commitments=(), goals=()))
        assert r.days_to_payday == 1
        assert r.per_day == Money(338040)

    def test_payday_in_the_past_still_divides_by_one_day(self):
        r = safe_to_spend(snapshot(next_payday=date(2026, 9, 1), commitments=(), goals=()))
        assert r.days_to_payday == 1


class TestDeterminism:
    def test_same_input_gives_the_same_result(self):
        assert safe_to_spend(snapshot()) == safe_to_spend(snapshot())


class TestValidation:
    def test_mixed_currencies_are_rejected_at_construction(self):
        with pytest.raises(CurrencyMismatch):
            snapshot(buffer=Money(80000, "SGD"))

    def test_cycle_days_must_be_positive(self):
        with pytest.raises(ValueError):
            snapshot(cycle_days=0)
