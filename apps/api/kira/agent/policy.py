"""Resources the Butler may not touch, whatever it has been asked to do.

This runs in the guard, before anything executes, and again at approval time.
A refusal here is not a failure of the model; it is the boundary working.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import Commitment, User
from kira.services.day_plan import find_place

# The safety net is the user's, not the Butler's. No tool exposes it, and any
# argument that names it is refused rather than quietly ignored.
UNTOUCHABLE_FIELDS = ("buffer", "buffer_sen", "balance", "balance_sen")


async def refusal_for(
    session: AsyncSession,
    user: User,
    tool_name: str,
    args: dict[str, Any],
) -> str | None:
    """Return why this call must not run, or None if the policy permits it."""
    named = sorted(field for field in UNTOUCHABLE_FIELDS if field in args)
    if named:
        return (
            f"{tool_name} was called with {', '.join(named)}. The buffer and the balance "
            "are not mine to change — they follow from confirmed transactions."
        )

    commitment_id = args.get("commitment_id")
    if commitment_id is not None:
        commitment = await _commitment(session, user, commitment_id)
        if commitment is None:
            return f"There is no bill {commitment_id} on this account."
        if commitment.protected:
            return (
                f"“{commitment.name}” is protected. Protected bills stay exactly as they "
                "are; I can work around them, not through them."
            )

    # A place id means nothing on its own: it is a handle on a row of a plan
    # built from somewhere, so it is checked against that somewhere, and left
    # alone by any call that names one without the other. The check belongs
    # here rather than in the handler because here it runs twice — in the
    # guard, so an id nobody was shown never reaches a card, and again on
    # resume, so an edited card cannot swap in one that was never offered.
    place_id = args.get("place_id")
    lat, lng = args.get("lat"), args.get("lng")
    if place_id is not None and isinstance(lat, int | float) and isinstance(lng, int | float):
        if find_place(str(place_id), lat=float(lat), lng=float(lng)) is None:
            return (
                f"There is no place {place_id} within range of that search. I can only add "
                "one the plan actually came back with — build it again and name one of those."
            )
    return None


async def _commitment(session: AsyncSession, user: User, commitment_id: Any) -> Commitment | None:
    try:
        identifier = (
            commitment_id if isinstance(commitment_id, uuid.UUID) else uuid.UUID(str(commitment_id))
        )
    except (ValueError, AttributeError, TypeError):
        return None
    return (
        await session.execute(
            select(Commitment).where(Commitment.id == identifier, Commitment.user_id == user.id)
        )
    ).scalar_one_or_none()
