from datetime import UTC, date, datetime

from kira.db.models import TXN_CONFIRMED, TXN_INCOME, Account, Transaction, User
from kira.engine import safe_to_spend
from kira.money import Money
from kira.services.goal_allocations import apply_income_allocation, recommend_income_allocation
from kira.services.goal_planning import (
    apply_approved_plan_change,
    create_draft_goal,
    definition_from_record,
    load_financial_snapshot,
    plan_from_record,
)
from kira.services.snapshot import load_snapshot

AS_OF = datetime(2026, 9, 3, tzinfo=UTC)


async def _user(session) -> User:
    user = User(
        email="allocation@example.com",
        password_hash="unused",
        display_name="Allocation",
        currency="MYR",
        buffer=Money(20_000),
        monthly_income=Money(100_000),
        next_payday=date(2026, 9, 10),
        cycle_start=date(2026, 9, 1),
        cycle_days=30,
    )
    session.add(user)
    await session.flush()
    session.add(
        Account(
            user_id=user.id,
            name="Main",
            kind="bank",
            opening_balance=Money(100_000),
        )
    )
    await session.flush()
    return user


async def _active_goal(session, user, *, name: str, priority: str, target: int):
    goal, draft = await create_draft_goal(
        session,
        user,
        goal_type="custom_goal",
        name=name,
        target_amount_sen=target,
        current_saved_sen=0,
        target_date=date(2026, 9, 10),
        priority=priority,
        funding_account_ids=(),
        as_of_utc=AS_OF,
    )
    await apply_approved_plan_change(
        session,
        user,
        definition=definition_from_record(goal),
        plan=plan_from_record(draft),
        base_plan_version=draft.version,
        as_of_utc=AS_OF,
    )
    await session.commit()
    return goal


async def test_approved_income_split_updates_progress_versions_and_daily_reserve(session):
    user = await _user(session)
    protected = await _active_goal(
        session, user, name="Emergency", priority="protected", target=30_000
    )
    flexible = await _active_goal(
        session, user, name="Holiday", priority="flexible", target=40_000
    )
    income = Transaction(
        user_id=user.id,
        merchant="Salary",
        amount=Money(50_000),
        category="income",
        occurred_on=AS_OF.date(),
        status=TXN_CONFIRMED,
        source="manual",
        direction=TXN_INCOME,
        income_type="salary",
    )
    session.add(income)
    await session.commit()

    before = await load_snapshot(session, user, AS_OF.date())
    recommendation = await recommend_income_allocation(session, user, income.id, AS_OF)
    assert [(item.name, item.amount_sen) for item in recommendation.allocations] == [
        ("Emergency", 30_000),
        ("Holiday", 20_000),
    ]

    applied = await apply_income_allocation(session, user, income.id, AS_OF)
    assert sum(item.amount_sen for item in applied.contributions) == 50_000
    assert protected.saved.sen == 30_000
    assert flexible.saved.sen == 20_000
    assert income.goal_allocation_applied is True
    assert all(item.plan_version == 3 for item in applied.contributions)

    after = await load_snapshot(session, user, AS_OF.date())
    assert before.contributed_goal_reserve.sen == 0
    assert after.contributed_goal_reserve.sen == 50_000
    assert after.balance == before.balance
    assert safe_to_spend(after).goal_reserve.sen == 50_000
    planning_snapshot = await load_financial_snapshot(session, user, AS_OF)
    assert planning_snapshot.cash_available_sen == after.balance.sen - 50_000
