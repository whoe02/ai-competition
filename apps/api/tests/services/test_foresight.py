"""The forecast, assembled from real rows."""

import pytest

from kira.engine.types import Lever
from kira.money import Money
from kira.seed.demo import DEMO_TODAY, seed_demo_user
from kira.services.foresight import candidate_levers, compare, foresight
from kira.services.snapshot import load_snapshot


async def demo(session):
    user = await seed_demo_user(session)
    await session.flush()
    return user


async def test_the_demo_user_gets_a_band_over_the_horizon(session):
    user = await demo(session)
    result = await foresight(session, user, DEMO_TODAY, horizon_days=90)
    assert len(result.bands.bands.p50) == 90
    assert len(result.bands.bands.days) == 90
    assert result.profile_days == 90


async def test_the_band_is_ordered_and_widens(session):
    user = await demo(session)
    result = await foresight(session, user, DEMO_TODAY)
    p10, p90 = result.bands.bands.p10, result.bands.bands.p90
    assert all(low <= high for low, high in zip(p10, p90, strict=True))
    assert (p90[-1].sen - p10[-1].sen) > (p90[0].sen - p10[0].sen)


async def test_the_assumption_travels_with_the_number(session):
    """A probability read as a promise is a trust failure, so it is labelled."""
    user = await demo(session)
    result = await foresight(session, user, DEMO_TODAY)
    assert "90 days" in result.assumption
    assert "not a promise" in result.assumption


async def test_the_demo_user_has_a_probability_to_show(session):
    user = await demo(session)
    result = await foresight(session, user, DEMO_TODAY)
    assert result.bands.outlooks, "the demo must show a probability, not an empty panel"
    probability = result.bands.outlooks[0].probability_bp
    assert 0 < probability < 10000, "a forecast reading 0% or 100% shows nothing"


async def test_the_demo_user_has_a_change_worth_proposing(session):
    user = await demo(session)
    result = await foresight(session, user, DEMO_TODAY)
    assert result.drivers, "a diagnosis with no treatment is not advice"


async def test_candidate_levers_cover_the_goals_and_the_spending(session):
    user = await demo(session)
    snapshot = await load_snapshot(session, user, DEMO_TODAY)
    kinds = {lever.kind for lever in candidate_levers(snapshot)}
    assert {"goal_monthly", "daily_spend"} <= kinds


async def test_a_protected_commitment_is_never_a_candidate(session):
    """Rent and the car loan are protected in the seed. Kira does not propose skipping them."""
    user = await demo(session)
    snapshot = await load_snapshot(session, user, DEMO_TODAY)
    from kira.services.foresight import _protected_ids

    protected = await _protected_ids(session, user)
    assert protected, "the seed marks two commitments protected"
    targets = {lever.target_id for lever in candidate_levers(snapshot, protected)}
    assert not (targets & protected)


async def test_compare_returns_one_result_per_lever(session):
    user = await demo(session)
    snapshot = await load_snapshot(session, user, DEMO_TODAY)
    goal_id = snapshot.goals[0].id
    results = await compare(
        session, user, DEMO_TODAY, (Lever("goal_monthly", goal_id, Money(5000)),),
        horizon_days=60,
    )
    assert len(results) == 1
    assert results[0].lever.target_id == goal_id


async def test_a_horizon_beyond_a_year_is_refused(session):
    user = await demo(session)
    with pytest.raises(ValueError):
        await foresight(session, user, DEMO_TODAY, horizon_days=400)


async def test_a_horizon_of_nothing_is_refused(session):
    user = await demo(session)
    with pytest.raises(ValueError):
        await foresight(session, user, DEMO_TODAY, horizon_days=0)


async def test_the_forecast_writes_nothing(session):
    from sqlalchemy import func, select

    from kira.db.models import Goal, Transaction

    user = await demo(session)
    before = (
        (await session.execute(select(func.count()).select_from(Transaction))).scalar_one(),
        (await session.execute(select(func.count()).select_from(Goal))).scalar_one(),
    )
    await foresight(session, user, DEMO_TODAY, horizon_days=60)
    after = (
        (await session.execute(select(func.count()).select_from(Transaction))).scalar_one(),
        (await session.execute(select(func.count()).select_from(Goal))).scalar_one(),
    )
    assert before == after
