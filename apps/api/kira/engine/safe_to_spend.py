"""How much of today's money is genuinely free to spend.

Pure: no I/O, no database, no clock. Every date arrives on the Snapshot.
"""

from __future__ import annotations

from kira.engine.types import SafeToSpend, Snapshot
from kira.money import Money, round_half_up


def safe_to_spend(snapshot: Snapshot) -> SafeToSpend:
    currency = snapshot.currency

    days_to_payday = max(1, (snapshot.next_payday - snapshot.today).days)
    cycle_elapsed = min(
        snapshot.cycle_days,
        max(0, (snapshot.today - snapshot.cycle_start).days),
    )

    # A goal claims what has accrued so far this cycle, not its whole contribution.
    # Each goal is rounded once, on its own; rounded parts are never re-divided.
    scheduled_goal_reserve = Money.sum(
        (
            Money(
                round_half_up(
                    goal.monthly.sen
                    * min(
                        snapshot.cycle_days,
                        max(
                            0,
                            (
                                snapshot.today
                                - (goal.last_contributed_on or snapshot.cycle_start)
                            ).days,
                        ),
                    ),
                    snapshot.cycle_days,
                ),
                currency,
            )
            for goal in snapshot.goals
        ),
        currency,
    )
    goal_reserve = snapshot.contributed_goal_reserve + scheduled_goal_reserve

    # Only bills that land before the next payday compete with today's money.
    reserved = Money.sum(
        (c.amount for c in snapshot.commitments if c.due_date < snapshot.next_payday),
        currency,
    )

    unclaimed = snapshot.balance - reserved - snapshot.buffer - goal_reserve
    per_day = unclaimed.divide_floor(days_to_payday)
    safe_today = max(Money.zero(currency), per_day - snapshot.spent_today)

    return SafeToSpend(
        days_to_payday=days_to_payday,
        cycle_elapsed=cycle_elapsed,
        balance=snapshot.balance,
        reserved=reserved,
        buffer=snapshot.buffer,
        goal_reserve=goal_reserve,
        unclaimed=unclaimed,
        per_day=per_day,
        spent_today=snapshot.spent_today,
        safe_today=safe_today,
    )
