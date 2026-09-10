from datetime import UTC, date, datetime

from sqlalchemy import select

from kira.db.models import (
    TXN_CONFIRMED,
    TXN_DRAFT,
    Account,
    GoalPlanRecord,
    Transaction,
    User,
)
from kira.money import Money
from kira.services.goal_planning import (
    create_draft_goal,
    load_financial_snapshot,
    persist_new_plan_version,
    plan_from_record,
)

AS_OF = datetime(2026, 9, 3, tzinfo=UTC)


async def user_with_account(session) -> User:
    user = User(
        email="goal-owner@example.com",
        password_hash="unused",
        display_name="Goal Owner",
        currency="MYR",
        buffer=Money(20_000),
        next_payday=date(2026, 9, 25),
        cycle_start=date(2026, 8, 26),
        cycle_days=30,
    )
    session.add(user)
    await session.flush()
    session.add(
        Account(
            user_id=user.id,
            name="Confirmed current account",
            kind="bank",
            opening_balance=Money(100_000),
        )
    )
    await session.flush()
    return user


class TestConfirmedSnapshot:
    async def test_draft_transactions_never_reduce_goal_cash(self, session):
        user = await user_with_account(session)
        session.add_all(
            [
                Transaction(
                    user_id=user.id,
                    merchant="Confirmed spend",
                    amount=Money(1_000),
                    category="shopping",
                    occurred_on=AS_OF.date(),
                    status=TXN_CONFIRMED,
                    source="manual",
                ),
                Transaction(
                    user_id=user.id,
                    merchant="Unconfirmed draft",
                    amount=Money(90_000),
                    category="shopping",
                    occurred_on=AS_OF.date(),
                    status=TXN_DRAFT,
                    source="manual",
                ),
            ]
        )
        await session.flush()
        snapshot = await load_financial_snapshot(session, user, AS_OF)
        assert snapshot.cash_available_sen == 99_000
        assert len([ref for ref in snapshot.evidence_refs if ref.startswith("transaction:")]) == 1


class TestPlanVersioning:
    async def test_approved_versions_are_appended_without_overwriting(self, session):
        user = await user_with_account(session)
        goal, first = await create_draft_goal(
            session,
            user,
            goal_type="emergency_starter_fund",
            name="Starter buffer",
            target_amount_sen=60_000,
            current_saved_sen=10_000,
            target_date=date(2026, 12, 24),
            funding_account_ids=(),
            as_of_utc=AS_OF,
        )
        plan = plan_from_record(first)
        second = await persist_new_plan_version(session, goal, plan, approval_status="approved")
        third = await persist_new_plan_version(session, goal, plan, approval_status="approved")
        await session.commit()

        records = (
            (
                await session.execute(
                    select(GoalPlanRecord)
                    .where(GoalPlanRecord.goal_id == goal.id)
                    .order_by(GoalPlanRecord.version)
                )
            )
            .scalars()
            .all()
        )
        assert [record.version for record in records] == [1, 2, 3]
        assert [record.approval_status for record in records] == [
            "draft",
            "approved",
            "approved",
        ]
        assert first.id != second.id != third.id
