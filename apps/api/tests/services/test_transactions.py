from datetime import date

import pytest

from kira.db.models import TXN_CONFIRMED, TXN_DISCARDED, TXN_DRAFT, Transaction, User
from kira.engine import safe_to_spend
from kira.money import Money
from kira.seed.demo import DEMO_TODAY, seed_demo_user
from kira.services.snapshot import load_snapshot
from kira.services.transactions import (
    AlreadySettled,
    InvalidTransaction,
    NotConfirmed,
    TransactionNotFound,
    confirm_draft,
    correct_draft,
    discard_draft,
    list_activity,
    unconfirm,
)


async def demo(session):
    user = await seed_demo_user(session)
    await session.flush()
    return user


async def stranger_with_a_draft(session) -> Transaction:
    """A second user's draft, used to prove ownership is checked."""
    other = User(
        email="stranger@kira.app",
        password_hash="x",
        display_name="Stranger",
        buffer=Money(0),
        next_payday=date(2026, 9, 25),
        cycle_start=date(2026, 8, 26),
    )
    session.add(other)
    await session.flush()
    draft = Transaction(
        user_id=other.id,
        merchant="Not yours",
        amount=Money(9999),
        category="Food",
        occurred_on=date(2026, 9, 2),
        status=TXN_DRAFT,
        source="manual",
    )
    session.add(draft)
    await session.flush()
    return draft


class TestListActivity:
    async def test_lists_the_waiting_drafts_newest_first(self, session):
        user = await demo(session)
        activity = await list_activity(session, user)
        assert [draft.merchant for draft in activity.drafts] == [
            "Grab — office to KLCC",
            "Nasi Kandar Pelita",
        ]
        assert activity.draft_total_sen == 3290

    async def test_groups_confirmed_spending_by_day_newest_first(self, session):
        user = await demo(session)
        activity = await list_activity(session, user)
        assert [day.date for day in activity.days][:2] == [
            date(2026, 9, 2),
            date(2026, 9, 1),
        ]
        assert activity.days[0].total_sen == 2870
        assert [txn.merchant for txn in activity.days[0].transactions] == [
            "Grab — KLCC to home",
            "Family Mart",
        ]

    async def test_totals_the_cycle_without_counting_drafts(self, session):
        user = await demo(session)
        activity = await list_activity(session, user)
        assert activity.spent_this_cycle_sen == 63135

    async def test_leaves_out_another_users_spending(self, session):
        user = await demo(session)
        stranger_draft = await stranger_with_a_draft(session)
        activity = await list_activity(session, user)
        assert stranger_draft.id not in {draft.id for draft in activity.drafts}
        assert activity.spent_this_cycle_sen == 63135

    async def test_hides_discarded_drafts(self, session):
        user = await demo(session)
        draft = (await list_activity(session, user)).drafts[0]
        await discard_draft(session, user, draft.id)
        activity = await list_activity(session, user)
        assert draft.id not in {waiting.id for waiting in activity.drafts}
        assert len(activity.drafts) == 1


class TestConfirmDraft:
    async def test_moves_the_draft_onto_the_ledger(self, session):
        user = await demo(session)
        draft = next(d for d in (await list_activity(session, user)).drafts if d.amount_sen == 1890)
        before = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))

        confirmed = await confirm_draft(session, user, draft.id)

        assert confirmed.status == TXN_CONFIRMED
        after = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))
        # More than RM18.90: the money leaves today's spending *and* the balance,
        # so the remaining days each lose their share of it too.
        assert before.safe_today == Money(5297)
        assert after.safe_today == Money(3321)

    async def test_refuses_a_draft_that_is_not_the_users(self, session):
        user = await demo(session)
        stranger_draft = await stranger_with_a_draft(session)
        with pytest.raises(TransactionNotFound):
            await confirm_draft(session, user, stranger_draft.id)
        assert (await session.get(Transaction, stranger_draft.id)).status == TXN_DRAFT

    async def test_refuses_to_confirm_twice(self, session):
        user = await demo(session)
        draft = (await list_activity(session, user)).drafts[0]
        await confirm_draft(session, user, draft.id)
        with pytest.raises(AlreadySettled):
            await confirm_draft(session, user, draft.id)


class TestDiscardDraft:
    async def test_leaves_the_money_untouched(self, session):
        user = await demo(session)
        draft = (await list_activity(session, user)).drafts[0]
        before = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))

        discarded = await discard_draft(session, user, draft.id)

        assert discarded.status == TXN_DISCARDED
        after = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))
        assert after.safe_today == before.safe_today

    async def test_keeps_the_row_for_the_record(self, session):
        user = await demo(session)
        draft = (await list_activity(session, user)).drafts[0]
        await discard_draft(session, user, draft.id)
        assert await session.get(Transaction, draft.id) is not None

    async def test_refuses_to_discard_a_confirmed_transaction(self, session):
        user = await demo(session)
        draft = (await list_activity(session, user)).drafts[0]
        await confirm_draft(session, user, draft.id)
        with pytest.raises(AlreadySettled):
            await discard_draft(session, user, draft.id)


class TestUnconfirm:
    async def test_returns_a_confirmed_transaction_to_the_drafts(self, session):
        user = await demo(session)
        draft = (await list_activity(session, user)).drafts[0]
        await confirm_draft(session, user, draft.id)

        returned = await unconfirm(session, user, draft.id)

        assert returned.status == TXN_DRAFT
        assert draft.id in {waiting.id for waiting in (await list_activity(session, user)).drafts}

    async def test_gives_the_money_back_to_today(self, session):
        user = await demo(session)
        before = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))
        draft = (await list_activity(session, user)).drafts[0]
        await confirm_draft(session, user, draft.id)

        await unconfirm(session, user, draft.id)

        after = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))
        assert after.safe_today == before.safe_today

    async def test_refuses_a_draft_that_was_never_confirmed(self, session):
        user = await demo(session)
        draft = (await list_activity(session, user)).drafts[0]
        with pytest.raises(NotConfirmed):
            await unconfirm(session, user, draft.id)

    async def test_refuses_a_discarded_transaction(self, session):
        user = await demo(session)
        draft = (await list_activity(session, user)).drafts[0]
        await discard_draft(session, user, draft.id)
        with pytest.raises(NotConfirmed):
            await unconfirm(session, user, draft.id)

    async def test_refuses_a_transaction_that_is_not_the_users(self, session):
        user = await demo(session)
        stranger_draft = await stranger_with_a_draft(session)
        with pytest.raises(TransactionNotFound):
            await unconfirm(session, user, stranger_draft.id)


class TestCorrectDraft:
    """The voice draft is the one the fake reader is only 71% sure of: RM14.00
    heard, RM19.90 spent. Correcting it is the whole reason confidence is shown.
    """

    async def misheard(self, session, user) -> Transaction:
        drafts = (await list_activity(session, user)).drafts
        draft = next(d for d in drafts if d.merchant == "Grab — office to KLCC")
        assert draft.amount_sen == 1400
        assert draft.confidence == 71
        return draft

    async def test_takes_the_users_amount_over_the_readers(self, session):
        user = await demo(session)
        draft = await self.misheard(session, user)

        corrected = await correct_draft(session, user, draft.id, amount_sen=1990)

        assert corrected.amount_sen == 1990
        assert corrected.status == TXN_DRAFT
        assert (await session.get(Transaction, draft.id)).amount == Money(1990)

    async def test_correcting_the_amount_clears_the_confidence(self, session):
        user = await demo(session)
        draft = await self.misheard(session, user)

        corrected = await correct_draft(session, user, draft.id, amount_sen=1990)

        # 71% sure of RM14.00 says nothing about the RM19.90 the user typed:
        # the figure is theirs now, and nothing should still underline it.
        assert corrected.confidence is None
        assert (await session.get(Transaction, draft.id)).confidence is None

    async def test_leaves_the_confidence_alone_when_the_amount_is_not_touched(self, session):
        user = await demo(session)
        draft = await self.misheard(session, user)

        corrected = await correct_draft(session, user, draft.id, category="fun")

        assert corrected.confidence == 71
        assert corrected.category == "fun"

    async def test_corrects_the_merchant_note_and_category_too(self, session):
        user = await demo(session)
        draft = await self.misheard(session, user)

        corrected = await correct_draft(
            session,
            user,
            draft.id,
            merchant="  Grab — office to Mid Valley  ",
            category="transport",
            note="",
        )

        assert corrected.merchant == "Grab — office to Mid Valley"
        assert corrected.category == "transport"
        assert corrected.note == ""

    async def test_leaves_out_of_what_was_not_named(self, session):
        user = await demo(session)
        draft = await self.misheard(session, user)

        corrected = await correct_draft(session, user, draft.id, amount_sen=1990)

        assert corrected.merchant == "Grab — office to KLCC"
        assert corrected.category == "transport"
        assert corrected.occurred_on == draft.occurred_on
        assert corrected.source == draft.source

    async def test_refuses_a_confirmed_transaction(self, session):
        user = await demo(session)
        draft = await self.misheard(session, user)
        await confirm_draft(session, user, draft.id)

        with pytest.raises(AlreadySettled):
            await correct_draft(session, user, draft.id, amount_sen=1990)

        # Silently rewriting it would move money safe-to-spend has already counted.
        assert (await session.get(Transaction, draft.id)).amount == Money(1400)

    async def test_refuses_a_discarded_transaction(self, session):
        user = await demo(session)
        draft = await self.misheard(session, user)
        await discard_draft(session, user, draft.id)

        with pytest.raises(AlreadySettled):
            await correct_draft(session, user, draft.id, amount_sen=1990)

        assert (await session.get(Transaction, draft.id)).amount == Money(1400)

    async def test_a_row_unconfirmed_back_to_a_draft_is_correctable_again(self, session):
        user = await demo(session)
        draft = await self.misheard(session, user)
        await confirm_draft(session, user, draft.id)
        await unconfirm(session, user, draft.id)

        assert (await correct_draft(session, user, draft.id, amount_sen=1990)).amount_sen == 1990

    async def test_refuses_a_transaction_that_is_not_the_users(self, session):
        user = await demo(session)
        stranger_draft = await stranger_with_a_draft(session)

        with pytest.raises(TransactionNotFound):
            await correct_draft(session, user, stranger_draft.id, amount_sen=1990)

        assert (await session.get(Transaction, stranger_draft.id)).amount == Money(9999)

    async def test_refuses_a_zero_amount(self, session):
        user = await demo(session)
        draft = await self.misheard(session, user)
        with pytest.raises(InvalidTransaction):
            await correct_draft(session, user, draft.id, amount_sen=0)
        assert (await session.get(Transaction, draft.id)).amount == Money(1400)

    async def test_refuses_a_negative_amount(self, session):
        user = await demo(session)
        draft = await self.misheard(session, user)
        with pytest.raises(InvalidTransaction):
            await correct_draft(session, user, draft.id, amount_sen=-1990)
        assert (await session.get(Transaction, draft.id)).amount == Money(1400)

    async def test_refuses_a_blank_merchant(self, session):
        user = await demo(session)
        draft = await self.misheard(session, user)
        with pytest.raises(InvalidTransaction):
            await correct_draft(session, user, draft.id, merchant="   ")

    async def test_refuses_a_correction_that_corrects_nothing(self, session):
        user = await demo(session)
        draft = await self.misheard(session, user)
        with pytest.raises(InvalidTransaction):
            await correct_draft(session, user, draft.id)

    async def test_the_corrected_figure_is_what_confirm_puts_on_the_ledger(self, session):
        user = await demo(session)
        draft = await self.misheard(session, user)

        await correct_draft(session, user, draft.id, amount_sen=1990)
        await confirm_draft(session, user, draft.id)

        activity = await list_activity(session, user)
        confirmed = next(
            txn
            for day in activity.days
            for txn in day.transactions
            if txn.id == draft.id
        )
        assert confirmed.amount_sen == 1990
        assert activity.spent_this_cycle_sen == 63135 + 1990

    async def test_safe_to_spend_reflects_the_corrected_figure(self, session):
        user = await demo(session)
        draft = await self.misheard(session, user)
        before = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))

        await correct_draft(session, user, draft.id, amount_sen=1990)
        await confirm_draft(session, user, draft.id)
        after = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))

        # RM19.90 leaves both today's spending and the balance, so the day loses
        # more than the correction itself — but it is the corrected RM19.90 that
        # is spent, never the RM14.00 the reader offered.
        assert before.safe_today == Money(5297)
        assert after.safe_today == Money(3216)


class TestCategoryChips:
    async def test_summarises_only_the_categories_actually_present(self, session):
        user = await demo(session)
        activity = await list_activity(session, user)
        present = {summary.slug for summary in activity.categories}
        assert "food" in present
        assert "bills" not in present  # rent and phone are commitments, not spending

    async def test_labels_each_category_for_a_person(self, session):
        user = await demo(session)
        activity = await list_activity(session, user)
        food = next(c for c in activity.categories if c.slug == "food")
        assert food.label == "Food & drink"

    async def test_totals_and_counts_each_category(self, session):
        user = await demo(session)
        activity = await list_activity(session, user)
        food = next(c for c in activity.categories if c.slug == "food")
        assert food.spent_this_cycle_sen == 2350 + 1190 + 890
        assert food.count == 3

    async def test_orders_the_chips_by_what_costs_most(self, session):
        user = await demo(session)
        activity = await list_activity(session, user)
        totals = [summary.spent_this_cycle_sen for summary in activity.categories]
        assert totals == sorted(totals, reverse=True)

    async def test_leaves_the_chips_alone_when_a_filter_is_on(self, session):
        user = await demo(session)
        everything = await list_activity(session, user)
        filtered = await list_activity(session, user, category="food")
        assert filtered.categories == everything.categories


class TestFilteringByCategory:
    async def test_narrows_the_ledger_to_one_category(self, session):
        user = await demo(session)
        activity = await list_activity(session, user, category="health")
        merchants = {txn.merchant for day in activity.days for txn in day.transactions}
        assert {"Watsons", "Guardian pharmacy"} <= merchants
        assert all(
            txn.category == "health" for day in activity.days for txn in day.transactions
        )

    async def test_retotals_the_cycle_for_what_is_shown(self, session):
        user = await demo(session)
        activity = await list_activity(session, user, category="health")
        assert activity.spent_this_cycle_sen == 3560 + 2480

    async def test_retotals_each_day_for_what_is_shown(self, session):
        user = await demo(session)
        activity = await list_activity(session, user, category="transport")
        september_first = next(day for day in activity.days if day.date == date(2026, 9, 1))
        assert september_first.total_sen == 5000  # the Touch 'n Go reload, not the restoran

    async def test_an_unknown_category_shows_an_empty_ledger(self, session):
        user = await demo(session)
        activity = await list_activity(session, user, category="pet-grooming")
        assert activity.days == ()
        assert activity.spent_this_cycle_sen == 0
        assert activity.categories  # the chips still say what is there

    async def test_leaves_the_waiting_drafts_alone(self, session):
        user = await demo(session)
        activity = await list_activity(session, user, category="health")
        assert len(activity.drafts) == 2
        assert activity.draft_total_sen == 3290
