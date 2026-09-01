"""The track record, scored from real advice rows."""

from datetime import timedelta

from kira.db.models import ADVICE_SOURCE_SEED, DailyAdvice
from kira.money import Money
from kira.seed.demo import DEMO_TODAY, seed_demo_user
from kira.services.hindsight import DEFAULT_WINDOW_DAYS, hindsight


async def demo(session):
    user = await seed_demo_user(session)
    await session.flush()
    return user


async def test_the_demo_user_has_a_record_to_show(session):
    user = await demo(session)
    result = await hindsight(session, user, DEMO_TODAY)
    assert result.record.days > 0, "the seed backfills ninety days of advice"
    assert result.window_days == DEFAULT_WINDOW_DAYS


async def test_today_is_not_scored_before_it_is_over(session):
    user = await demo(session)
    result = await hindsight(session, user, DEMO_TODAY)
    assert all(day.on < DEMO_TODAY for day in result.days)


async def test_the_follow_rate_is_neither_zero_nor_perfect(session):
    """A hand-tuned record would read 100%. This one is scored, so it does not."""
    user = await demo(session)
    result = await hindsight(session, user, DEMO_TODAY)
    assert 0 < result.record.follow_rate_bp < 10000


async def test_the_counterfactual_counts_only_the_days_that_went_over(session):
    user = await demo(session)
    result = await hindsight(session, user, DEMO_TODAY)
    over = sum(
        max(0, day.actual.sen - day.advised.sen) for day in result.days
    )
    assert result.record.counterfactual_gain.sen == over


async def test_the_window_limits_the_days_scored(session):
    user = await demo(session)
    narrow = await hindsight(session, user, DEMO_TODAY, window_days=10)
    assert narrow.record.days <= 10
    assert all(day.on >= DEMO_TODAY - timedelta(days=10) for day in narrow.days)


async def test_a_user_with_no_advice_rows_scores_nothing_rather_than_failing(session):
    user = await demo(session)
    for row in (
        await session.execute(
            DailyAdvice.__table__.select().where(DailyAdvice.user_id == user.id)
        )
    ).all():
        assert row is not None
    await session.execute(DailyAdvice.__table__.delete().where(DailyAdvice.user_id == user.id))

    result = await hindsight(session, user, DEMO_TODAY)
    assert result.record.days == 0
    assert result.record.follow_rate_bp == 0
    assert result.record.counterfactual_gain == Money.zero(user.currency)


async def test_a_bill_is_not_charged_against_the_daily_number(session):
    """``safe_today`` already reserved the rent; scoring it twice would be a lie."""
    user = await demo(session)
    day = DEMO_TODAY - timedelta(days=1)
    scored = await hindsight(session, user, DEMO_TODAY)
    before = next(record for record in scored.days if record.on == day)

    from kira.db.models import TXN_CONFIRMED, Commitment, Transaction

    commitment = (
        await session.execute(Commitment.__table__.select().where(Commitment.user_id == user.id))
    ).first()
    session.add(
        Transaction(
            user_id=user.id,
            merchant=commitment.name,
            amount=Money(120000, user.currency),
            category="bills",
            occurred_on=day,
            status=TXN_CONFIRMED,
            source="manual",
        )
    )
    await session.flush()

    after = next(
        record for record in (await hindsight(session, user, DEMO_TODAY)).days if record.on == day
    )
    assert after.actual == before.actual


async def test_the_advised_number_ignores_what_was_spent_that_day(session):
    """The seed writes ``safe_today`` after the day's spend; the score must not."""
    user = await demo(session)
    result = await hindsight(session, user, DEMO_TODAY)
    rows = {
        row.on_date: row
        for row in (
            await session.execute(
                DailyAdvice.__table__.select().where(DailyAdvice.user_id == user.id)
            )
        ).all()
    }
    spent = [day for day in result.days if day.actual.sen > 0]
    assert spent, "the seed spends money"
    for day in spent[:5]:
        stored = rows[day.on].safe_today
        assert day.advised.sen >= stored.sen
        assert rows[day.on].source == ADVICE_SOURCE_SEED


async def test_the_counterfactual_never_lowers_the_goal_probability(session):
    user = await demo(session)
    result = await hindsight(session, user, DEMO_TODAY)
    if result.probability_bp_now is None:
        return
    assert result.probability_bp_if_followed is not None
    assert result.probability_bp_if_followed >= result.probability_bp_now


async def test_the_assumption_travels_with_the_score(session):
    user = await demo(session)
    result = await hindsight(session, user, DEMO_TODAY)
    assert "confirmed spending" in result.assumption
