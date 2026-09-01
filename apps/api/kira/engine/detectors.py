"""Deterministic overnight signals derived from already-known finance facts.

These functions deliberately return evidence, not instructions to move money.
The worker decides how to present a signal; this module only answers whether a
condition is true from its explicit inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from kira.engine.types import GoalOutlook, Projection, Snapshot
from kira.money import Money


@dataclass(frozen=True, slots=True)
class DetectorHit:
    """A stable, display-ready description of one detected condition."""

    kind: str
    title: str
    detail: str


def buffer_breach_ahead(
    bands: Projection, buffer: Money, first_day: date
) -> DetectorHit | None:
    """Find the first cautious forecast day that lands below the user's buffer."""
    for index, amount in enumerate(bands.p10):
        if amount < buffer:
            on = first_day + timedelta(days=index)
            return DetectorHit(
                kind="buffer_breach_ahead",
                title="Your cautious forecast crosses the buffer",
                detail=(
                    f"The p10 forecast reaches {amount} on {on.isoformat()}, "
                    f"below your {buffer} buffer."
                ),
            )
    return None


def goal_probability_dropped(
    goal_id: str,
    previous_probability_bp: int,
    current: GoalOutlook,
    *,
    material_drop_bp: int = 500,
) -> DetectorHit | None:
    """Report a goal only after a meaningful five-point probability movement."""
    if current.goal_id != goal_id:
        raise ValueError("goal_id must match the supplied outlook")
    if previous_probability_bp - current.probability_bp < material_drop_bp:
        return None
    return DetectorHit(
        kind="goal_probability_dropped",
        title="A goal is less likely to land on time",
        detail=(
            f"Goal {goal_id} moved from {previous_probability_bp} to "
            f"{current.probability_bp} basis points."
        ),
    )


def unconfirmed_drafts_piling(draft_count: int, *, threshold: int = 2) -> DetectorHit | None:
    """Surface a small queue before drafts silently stop matching reality."""
    if draft_count < threshold:
        return None
    return DetectorHit(
        kind="unconfirmed_drafts_piling",
        title="Draft spending is waiting for you",
        detail=f"{draft_count} drafts are still excluded from your available balance.",
    )


def spend_pattern_anomaly(actual: Money, expected: Money) -> DetectorHit | None:
    """Flag a day at least twice the user's own normal level, without floats."""
    if expected.sen <= 0:
        return None
    if actual.sen < expected.sen * 2:
        return None
    return DetectorHit(
        kind="spend_pattern_anomaly",
        title="Today's spending is above your usual pattern",
        detail=f"Confirmed spending is {actual}; your normal level is {expected}.",
    )


def commitment_due_unfunded(snapshot: Snapshot) -> DetectorHit | None:
    """Name a commitment that cannot fit above the buffer; never try to pay it."""
    available = snapshot.balance - snapshot.buffer
    for commitment in sorted(snapshot.commitments, key=lambda item: item.due_date):
        if commitment.amount > available:
            return DetectorHit(
                kind="commitment_due_unfunded",
                title="A commitment is not covered above your buffer",
                detail=(
                    f"Commitment {commitment.id} needs {commitment.amount} on "
                    f"{commitment.due_date.isoformat()}, with {available} available above "
                    "the buffer."
                ),
            )
    return None
