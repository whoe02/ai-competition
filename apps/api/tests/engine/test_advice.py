"""Kira grading her own past advice. The arithmetic, not the wording."""

from datetime import date, timedelta

from kira.engine.advice import score_advice
from kira.engine.types import AdviceRecord
from kira.money import Money


def records(*pairs: tuple[int, int]) -> tuple[AdviceRecord, ...]:
    start = date(2026, 6, 5)
    return tuple(
        AdviceRecord(start + timedelta(days=i), Money(advised), Money(actual))
        for i, (advised, actual) in enumerate(pairs)
    )


def test_no_records_is_an_empty_record_rather_than_a_crash():
    result = score_advice(())
    assert result.days == 0
    assert result.follow_rate_bp == 0
    assert result.counterfactual_gain == Money.zero()


def test_spending_at_or_under_the_number_counts_as_following_it():
    result = score_advice(records((5000, 5000), (5000, 4000), (5000, 6000)))
    assert result.days == 3
    assert result.followed == 2
    assert result.follow_rate_bp == 6667


def test_deviation_is_absolute_so_underspending_is_not_free_credit():
    result = score_advice(records((5000, 3000), (5000, 7000)))
    assert result.mean_abs_deviation.sen == 2000


def test_the_counterfactual_counts_only_the_overspend():
    """Following the advice would have saved the excess, not the underspend."""
    result = score_advice(records((5000, 8000), (5000, 2000), (5000, 5500)))
    assert result.counterfactual_gain.sen == 3500


def test_a_perfect_record_gains_nothing_and_says_so():
    result = score_advice(records((5000, 5000), (4000, 3000)))
    assert result.follow_rate_bp == 10000
    assert result.counterfactual_gain.sen == 0


def test_a_record_of_pure_overspending_is_reported_as_such():
    result = score_advice(records((5000, 9000), (5000, 9000)))
    assert result.follow_rate_bp == 0
    assert result.counterfactual_gain.sen == 8000


def test_currency_travels_with_the_record():
    result = score_advice(
        (AdviceRecord(date(2026, 6, 5), Money(5000, "MYR"), Money(6000, "MYR")),)
    )
    assert result.counterfactual_gain.currency == "MYR"
