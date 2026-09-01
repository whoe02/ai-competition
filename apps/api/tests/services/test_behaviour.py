"""What the forecast learns from the ledger, and what it must ignore."""

from datetime import date, timedelta

import pytest

from kira.db.models import TXN_CONFIRMED, TXN_DRAFT, Commitment, Transaction, User
from kira.money import Money
from kira.services.auth import hash_password
from kira.services.behaviour import build_profile

TODAY = date(2026, 9, 3)
MONDAY = date(2026, 8, 31)


@pytest.fixture
async def user(session) -> User:
    person = User(
        email="profile@kira.app",
        password_hash=hash_password("profile-tests-password"),
        display_name="Profile",
        currency="MYR",
        buffer=Money(0),
        monthly_income=Money(450000),
        next_payday=date(2026, 9, 25),
        cycle_start=date(2026, 8, 26),
        cycle_days=30,
    )
    session.add(person)
    await session.flush()
    return person


async def add_txn(session, user, sen, on, status=TXN_CONFIRMED, merchant="Kedai"):
    session.add(
        Transaction(
            user_id=user.id,
            merchant=merchant,
            amount=Money(sen),
            category="food",
            occurred_on=on,
            status=status,
        )
    )
    await session.flush()


async def test_a_confirmed_row_lands_on_its_weekday(session, user):
    assert MONDAY.weekday() == 0
    await add_txn(session, user, 1500, MONDAY)
    profile = await build_profile(session, user, TODAY)
    assert 1500 in profile.by_weekday[0]


async def test_two_rows_on_one_day_become_one_observation(session, user):
    await add_txn(session, user, 1500, MONDAY)
    await add_txn(session, user, 900, MONDAY, merchant="Kopitiam")
    profile = await build_profile(session, user, TODAY)
    assert profile.by_weekday[0].count(2400) == 1, "a day is one observation, not two"
    assert 1500 not in profile.by_weekday[0]


async def test_a_draft_is_invisible_to_the_forecast(session, user):
    await add_txn(session, user, 5000, MONDAY, status=TXN_DRAFT)
    profile = await build_profile(session, user, TODAY, lookback_days=14)
    assert set(profile.by_weekday[0]) == {0}


async def test_a_transaction_matching_a_commitment_is_not_counted_twice(session, user):
    session.add(
        Commitment(
            user_id=user.id,
            name="Streaming bundle",
            amount=Money(5500),
            due_date=date(2026, 9, 14),
        )
    )
    await session.flush()
    await add_txn(session, user, 5500, MONDAY, merchant="Streaming bundle")
    profile = await build_profile(session, user, TODAY, lookback_days=14)
    assert set(profile.by_weekday[0]) == {0}, "the projection lands commitments itself"


async def test_the_window_ends_at_today_and_excludes_it(session, user):
    await add_txn(session, user, 1500, TODAY)
    profile = await build_profile(session, user, TODAY, lookback_days=14)
    assert 1500 not in profile.by_weekday[TODAY.weekday()]


async def test_the_window_starts_at_the_lookback(session, user):
    await add_txn(session, user, 1500, TODAY - timedelta(days=200))
    profile = await build_profile(session, user, TODAY, lookback_days=90)
    assert all(1500 not in amounts for amounts in profile.by_weekday)


async def test_the_lookback_is_reported(session, user):
    profile = await build_profile(session, user, TODAY, lookback_days=45)
    assert profile.lookback_days == 45


async def test_a_day_with_no_spending_is_a_zero_observation(session, user):
    """Days off are part of the pattern; dropping them would inflate the forecast."""
    await add_txn(session, user, 1500, MONDAY)
    profile = await build_profile(session, user, TODAY, lookback_days=14)
    assert 0 in profile.by_weekday[1], "Tuesday had no spending and must say so"


async def test_a_user_with_no_ledger_has_an_empty_profile(session, user):
    profile = await build_profile(session, user, TODAY, lookback_days=0)
    assert profile.is_empty


async def test_every_day_in_the_window_is_observed_exactly_once(session, user):
    profile = await build_profile(session, user, TODAY, lookback_days=14)
    assert sum(len(amounts) for amounts in profile.by_weekday) == 14
