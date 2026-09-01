"""Shared serialization for the exact engine input behind a daily advice row."""

from __future__ import annotations

from datetime import date

from kira.engine.types import CommitmentInput, GoalInput, Snapshot
from kira.money import Money


def snapshot_json(snapshot: Snapshot) -> dict:
    """Make an engine snapshot durable without converting money to floats."""
    return {
        "balance": snapshot.balance.sen,
        "buffer": snapshot.buffer.sen,
        "spent_today": snapshot.spent_today.sen,
        "income": snapshot.income.sen,
        "today": snapshot.today.isoformat(),
        "next_payday": snapshot.next_payday.isoformat(),
        "cycle_start": snapshot.cycle_start.isoformat(),
        "cycle_days": snapshot.cycle_days,
        "commitments": [
            {"id": item.id, "amount": item.amount.sen, "due_date": item.due_date.isoformat()}
            for item in snapshot.commitments
        ],
        "goals": [{"id": item.id, "monthly": item.monthly.sen} for item in snapshot.goals],
    }


def snapshot_from_json(payload: dict, currency: str) -> Snapshot:
    """Read back exactly what was stored. The inverse of ``snapshot_json``.

    Goals come back with their monthly claim alone, because that is all the row
    holds: a stored snapshot answers "what was advised", never "what was the
    goal's arc that day".
    """
    return Snapshot(
        balance=Money(payload["balance"], currency),
        buffer=Money(payload["buffer"], currency),
        spent_today=Money(payload["spent_today"], currency),
        income=Money(payload.get("income", 0), currency),
        today=date.fromisoformat(payload["today"]),
        next_payday=date.fromisoformat(payload["next_payday"]),
        cycle_start=date.fromisoformat(payload["cycle_start"]),
        cycle_days=payload["cycle_days"],
        commitments=tuple(
            CommitmentInput(
                item["id"], Money(item["amount"], currency), date.fromisoformat(item["due_date"])
            )
            for item in payload["commitments"]
        ),
        goals=tuple(
            GoalInput(item["id"], Money(item["monthly"], currency))
            for item in payload["goals"]
        ),
    )
