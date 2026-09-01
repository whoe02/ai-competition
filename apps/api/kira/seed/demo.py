"""The versioned demo user, maintained alongside the product's prototype figures."""

from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import (
    HORIZON_LONG,
    HORIZON_SHORT,
    SOURCE_MANUAL,
    SOURCE_RECEIPT,
    SOURCE_VOICE,
    TXN_CONFIRMED,
    TXN_DRAFT,
    Account,
    Commitment,
    DailyAdvice,
    Goal,
    Transaction,
    User,
)
from kira.money import Money
from kira.seed.advice import backfill_advice
from kira.seed.history import history_entries
from kira.services.auth import hash_password

DEMO_EMAIL = "demo@kira.app"
DEMO_PASSWORD = "demo-money-butler"
DEMO_TODAY = date(2026, 9, 3)
DEMO_PAYDAY = date(2026, 9, 25)
DEMO_CYCLE_START = date(2026, 8, 26)
# Ninety days back from DEMO_TODAY: enough history for a behaviour profile to
# be a pattern rather than a rumour.
DEMO_HISTORY_START = date(2026, 6, 5)
# RM5,200. The prototype's person is tight — RM52.97 a day — and this is what
# their own ledger costs: RM2,003 of commitments and RM2,719 of spending a
# month, leaving barely enough for the goals they have set themselves.
DEMO_MONTHLY_INCOME = 520000

COMMITMENTS = (
    ("Rent", 120000, date(2026, 9, 5), True),
    ("Phone bill", 8900, date(2026, 9, 8), False),
    ("Car loan minimum", 52000, date(2026, 9, 10), True),
    ("Streaming bundle", 5500, date(2026, 9, 14), False),
    ("Home internet", 13900, date(2026, 9, 18), False),
)

GOALS = (
    (
        "Emergency top-up",
        HORIZON_SHORT,
        250000,
        115000,
        27000,
        date(2027, 2, 15),
        "Three weeks of expenses, kept separate from the buffer.",
    ),
    (
        "Wedding",
        HORIZON_LONG,
        800000,
        329000,
        52500,
        date(2027, 6, 30),
        "Deposit and banquet, split with Aida.",
    ),
)

# Cycle-to-date spending, all of it already confirmed and already spent. The
# opening balance below is raised by exactly this total, so the derived balance
# — and therefore Today's RM52.97 — is unchanged by the history's presence.
CONFIRMED = (
    ("Grab — KLCC to home", 1620, "transport", SOURCE_MANUAL, date(2026, 9, 2)),
    ("Family Mart", 1250, "groceries", SOURCE_RECEIPT, date(2026, 9, 2)),
    ("Village Park Restoran", 2350, "food", SOURCE_RECEIPT, date(2026, 9, 1)),
    ("Touch 'n Go reload", 5000, "transport", SOURCE_MANUAL, date(2026, 9, 1)),
    ("Jaya Grocer", 8745, "groceries", SOURCE_RECEIPT, date(2026, 8, 31)),
    ("Uniqlo Mid Valley", 7900, "shopping", SOURCE_RECEIPT, date(2026, 8, 31)),
    ("Zus Coffee", 1190, "food", SOURCE_RECEIPT, date(2026, 8, 30)),
    ("GSC Mid Valley", 4200, "fun", SOURCE_MANUAL, date(2026, 8, 30)),
    ("Petronas Setapak", 9000, "transport", SOURCE_RECEIPT, date(2026, 8, 29)),
    ("Instant transfer fee", 50, "fees", SOURCE_MANUAL, date(2026, 8, 29)),
    ("Mixue", 890, "food", SOURCE_VOICE, date(2026, 8, 28)),
    ("Watsons", 3560, "health", SOURCE_RECEIPT, date(2026, 8, 28)),
    ("Duit raya — Adik Aina", 5000, "family", SOURCE_MANUAL, date(2026, 8, 27)),
    ("Coursera — Python track", 7900, "education", SOURCE_MANUAL, date(2026, 8, 27)),
    ("Guardian pharmacy", 2480, "health", SOURCE_MANUAL, date(2026, 8, 26)),
    ("Masjid Wilayah donation", 2000, "charity", SOURCE_MANUAL, date(2026, 8, 26)),
)

# The ninety days before the current cycle. Together with CONFIRMED this is
# every confirmed row the demo user owns.
HISTORY = history_entries(DEMO_HISTORY_START, CONFIRMED[-1][4])
ALL_CONFIRMED = HISTORY + CONFIRMED

SPENT_ALL_TIME = sum(sen for _, sen, _, _, _ in ALL_CONFIRMED)
OPENING_BALANCE = 418040 + SPENT_ALL_TIME

DRAFTS = (
    (
        "Nasi Kandar Pelita",
        1890,
        "food",
        SOURCE_RECEIPT,
        94,
        "Line item total matched, tax line ignored.",
    ),
    (
        "Grab — office to KLCC",
        1400,
        "transport",
        SOURCE_VOICE,
        71,
        "Heard 'fourteen ringgit'. Amount is worth a second look.",
    ),
)


async def seed_demo_user(session: AsyncSession) -> User:
    """Create or reset the demo user's financial picture without duplicates."""
    user = (
        await session.execute(select(User).where(User.email == DEMO_EMAIL))
    ).scalar_one_or_none()

    if user is None:
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            display_name="Floyd",
            currency="MYR",
            buffer=Money(80000),
            monthly_income=Money(DEMO_MONTHLY_INCOME),
            next_payday=DEMO_PAYDAY,
            cycle_start=DEMO_CYCLE_START,
            cycle_days=30,
        )
        session.add(user)
        await session.flush()
    else:
        user.password_hash = hash_password(DEMO_PASSWORD)
        user.display_name = "Floyd"
        user.currency = "MYR"
        user.buffer = Money(80000)
        user.monthly_income = Money(DEMO_MONTHLY_INCOME)
        user.next_payday = DEMO_PAYDAY
        user.cycle_start = DEMO_CYCLE_START
        user.cycle_days = 30
        for model in (DailyAdvice, Transaction, Goal, Commitment, Account):
            await session.execute(delete(model).where(model.user_id == user.id))

    session.add(
        Account(
            user_id=user.id,
            name="Maybank current",
            kind="bank",
            opening_balance=Money(OPENING_BALANCE),
        )
    )

    for name, sen, due_date, protected in COMMITMENTS:
        session.add(
            Commitment(
                user_id=user.id,
                name=name,
                amount=Money(sen),
                due_date=due_date,
                protected=protected,
            )
        )

    for name, horizon, target, saved, monthly, target_date, note in GOALS:
        session.add(
            Goal(
                user_id=user.id,
                name=name,
                horizon=horizon,
                target=Money(target),
                saved=Money(saved),
                monthly=Money(monthly),
                target_date=target_date,
                note=note,
            )
        )

    # Oldest first, so created_at rises with the day it happened.
    for merchant, sen, category, source, occurred_on in reversed(ALL_CONFIRMED):
        session.add(
            Transaction(
                user_id=user.id,
                merchant=merchant,
                amount=Money(sen),
                category=category,
                occurred_on=occurred_on,
                status=TXN_CONFIRMED,
                source=source,
            )
        )

    # Drafts are intentionally excluded from all Today calculations until confirmed.
    for merchant, sen, category, source, confidence, note in DRAFTS:
        session.add(
            Transaction(
                user_id=user.id,
                merchant=merchant,
                amount=Money(sen),
                category=category,
                occurred_on=DEMO_TODAY,
                status=TXN_DRAFT,
                source=source,
                confidence=confidence,
                note=note,
            )
        )

    await session.flush()
    await backfill_advice(session, user, DEMO_HISTORY_START, DEMO_TODAY)
    await session.flush()
    return user
