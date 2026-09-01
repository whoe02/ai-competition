"""Scores Kira's past advice against what the user actually did.

Pure, and unflattering by construction: the counterfactual counts only the days
the number was exceeded, so underspending never earns credit.
"""

from __future__ import annotations

from kira.engine.types import AdviceRecord, TrackRecord
from kira.money import Money, round_half_up


def score_advice(records: tuple[AdviceRecord, ...]) -> TrackRecord:
    if not records:
        return TrackRecord(
            days=0,
            followed=0,
            follow_rate_bp=0,
            mean_abs_deviation=Money.zero(),
            counterfactual_gain=Money.zero(),
        )

    currency = records[0].advised.currency
    days = len(records)
    followed = sum(1 for record in records if record.actual <= record.advised)
    deviation = sum(abs(record.actual.sen - record.advised.sen) for record in records)
    excess = sum(max(0, record.actual.sen - record.advised.sen) for record in records)

    return TrackRecord(
        days=days,
        followed=followed,
        follow_rate_bp=round_half_up(followed * 10000, days),
        mean_abs_deviation=Money(round_half_up(deviation, days), currency),
        counterfactual_gain=Money(excess, currency),
    )
