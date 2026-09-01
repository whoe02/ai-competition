"""Locks the forecast. A change to any number here must be deliberate."""

import json
from datetime import date
from pathlib import Path

import pytest

from kira.engine.projection import simulate
from kira.engine.types import CommitmentInput, DailySpendProfile, GoalInput, Snapshot
from kira.money import Money

CASES_DIR = Path(__file__).parent / "projection_cases"
CASES = [(p.stem, json.loads(p.read_text())) for p in sorted(CASES_DIR.glob("*.json"))]


def build(spec: dict) -> tuple[Snapshot, DailySpendProfile]:
    currency = spec.get("currency", "MYR")
    snapshot = Snapshot(
        balance=Money(spec["balance"], currency),
        buffer=Money(spec["buffer"], currency),
        spent_today=Money(spec["spent_today"], currency),
        commitments=tuple(
            CommitmentInput(
                c["id"], Money(c["amount"], currency), date.fromisoformat(c["due_date"])
            )
            for c in spec["commitments"]
        ),
        goals=tuple(
            GoalInput(
                g["id"],
                Money(g["monthly"], currency),
                Money(g.get("target", 0), currency),
                Money(g.get("saved", 0), currency),
                date.fromisoformat(g["target_date"]) if g.get("target_date") else None,
            )
            for g in spec["goals"]
        ),
        today=date.fromisoformat(spec["today"]),
        next_payday=date.fromisoformat(spec["next_payday"]),
        cycle_start=date.fromisoformat(spec["cycle_start"]),
        cycle_days=spec["cycle_days"],
        income=Money(spec.get("income", 0), currency),
    )
    profile = DailySpendProfile(
        by_weekday=tuple(tuple(day) for day in spec["profile"]),
        lookback_days=spec["lookback_days"],
        series=tuple(spec.get("series", ())),
    )
    return snapshot, profile


def test_cases_exist():
    assert CASES, "no projection cases found — the forecast is unprotected"


@pytest.mark.parametrize("name,case", CASES, ids=[n for n, _ in CASES])
def test_projection_golden_case(name, case):
    snapshot, profile = build(case["input"])
    result = simulate(
        snapshot,
        profile,
        case["horizon_days"],
        trials=case["trials"],
        seed=case["seed"],
    )
    actual = {
        "final_p10": result.bands.p10[-1].sen,
        "final_p50": result.bands.p50[-1].sen,
        "final_p90": result.bands.p90[-1].sen,
        "outlooks": [
            {
                "goal_id": o.goal_id,
                "probability_bp": o.probability_bp,
                "median_shortfall": o.median_shortfall.sen,
            }
            for o in result.outlooks
        ],
    }
    assert actual == case["expected"], case["name"]
