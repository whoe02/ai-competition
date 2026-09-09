"""The shared mutation path for user-owned financial preferences."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import User
from kira.money import Money


class InvalidProfile(Exception):
    pass


async def update_profile(
    session: AsyncSession,
    user: User,
    *,
    display_name: str | None = None,
    job_title: str | None = None,
    monthly_income_sen: int | None = None,
    next_payday: date | None = None,
    cycle_start: date | None = None,
    cycle_days: int | None = None,
) -> User:
    if display_name is not None:
        if not display_name.strip():
            raise InvalidProfile("display name cannot be blank")
        user.display_name = display_name.strip()
    if job_title is not None:
        user.job_title = job_title.strip()
    if monthly_income_sen is not None:
        if monthly_income_sen < 0:
            raise InvalidProfile("monthly income cannot be negative")
        user.monthly_income = Money(monthly_income_sen, user.currency)
    if next_payday is not None:
        user.next_payday = next_payday
    if cycle_start is not None:
        user.cycle_start = cycle_start
    if cycle_days is not None:
        if not 1 <= cycle_days <= 62:
            raise InvalidProfile("cycle days must be between 1 and 62")
        user.cycle_days = cycle_days
    await session.flush()
    return user
