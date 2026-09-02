"""Read the ledger, and settle drafts. The only place a transaction's status moves."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from itertools import groupby

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.categories import label_for
from kira.db.models import (
    INCOME_TYPES,
    SOURCE_MANUAL,
    TXN_CONFIRMED,
    TXN_DIRECTIONS,
    TXN_DISCARDED,
    TXN_DRAFT,
    TXN_EXPENSE,
    Transaction,
    User,
)
from kira.money import Money


class TransactionNotFound(Exception):
    """No such transaction belongs to this user."""


class AlreadySettled(Exception):
    """The transaction has already been confirmed or discarded."""


class NotConfirmed(Exception):
    """Only a confirmed transaction can be returned to the drafts."""


class InvalidTransaction(Exception):
    """The proposed transaction is not something that can go on the ledger."""


class IncomeAllocationExists(Exception):
    """An income supporting goal contributions cannot be removed underneath them."""


@dataclass(frozen=True, slots=True)
class TransactionView:
    id: uuid.UUID
    merchant: str
    amount_sen: int
    category: str
    category_label: str
    occurred_on: date
    status: str
    source: str
    confidence: int | None
    note: str
    direction: str
    income_type: str | None
    goal_allocation_applied: bool


@dataclass(frozen=True, slots=True)
class ActivityDay:
    date: date
    total_sen: int
    transactions: tuple[TransactionView, ...]


@dataclass(frozen=True, slots=True)
class CategorySummary:
    slug: str
    label: str
    spent_this_cycle_sen: int
    count: int


@dataclass(frozen=True, slots=True)
class Activity:
    drafts: tuple[TransactionView, ...]
    draft_total_sen: int
    days: tuple[ActivityDay, ...]
    spent_this_cycle_sen: int
    income_this_cycle_sen: int
    categories: tuple[CategorySummary, ...]


def _view(txn: Transaction) -> TransactionView:
    return TransactionView(
        id=txn.id,
        merchant=txn.merchant,
        amount_sen=txn.amount.sen,
        category=txn.category,
        category_label=label_for(txn.category),
        occurred_on=txn.occurred_on,
        status=txn.status,
        source=txn.source,
        confidence=txn.confidence,
        note=txn.note,
        direction=txn.direction,
        income_type=txn.income_type,
        goal_allocation_applied=txn.goal_allocation_applied,
    )


def _total(txns: Iterable[TransactionView], currency: str) -> int:
    return Money.sum((Money(txn.amount_sen, currency) for txn in txns), currency).sen


def _activity_day(occurred_on: date, transactions: Iterable[Transaction]) -> ActivityDay:
    rows = tuple(_view(txn) for txn in transactions)
    return ActivityDay(
        date=occurred_on,
        # A positive total is net money out; income therefore offsets it.
        total_sen=sum(
            row.amount_sen if row.direction == TXN_EXPENSE else -row.amount_sen
            for row in rows
        ),
        transactions=rows,
    )


def _summarise(
    confirmed: Iterable[Transaction], cycle_start: date, currency: str
) -> tuple[CategorySummary, ...]:
    """One chip per category present this cycle, dearest first."""
    totals: dict[str, list[int]] = {}
    for txn in confirmed:
        if txn.direction != TXN_EXPENSE:
            continue
        if txn.occurred_on < cycle_start:
            continue
        running = totals.setdefault(txn.category, [0, 0])
        running[0] += txn.amount.sen
        running[1] += 1
    return tuple(
        CategorySummary(
            slug=slug,
            label=label_for(slug),
            spent_this_cycle_sen=Money(spent, currency).sen,
            count=count,
        )
        for slug, (spent, count) in sorted(
            totals.items(), key=lambda item: (-item[1][0], item[0])
        )
    )


async def list_activity(
    session: AsyncSession, user: User, category: str | None = None
) -> Activity:
    """Drafts waiting for a decision, then confirmed spending grouped by day.

    `category` narrows the ledger only. The waiting drafts and the chips are
    always the whole picture, so a filter can never hide a pending decision.
    """
    drafts = (
        await session.execute(
            select(Transaction)
            .where(Transaction.user_id == user.id, Transaction.status == TXN_DRAFT)
            .order_by(Transaction.created_at.desc(), Transaction.id)
        )
    ).scalars().all()

    confirmed = (
        await session.execute(
            select(Transaction)
            .where(Transaction.user_id == user.id, Transaction.status == TXN_CONFIRMED)
            .order_by(
                Transaction.occurred_on.desc(), Transaction.created_at.desc(), Transaction.id
            )
        )
    ).scalars().all()
    categories = _summarise(confirmed, user.cycle_start, user.currency)
    shown = [
        txn
        for txn in confirmed
        if txn.direction != TXN_EXPENSE or category is None or txn.category == category
    ]

    days = tuple(
        _activity_day(occurred_on, group)
        for occurred_on, group in groupby(shown, key=lambda txn: txn.occurred_on)
    )

    draft_views = tuple(_view(txn) for txn in drafts)
    return Activity(
        drafts=draft_views,
        draft_total_sen=_total(draft_views, user.currency),
        days=days,
        spent_this_cycle_sen=_total(
            (
                _view(txn)
                for txn in shown
                if txn.direction == TXN_EXPENSE and txn.occurred_on >= user.cycle_start
            ),
            user.currency,
        ),
        income_this_cycle_sen=_total(
            (
                _view(txn)
                for txn in shown
                if txn.direction != TXN_EXPENSE and txn.occurred_on >= user.cycle_start
            ),
            user.currency,
        ),
        categories=categories,
    )


async def create_transaction(
    session: AsyncSession,
    user: User,
    *,
    merchant: str,
    amount_sen: int,
    occurred_on: date,
    category: str = "uncategorised",
    source: str = SOURCE_MANUAL,
    confidence: int | None = None,
    note: str = "",
    direction: str = TXN_EXPENSE,
    income_type: str | None = None,
) -> TransactionView:
    """Add a transaction as a draft. Nothing enters the ledger unconfirmed.

    Every capture path — typed, scanned, spoken, imported — lands here, so the
    rule that a machine-read amount is a proposal and not a fact is enforced in
    one place rather than at each caller.
    """
    if not merchant.strip():
        raise InvalidTransaction("a transaction needs a merchant")
    if amount_sen <= 0:
        raise InvalidTransaction("a transaction needs a positive amount")
    if confidence is not None and not 0 <= confidence <= 100:
        raise InvalidTransaction("confidence is a percentage")
    if direction not in TXN_DIRECTIONS:
        raise InvalidTransaction(f"direction must be one of: {', '.join(TXN_DIRECTIONS)}")
    if direction == TXN_EXPENSE and income_type is not None:
        raise InvalidTransaction("an expense cannot have an income type")
    if direction != TXN_EXPENSE and income_type not in INCOME_TYPES:
        raise InvalidTransaction(f"income_type must be one of: {', '.join(INCOME_TYPES)}")
    txn = Transaction(
        user_id=user.id,
        merchant=merchant.strip(),
        amount=Money(amount_sen, user.currency),
        category=category,
        occurred_on=occurred_on,
        status=TXN_DRAFT,
        source=source,
        confidence=confidence,
        note=note,
        direction=direction,
        income_type=income_type,
    )
    session.add(txn)
    await session.flush()
    return _view(txn)


async def _owned(session: AsyncSession, user: User, transaction_id: uuid.UUID) -> Transaction:
    """One of this user's transactions, or nothing at all.

    Every path that touches a single row goes through here, so another user's
    transaction is indistinguishable from one that does not exist.
    """
    txn = (
        await session.execute(
            select(Transaction).where(
                Transaction.id == transaction_id, Transaction.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if txn is None:
        raise TransactionNotFound(str(transaction_id))
    return txn


async def get_transaction(
    session: AsyncSession, user: User, transaction_id: uuid.UUID
) -> TransactionView:
    return _view(await _owned(session, user, transaction_id))


async def correct_draft(
    session: AsyncSession,
    user: User,
    transaction_id: uuid.UUID,
    *,
    merchant: str | None = None,
    amount_sen: int | None = None,
    category: str | None = None,
    note: str | None = None,
) -> TransactionView:
    """Fix what a draft says before it is counted. Drafts only, never the ledger.

    Every field is optional and ``None`` means "leave it": a caller fixing one
    misread amount does not have to restate the rest of the row, and cannot
    blank a field by omitting it.

    A confirmed row is refused rather than edited. Correcting one in place would
    move money that safe-to-spend has already reported, with nothing on the row
    to say it moved; ``unconfirm`` is the way back to something editable.

    Correcting the amount clears ``confidence``. A reader 71% sure of RM14.00 is
    not 71% sure of the RM19.90 the user typed over it — the figure is the
    user's now, and a UI that kept underlining it would be doubting the human.
    """
    if merchant is None and amount_sen is None and category is None and note is None:
        raise InvalidTransaction("a correction needs at least one field")
    if merchant is not None and not merchant.strip():
        raise InvalidTransaction("a transaction needs a merchant")
    if amount_sen is not None and amount_sen <= 0:
        raise InvalidTransaction("a transaction needs a positive amount")

    txn = await _owned(session, user, transaction_id)
    if txn.status != TXN_DRAFT:
        raise AlreadySettled(txn.status)

    if merchant is not None:
        txn.merchant = merchant.strip()
    if amount_sen is not None:
        txn.amount = Money(amount_sen, txn.amount.currency)
        txn.confidence = None
    if category is not None:
        txn.category = category
    if note is not None:
        txn.note = note
    await session.flush()
    return _view(txn)


async def _move(
    session: AsyncSession,
    user: User,
    transaction_id: uuid.UUID,
    *,
    expected: str,
    to: str,
    refusal: type[Exception],
) -> TransactionView:
    """Move one of the user's transactions between statuses, or refuse to."""
    txn = await _owned(session, user, transaction_id)
    if txn.status != expected:
        raise refusal(txn.status)
    txn.status = to
    await session.flush()
    return _view(txn)


async def confirm_draft(
    session: AsyncSession, user: User, transaction_id: uuid.UUID
) -> TransactionView:
    """Put a draft on the ledger, where safe-to-spend can finally see it."""
    view = await _move(
        session,
        user,
        transaction_id,
        expected=TXN_DRAFT,
        to=TXN_CONFIRMED,
        refusal=AlreadySettled,
    )
    from kira.services.clock import today_for
    from kira.services.goal_planning import recalculate_active_goal_plans

    await recalculate_active_goal_plans(
        session,
        user,
        datetime.combine(today_for(), time.min, tzinfo=UTC),
    )
    return view


async def discard_draft(
    session: AsyncSession, user: User, transaction_id: uuid.UUID
) -> TransactionView:
    """Retire a draft. The row stays for the record; the money never counted."""
    return await _move(
        session,
        user,
        transaction_id,
        expected=TXN_DRAFT,
        to=TXN_DISCARDED,
        refusal=AlreadySettled,
    )


async def unconfirm(
    session: AsyncSession, user: User, transaction_id: uuid.UUID
) -> TransactionView:
    """Take a transaction back off the ledger, undoing what a mis-tap counted."""
    transaction = await _owned(session, user, transaction_id)
    if transaction.goal_allocation_applied:
        raise IncomeAllocationExists(str(transaction_id))
    view = await _move(
        session,
        user,
        transaction_id,
        expected=TXN_CONFIRMED,
        to=TXN_DRAFT,
        refusal=NotConfirmed,
    )
    from kira.services.clock import today_for
    from kira.services.goal_planning import recalculate_active_goal_plans

    await recalculate_active_goal_plans(
        session,
        user,
        datetime.combine(today_for(), time.min, tzinfo=UTC),
    )
    return view
