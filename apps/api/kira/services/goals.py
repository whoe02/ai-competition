"""Goals: reading them, projecting them, and the writes the Butler proposes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import HORIZON_LONG, HORIZON_SHORT, Goal, User
from kira.engine import months_to_goal
from kira.money import Money

HORIZONS = (HORIZON_SHORT, HORIZON_LONG)


class GoalNotFound(Exception):
    """No such goal belongs to this user."""


class InvalidGoal(Exception):
    """The proposed goal does not describe something fundable."""


class AmbiguousGoal(Exception):
    """A human goal reference matches more than one owned goal."""


@dataclass(frozen=True, slots=True)
class GoalView:
    id: uuid.UUID
    name: str
    horizon: str
    target_sen: int
    saved_sen: int
    monthly_sen: int
    months_left: int
    note: str


@dataclass(frozen=True, slots=True)
class GoalProjection:
    """What changing the monthly contribution would do to the finish date."""

    id: uuid.UUID
    name: str
    monthly_sen: int
    months_left: int
    proposed_monthly_sen: int
    proposed_months_left: int
    months_moved: int


def _view(goal: Goal) -> GoalView:
    return GoalView(
        id=goal.id,
        name=goal.name,
        horizon=goal.horizon,
        target_sen=goal.target.sen,
        saved_sen=goal.saved.sen,
        monthly_sen=goal.monthly.sen,
        months_left=months_to_goal(goal.target, goal.saved, goal.monthly),
        note=goal.note,
    )


async def _owned(session: AsyncSession, user: User, goal_id: uuid.UUID) -> Goal:
    goal = (
        await session.execute(
            select(Goal).where(
                Goal.id == goal_id,
                Goal.user_id == user.id,
                Goal.status != "deleted",
            )
        )
    ).scalar_one_or_none()
    if goal is None:
        raise GoalNotFound(str(goal_id))
    return goal


async def list_goals(session: AsyncSession, user: User) -> tuple[GoalView, ...]:
    goals = (
        await session.execute(
            select(Goal)
            .where(
                Goal.user_id == user.id,
                Goal.status.not_in(("draft", "cancelled", "deleted")),
            )
            .order_by(Goal.name)
        )
    ).scalars().all()
    return tuple(_view(goal) for goal in goals)


def _reference_words(value: str) -> set[str]:
    ignored = {"a", "an", "the", "my", "goal", "fund", "savings", "for"}
    return {
        word
        for word in "".join(character if character.isalnum() else " " for character in value)
        .casefold()
        .split()
        if word not in ignored
    }


async def resolve_owned_goal_reference(
    session: AsyncSession, user: User, reference: str = ""
) -> Goal:
    """Resolve a user-facing goal name without asking the model for a UUID."""
    goals = (
        await session.execute(
            select(Goal)
            .where(
                Goal.user_id == user.id,
                Goal.status.not_in(("draft", "cancelled", "deleted", "achieved")),
            )
            .order_by(Goal.created_at, Goal.id)
        )
    ).scalars().all()
    if not goals:
        raise GoalNotFound("you do not have an active goal yet")

    cleaned = reference.strip()
    if not cleaned:
        if len(goals) == 1:
            return goals[0]
        raise AmbiguousGoal("name the goal you want to accelerate")

    folded = cleaned.casefold()
    matches = [goal for goal in goals if goal.name.casefold() == folded]
    if not matches:
        wanted = _reference_words(cleaned)
        scored = [(len(wanted & _reference_words(goal.name)), goal) for goal in goals]
        best = max((score for score, _ in scored), default=0)
        matches = [goal for score, goal in scored if score == best and score > 0]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(goal.name for goal in matches)
        raise AmbiguousGoal(f"more than one goal matches '{cleaned}': {names}")
    raise GoalNotFound(f"I could not find an active goal matching '{cleaned}'")


async def project_goal(
    session: AsyncSession, user: User, goal_id: uuid.UUID, monthly_sen: int
) -> GoalProjection:
    """Answer "what if I put this much aside" without changing anything."""
    goal = await _owned(session, user, goal_id)
    if monthly_sen <= 0:
        raise InvalidGoal("a monthly contribution must be positive")
    proposed = Money(monthly_sen, user.currency)
    now = months_to_goal(goal.target, goal.saved, goal.monthly)
    then = months_to_goal(goal.target, goal.saved, proposed)
    return GoalProjection(
        id=goal.id,
        name=goal.name,
        monthly_sen=goal.monthly.sen,
        months_left=now,
        proposed_monthly_sen=monthly_sen,
        proposed_months_left=then,
        months_moved=then - now,
    )


async def create_goal(
    session: AsyncSession,
    user: User,
    *,
    name: str,
    horizon: str,
    target_sen: int,
    monthly_sen: int,
    saved_sen: int = 0,
    note: str = "",
) -> GoalView:
    if horizon not in HORIZONS:
        raise InvalidGoal(f"horizon must be one of {HORIZONS}")
    if target_sen <= 0 or monthly_sen <= 0 or saved_sen < 0:
        raise InvalidGoal("a goal needs a positive target and monthly contribution")
    if not name.strip():
        raise InvalidGoal("a goal needs a name")
    goal = Goal(
        user_id=user.id,
        name=name.strip(),
        horizon=horizon,
        target=Money(target_sen, user.currency),
        saved=Money(saved_sen, user.currency),
        monthly=Money(monthly_sen, user.currency),
        note=note,
    )
    session.add(goal)
    await session.flush()
    return _view(goal)


async def update_goal(
    session: AsyncSession,
    user: User,
    goal_id: uuid.UUID,
    *,
    name: str | None = None,
    target_sen: int | None = None,
    monthly_sen: int | None = None,
    saved_sen: int | None = None,
    note: str | None = None,
) -> GoalView:
    goal = await _owned(session, user, goal_id)
    if name is not None:
        if not name.strip():
            raise InvalidGoal("a goal needs a name")
        goal.name = name.strip()
    if target_sen is not None:
        if target_sen <= 0:
            raise InvalidGoal("a goal needs a positive target")
        goal.target = Money(target_sen, user.currency)
    if monthly_sen is not None:
        if monthly_sen <= 0:
            raise InvalidGoal("a monthly contribution must be positive")
        goal.monthly = Money(monthly_sen, user.currency)
    if saved_sen is not None:
        if saved_sen < 0:
            raise InvalidGoal("saved cannot be negative")
        goal.saved = Money(saved_sen, user.currency)
    if note is not None:
        goal.note = note
    await session.flush()
    return _view(goal)
