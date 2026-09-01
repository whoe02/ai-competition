"""The overnight signals are deterministic, pure checks — never a model hunch."""

from datetime import date

from kira.engine.detectors import (
    buffer_breach_ahead,
    commitment_due_unfunded,
    goal_probability_dropped,
    spend_pattern_anomaly,
    unconfirmed_drafts_piling,
)
from kira.engine.types import CommitmentInput, GoalOutlook, Projection, Snapshot
from kira.money import Money


def snapshot(**overrides) -> Snapshot:
    fields = dict(
        balance=Money(100000),
        buffer=Money(80000),
        spent_today=Money.zero(),
        commitments=(CommitmentInput("rent", Money(40000), date(2026, 9, 5)),),
        goals=(),
        today=date(2026, 9, 3),
        next_payday=date(2026, 9, 25),
        cycle_start=date(2026, 8, 26),
        cycle_days=30,
        income=Money(400000),
    )
    fields.update(overrides)
    return Snapshot(**fields)


def test_buffer_breach_names_the_first_day_the_cautious_band_breaks_the_buffer():
    bands = Projection(
        days=(),
        p10=(Money(95000), Money(79000)),
        p50=(Money(110000), Money(100000)),
        p90=(Money(120000), Money(140000)),
    )
    hit = buffer_breach_ahead(bands, Money(80000), date(2026, 9, 4))
    assert hit is not None
    assert hit.kind == "buffer_breach_ahead"
    assert "2026-09-05" in hit.detail


def test_a_goal_only_counts_as_dropped_when_it_loses_material_probability():
    current = GoalOutlook("goal", date(2026, 12, 1), 5400, Money(30000))
    assert goal_probability_dropped("goal", 5900, current) is not None
    assert goal_probability_dropped("goal", 5500, current) is None


def test_drafts_piling_up_has_a_small_deliberate_threshold():
    assert unconfirmed_drafts_piling(1) is None
    hit = unconfirmed_drafts_piling(2)
    assert hit is not None
    assert hit.kind == "unconfirmed_drafts_piling"


def test_spending_anomaly_compares_actual_to_the_users_own_pattern():
    assert spend_pattern_anomaly(Money(2000), Money(1500)) is None
    hit = spend_pattern_anomaly(Money(5000), Money(1500))
    assert hit is not None
    assert hit.kind == "spend_pattern_anomaly"


def test_an_unfunded_commitment_is_flagged_without_attempting_to_pay_it():
    hit = commitment_due_unfunded(snapshot())
    assert hit is not None
    assert hit.kind == "commitment_due_unfunded"
    assert commitment_due_unfunded(snapshot(balance=Money(200000))) is None
