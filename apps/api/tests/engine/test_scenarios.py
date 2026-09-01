"""What one change is worth, measured against the same futures."""

from datetime import date

import pytest

from kira.engine.projection import apply_lever, drivers, run_scenarios
from kira.engine.types import CommitmentInput, DailySpendProfile, GoalInput, Lever, Snapshot
from kira.money import Money

VARIED = DailySpendProfile(
    by_weekday=tuple((500, 1500, 2500) for _ in range(7)), lookback_days=90
)

# The seeded demo picture, where the emergency top-up is genuinely marginal.
DEMO_PROFILE = DailySpendProfile(
    by_weekday=(
        (1380, 1150, 2530), (3000, 1090, 4090), (1690, 1420, 3110), (1250, 890, 2140),
        (2350, 4200, 1980), (9000, 3560, 12560), (18040, 18040, 9020),
    ),
    lookback_days=90,
)
DEMO = Snapshot(
    balance=Money(418040),
    buffer=Money(80000),
    spent_today=Money.zero(),
    commitments=(
        CommitmentInput("rent", Money(120000), date(2026, 9, 5)),
        CommitmentInput("sub", Money(5500), date(2026, 9, 14)),
    ),
    goals=(GoalInput("g1", Money(27000), Money(250000), Money(115000), date(2027, 1, 29)),),
    today=date(2026, 9, 3),
    next_payday=date(2026, 9, 25),
    cycle_start=date(2026, 8, 26),
    cycle_days=30,
    income=Money(450000),
)


def snapshot(**overrides) -> Snapshot:
    fields = dict(
        balance=Money(300000),
        buffer=Money(0),
        spent_today=Money.zero(),
        commitments=(CommitmentInput("sub", Money(5500), date(2026, 9, 14)),),
        goals=(GoalInput("g1", Money(50000), Money(400000), Money(100000), date(2026, 12, 1)),),
        today=date(2026, 9, 3),
        next_payday=date(2026, 9, 25),
        cycle_start=date(2026, 8, 26),
        cycle_days=30,
        income=Money(650000),
    )
    fields.update(overrides)
    return Snapshot(**fields)


class TestApplyLever:
    def test_a_goal_lever_changes_the_monthly_contribution(self):
        moved, _ = apply_lever(snapshot(), VARIED, Lever("goal_monthly", "g1", Money(4000)))
        assert moved.goals[0].monthly.sen == 54000

    def test_a_commitment_lever_changes_that_commitment_only(self):
        moved, _ = apply_lever(
            snapshot(), VARIED, Lever("commitment_amount", "sub", Money(-5500))
        )
        assert moved.commitments[0].amount.sen == 0

    def test_a_daily_spend_lever_shifts_every_observation(self):
        _, profile = apply_lever(snapshot(), VARIED, Lever("daily_spend", "all", Money(-500)))
        assert profile.by_weekday[0] == (0, 1000, 2000)

    def test_a_daily_spend_lever_never_pushes_an_observation_below_zero(self):
        _, profile = apply_lever(snapshot(), VARIED, Lever("daily_spend", "all", Money(-9999)))
        assert profile.by_weekday[0] == (0, 0, 0)

    def test_a_daily_spend_lever_shifts_the_chronology_used_by_block_bootstrap(self):
        profile = DailySpendProfile(
            by_weekday=tuple((1000,) for _ in range(7)),
            lookback_days=14,
            series=(1000,) * 14,
        )
        _, moved = apply_lever(snapshot(), profile, Lever("daily_spend", "all", Money(-500)))
        assert moved.series == (500,) * 14

    def test_neither_argument_is_mutated(self):
        original = snapshot()
        apply_lever(original, VARIED, Lever("goal_monthly", "g1", Money(4000)))
        assert original.goals[0].monthly.sen == 50000
        assert VARIED.by_weekday[0] == (500, 1500, 2500)

    def test_an_unknown_target_is_an_error_rather_than_a_silent_no_op(self):
        with pytest.raises(KeyError):
            apply_lever(snapshot(), VARIED, Lever("goal_monthly", "nope", Money(1000)))

    def test_an_unknown_commitment_is_an_error_too(self):
        with pytest.raises(KeyError):
            apply_lever(snapshot(), VARIED, Lever("commitment_amount", "nope", Money(1000)))


class TestRunScenarios:
    def test_one_result_per_lever(self):
        results = run_scenarios(
            DEMO,
            DEMO_PROFILE,
            (
                Lever("goal_monthly", "g1", Money(4000)),
                Lever("daily_spend", "all", Money(-500)),
            ),
            days=180,
            trials=200,
            seed=5,
        )
        assert len(results) == 2
        assert [r.lever.kind for r in results] == ["goal_monthly", "daily_spend"]

    def test_no_levers_is_no_results(self):
        assert run_scenarios(DEMO, DEMO_PROFILE, (), days=180, trials=200, seed=5) == ()

    def test_paying_more_into_a_goal_raises_its_probability(self):
        results = run_scenarios(
            DEMO,
            DEMO_PROFILE,
            (Lever("goal_monthly", "g1", Money(0)), Lever("goal_monthly", "g1", Money(4000))),
            days=180,
            trials=300,
            seed=13,
        )
        before, after = results[0].outlooks[0], results[1].outlooks[0]
        assert after.probability_bp > before.probability_bp

    def test_scenarios_are_compared_under_one_set_of_futures(self):
        """Same seed, so the difference is the lever and not the noise."""
        lever = Lever("goal_monthly", "g1", Money(10000))
        first, second = run_scenarios(
            DEMO, DEMO_PROFILE, (lever, lever), days=180, trials=200, seed=9
        )
        assert first.outlooks == second.outlooks

    def test_a_scenario_reports_what_today_would_become(self):
        richer, leaner = run_scenarios(
            DEMO,
            DEMO_PROFILE,
            (Lever("goal_monthly", "g1", Money(0)), Lever("goal_monthly", "g1", Money(30000))),
            days=180,
            trials=100,
            seed=9,
        )
        assert leaner.safe_today_after < richer.safe_today_after


class TestDrivers:
    def test_ranked_by_probability_bought_per_ringgit(self):
        candidates = (
            Lever("goal_monthly", "g1", Money(4000)),
            Lever("goal_monthly", "g1", Money(20000)),
        )
        ranked = drivers(DEMO, DEMO_PROFILE, "g1", candidates, days=180, trials=200, seed=4)
        assert len(ranked) == 2
        assert ranked[0].bp_per_ringgit >= ranked[1].bp_per_ringgit
        assert {d.probability_bp_before for d in ranked} == {ranked[0].probability_bp_before}

    def test_a_driver_reports_what_it_buys(self):
        ranked = drivers(
            DEMO, DEMO_PROFILE, "g1", (Lever("goal_monthly", "g1", Money(4000)),),
            days=180, trials=200, seed=4,
        )
        assert ranked[0].probability_bp_after > ranked[0].probability_bp_before
        assert ranked[0].bp_per_ringgit > 0

    def test_a_driver_that_buys_nothing_is_still_reported_honestly(self):
        ranked = drivers(
            DEMO, DEMO_PROFILE, "g1", (Lever("goal_monthly", "g1", Money(0)),),
            days=180, trials=100, seed=4,
        )
        assert ranked[0].bp_per_ringgit == 0

    def test_drivers_for_an_unknown_goal_is_empty(self):
        ranked = drivers(
            DEMO, DEMO_PROFILE, "missing", (Lever("goal_monthly", "g1", Money(1000)),),
            days=180, trials=50, seed=4,
        )
        assert ranked == ()
