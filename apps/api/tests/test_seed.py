from datetime import date, timedelta

import sqlalchemy as sa

from kira.categories import slugs
from kira.db.models import (
    TXN_CONFIRMED,
    TXN_DRAFT,
    Account,
    Commitment,
    DailyAdvice,
    Goal,
    Transaction,
    User,
)
from kira.engine import safe_to_spend
from kira.money import Money
from kira.seed.demo import (
    DEMO_EMAIL,
    DEMO_HISTORY_START,
    DEMO_TODAY,
    seed_demo_user,
)
from kira.services.snapshot import load_snapshot


class TestSeed:
    async def test_creates_the_demo_user_and_their_picture(self, session):
        user = await seed_demo_user(session)
        assert user.email == DEMO_EMAIL
        assert user.display_name == "Floyd"
        assert user.buffer == Money(80000)
        assert user.next_payday == date(2026, 9, 25)
        assert user.cycle_start == date(2026, 8, 26)
        assert user.cycle_days == 30

    async def test_seeds_the_prototype_figures(self, session):
        await seed_demo_user(session)
        opening = (
            await session.execute(sa.select(sa.func.sum(Account.opening_balance)))
        ).scalar_one()
        confirmed = (
            await session.execute(
                sa.select(Transaction).where(Transaction.status == TXN_CONFIRMED)
            )
        ).scalars().all()
        assert opening - Money.sum((txn.amount for txn in confirmed), "MYR") == Money(418040)
        commitments = (await session.execute(sa.select(Commitment))).scalars().all()
        assert sum(commitment.amount.sen for commitment in commitments) == 200300
        assert {commitment.name for commitment in commitments} == {
            "Rent",
            "Phone bill",
            "Car loan minimum",
            "Streaming bundle",
            "Home internet",
        }
        goals = (await session.execute(sa.select(Goal))).scalars().all()
        assert {goal.name for goal in goals} == {"Emergency top-up", "Wedding"}
        assert sum(goal.monthly.sen for goal in goals) == 79500

    async def test_seeds_two_waiting_drafts(self, session):
        await seed_demo_user(session)
        txns = (await session.execute(sa.select(Transaction))).scalars().all()
        drafts = [txn for txn in txns if txn.status == TXN_DRAFT]
        assert len(drafts) == 2

    async def test_seeds_a_spending_history_that_leaves_the_balance_unchanged(self, session):
        await seed_demo_user(session)
        opening = (
            await session.execute(sa.select(sa.func.sum(Account.opening_balance)))
        ).scalar_one()
        confirmed = (
            await session.execute(
                sa.select(Transaction).where(Transaction.status == TXN_CONFIRMED)
            )
        ).scalars().all()
        assert len(confirmed) >= 180
        assert opening - Money.sum((txn.amount for txn in confirmed), "MYR") == Money(418040)

    async def test_categorises_every_transaction_from_the_vocabulary(self, session):
        await seed_demo_user(session)
        txns = (await session.execute(sa.select(Transaction))).scalars().all()
        assert {txn.category for txn in txns} <= set(slugs())

    async def test_spreads_the_history_widely_enough_to_filter(self, session):
        await seed_demo_user(session)
        confirmed = (
            await session.execute(
                sa.select(Transaction).where(Transaction.status == TXN_CONFIRMED)
            )
        ).scalars().all()
        categories = {txn.category for txn in confirmed}
        assert len(categories) >= 8
        assert {"family", "charity", "shopping"} <= categories

    async def test_never_confirms_spending_dated_today(self, session):
        await seed_demo_user(session)
        confirmed = (
            await session.execute(
                sa.select(Transaction).where(Transaction.status == TXN_CONFIRMED)
            )
        ).scalars().all()
        assert confirmed
        assert all(txn.occurred_on < DEMO_TODAY for txn in confirmed)

    async def test_is_idempotent(self, session):
        first = await seed_demo_user(session)
        second = await seed_demo_user(session)
        assert first.id == second.id
        user_count = (
            await session.execute(sa.select(sa.func.count()).select_from(User))
        ).scalar_one()
        assert user_count == 1
        assert (
            await session.execute(sa.select(sa.func.count()).select_from(Commitment))
        ).scalar_one() == 5


class TestSeededHistory:
    """Ninety days of it, and a record of what Kira advised on each one."""

    async def test_has_ninety_days_of_confirmed_history(self, session):
        user = await seed_demo_user(session)
        await session.flush()
        rows = (
            await session.execute(
                sa.select(Transaction).where(
                    Transaction.user_id == user.id,
                    Transaction.status == TXN_CONFIRMED,
                )
            )
        ).scalars().all()

        assert len(rows) >= 180, "a behaviour profile needs density, not a handful of rows"
        span = max(r.occurred_on for r in rows) - min(r.occurred_on for r in rows)
        assert span >= timedelta(days=85)
        assert min(r.occurred_on for r in rows) == DEMO_HISTORY_START

    async def test_history_has_a_weekly_rhythm(self, session):
        user = await seed_demo_user(session)
        await session.flush()
        rows = (
            await session.execute(
                sa.select(Transaction).where(
                    Transaction.user_id == user.id,
                    Transaction.status == TXN_CONFIRMED,
                    Transaction.category == "groceries",
                )
            )
        ).scalars().all()
        sundays = [r for r in rows if r.occurred_on.weekday() == 6]
        assert len(sundays) >= 10, "Sunday groceries are the rhythm the forecast learns"

    async def test_backfills_one_advice_row_per_day(self, session):
        user = await seed_demo_user(session)
        await session.flush()
        count = (
            await session.execute(
                sa.select(sa.func.count()).select_from(DailyAdvice).where(
                    DailyAdvice.user_id == user.id
                )
            )
        ).scalar_one()
        assert count >= 85

        row = (
            await session.execute(
                sa.select(DailyAdvice).where(
                    DailyAdvice.user_id == user.id,
                    DailyAdvice.on_date == DEMO_TODAY - timedelta(days=1),
                )
            )
        ).scalar_one()
        assert row.source == "seed"
        assert row.snapshot["balance"] != 0
        assert row.safe_today.sen >= 0

    async def test_advice_varies_because_the_engine_computed_it(self, session):
        """A hand-written track record would be flat, and flatly false."""
        user = await seed_demo_user(session)
        await session.flush()
        values = (
            await session.execute(
                sa.select(DailyAdvice.safe_today).where(DailyAdvice.user_id == user.id)
            )
        ).scalars().all()
        assert len({value.sen for value in values}) >= 20

    async def test_seeding_twice_leaves_one_advice_row_per_day(self, session):
        user = await seed_demo_user(session)
        await session.flush()
        await seed_demo_user(session)
        await session.flush()
        days = (
            await session.execute(
                sa.select(DailyAdvice.on_date).where(DailyAdvice.user_id == user.id)
            )
        ).scalars().all()
        assert len(days) == len(set(days))

    async def test_the_headline_is_unchanged_by_the_history(self, session):
        """RM52.97 is the demo's headline. Deepening history must not move it."""
        user = await seed_demo_user(session)
        await session.flush()
        result = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))
        assert result.safe_today.sen == 5297

    async def test_the_user_has_an_income_to_project(self, session):
        user = await seed_demo_user(session)
        assert user.monthly_income.sen > 0
