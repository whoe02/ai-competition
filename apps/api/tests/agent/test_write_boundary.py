"""The write boundary, tested from the outside: propose a write, change nothing."""

from __future__ import annotations

from sqlalchemy import func, select

from kira.agent.run import resume_approval, run_turn
from kira.db.models import (
    APPROVAL_APPLIED,
    APPROVAL_PENDING,
    SOURCE_PLAN,
    TXN_CONFIRMED,
    TXN_DRAFT,
    AuditEvent,
    ButlerApproval,
    Commitment,
    Goal,
    Transaction,
)
from kira.money import Money
from kira.services.dashboard import today_dashboard
from kira.services.transactions import confirm_draft
from tests.agent.conftest import scripted_factory


async def count(session, model, **where) -> int:
    query = select(func.count()).select_from(model)
    for column, value in where.items():
        query = query.where(getattr(model, column) == value)
    return (await session.execute(query)).scalar_one()


async def a_draft(session, user, today, amount=1890) -> Transaction:
    txn = Transaction(
        user_id=user.id,
        merchant="Nasi Kandar Pelita",
        amount=Money(amount),
        category="food",
        occurred_on=today,
        status=TXN_DRAFT,
        source="receipt",
        confidence=94,
    )
    session.add(txn)
    await session.flush()
    return txn


class TestAWriteStopsAtTheBoundary:
    async def test_it_raises_one_approval_and_changes_nothing(self, session, butler, today):
        user, thread = butler
        draft = await a_draft(session, user, today)
        confirmed_before = await count(session, Transaction, status=TXN_CONFIRMED)

        result = await run_turn(
            session,
            user,
            thread,
            text="Confirm that lunch",
            today=today,
            model_factory=scripted_factory(
                ("confirm_draft", {"transaction_id": str(draft.id)})
            ),
        )

        assert result.approval is not None
        assert result.approval["tool"] == "confirm_draft"
        assert await count(session, ButlerApproval, status=APPROVAL_PENDING) == 1
        assert await count(session, Transaction, status=TXN_CONFIRMED) == confirmed_before
        assert draft.status == TXN_DRAFT

    async def test_the_summary_is_what_the_user_will_read(self, session, butler, today):
        user, thread = butler
        draft = await a_draft(session, user, today)
        result = await run_turn(
            session,
            user,
            thread,
            text="Bin that draft",
            today=today,
            model_factory=scripted_factory(
                ("discard_draft", {"transaction_id": str(draft.id)})
            ),
        )
        assert str(draft.id) in result.approval["summary"]
        assert result.approval["summary"].startswith("Discard")

    async def test_reads_run_first_so_the_card_arrives_with_its_evidence(
        self, session, butler, today
    ):
        user, thread = butler
        draft = await a_draft(session, user, today)
        result = await run_turn(
            session,
            user,
            thread,
            text="Confirm that and tell me where it leaves me",
            today=today,
            model_factory=scripted_factory(
                ("get_financial_snapshot", {}),
                ("confirm_draft", {"transaction_id": str(draft.id)}),
            ),
        )
        assert result.approval is not None
        assert "Safe to spend today" in dict(result.evidence)


class TestDeciding:
    async def test_accepting_applies_it_and_writes_an_audit_event(
        self, session, butler, today
    ):
        user, thread = butler
        draft = await a_draft(session, user, today)
        factory = scripted_factory(("confirm_draft", {"transaction_id": str(draft.id)}))
        first = await run_turn(
            session, user, thread, text="Confirm it", today=today, model_factory=factory
        )
        approval = (
            await session.execute(select(ButlerApproval).limit(1))
        ).scalar_one()

        result = await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={"action": "accept"},
            today=today,
            model_factory=factory,
        )

        assert first.approval is not None
        assert result.applied == {
            "tool": "confirm_draft",
            "summary": approval.summary,
        }
        assert draft.status == TXN_CONFIRMED
        assert approval.status == APPROVAL_APPLIED
        assert await count(session, AuditEvent, action="butler.confirm_draft") == 1
        assert approval.audit_event_id is not None

    async def test_rejecting_changes_nothing(self, session, butler, today):
        user, thread = butler
        draft = await a_draft(session, user, today)
        factory = scripted_factory(("confirm_draft", {"transaction_id": str(draft.id)}))
        await run_turn(
            session, user, thread, text="Confirm it", today=today, model_factory=factory
        )
        approval = (await session.execute(select(ButlerApproval).limit(1))).scalar_one()

        result = await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={"action": "reject"},
            today=today,
            model_factory=factory,
        )

        assert result.applied is None
        assert draft.status == TXN_DRAFT
        assert approval.status == APPROVAL_PENDING
        assert await count(session, AuditEvent) == 0

    async def test_an_edit_is_revalidated_before_it_runs(self, session, butler, today):
        """The row is not a licence to execute whatever it happens to contain."""
        user, thread = butler
        bill = (
            await session.execute(
                select(Commitment).where(Commitment.protected.is_(False)).limit(1)
            )
        ).scalar_one()
        factory = scripted_factory(
            ("update_commitment", {"commitment_id": str(bill.id), "amount_sen": 60000})
        )
        await run_turn(
            session, user, thread, text="Update that bill", today=today, model_factory=factory
        )
        approval = (await session.execute(select(ButlerApproval).limit(1))).scalar_one()
        before = bill.amount

        result = await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={
                "action": "edit",
                "args": {"commitment_id": str(bill.id), "amount_sen": -5},
            },
            today=today,
            model_factory=factory,
        )

        assert result.applied is None
        assert bill.amount == before
        assert approval.status == APPROVAL_PENDING


class TestProtectedResources:
    async def test_a_protected_bill_is_refused_before_anything_runs(
        self, session, butler, today
    ):
        user, thread = butler
        rent = (
            await session.execute(select(Commitment).where(Commitment.protected.is_(True)))
        ).scalars().first()
        result = await run_turn(
            session,
            user,
            thread,
            text="Cut the rent",
            today=today,
            model_factory=scripted_factory(
                ("update_commitment", {"commitment_id": str(rent.id), "amount_sen": 1000})
            ),
        )
        assert result.approval is None
        assert await count(session, ButlerApproval) == 0
        assert rent.amount == Money(120000)

    async def test_the_buffer_cannot_be_named_in_any_call(self, session, butler, today):
        user, thread = butler
        result = await run_turn(
            session,
            user,
            thread,
            text="Drop my buffer to nothing",
            today=today,
            model_factory=scripted_factory(("update_goal", {"buffer_sen": 0})),
        )
        assert result.approval is None
        assert await count(session, ButlerApproval) == 0

    async def test_an_unknown_tool_is_refused(self, session, butler, today):
        user, thread = butler
        result = await run_turn(
            session,
            user,
            thread,
            text="Pay my rent",
            today=today,
            model_factory=scripted_factory(("apply_plan_change", {"amount_sen": 100})),
        )
        assert result.approval is None
        assert await count(session, ButlerApproval) == 0

    async def test_only_one_write_is_proposed_at_a_time(self, session, butler, today):
        user, thread = butler
        first = await a_draft(session, user, today)
        second = await a_draft(session, user, today, amount=1400)
        result = await run_turn(
            session,
            user,
            thread,
            text="Confirm both",
            today=today,
            model_factory=scripted_factory(
                ("confirm_draft", {"transaction_id": str(first.id)}),
                ("confirm_draft", {"transaction_id": str(second.id)}),
            ),
        )
        assert await count(session, ButlerApproval) == 1
        assert result.approval["args"]["transaction_id"] == str(first.id)

    async def test_bad_arguments_are_refused_with_a_reason(self, session, butler, today):
        user, thread = butler
        before = await count(session, Transaction)
        result = await run_turn(
            session,
            user,
            thread,
            text="Add a transaction",
            today=today,
            model_factory=scripted_factory(
                ("add_transaction", {"merchant": "", "amount_sen": -1})
            ),
        )
        assert result.approval is None
        assert await count(session, ButlerApproval) == 0
        assert await count(session, Transaction) == before


class TestAddingAPlaceToToday:
    """The day planner's own write, held to the boundary like every other one.

    Checked here rather than trusted by analogy with ``add_transaction``: this
    is the one write whose arguments name something outside the database, so
    the id has to be resolved before a card is raised and again before it runs.

    Mamak Dua is RM12.50 and half a kilometre away. Walking costs nothing, so
    the whole outing is the meal, and every figure below is that RM12.50.
    """

    def proposed(self, place_world, place=None, total_sen=1250) -> tuple:
        chosen = place or place_world.mid
        return (
            "add_place_to_today",
            {
                "place_id": chosen.id,
                "name": chosen.name,
                "total_sen": total_sen,
                **place_world.origin,
            },
        )

    async def plans(self, session) -> list[Transaction]:
        return list(
            (
                await session.execute(
                    select(Transaction).where(Transaction.source == SOURCE_PLAN)
                )
            )
            .scalars()
            .all()
        )

    async def propose(self, session, user, thread, today, factory):
        await run_turn(
            session,
            user,
            thread,
            text="Add the second one",
            today=today,
            model_factory=factory,
        )
        return (await session.execute(select(ButlerApproval).limit(1))).scalar_one()

    async def test_proposing_it_touches_no_financial_table(
        self, session, butler, today, place_world
    ):
        user, thread = butler
        before = (
            await count(session, Transaction),
            await count(session, Goal),
            await count(session, Commitment),
        )

        result = await run_turn(
            session,
            user,
            thread,
            text="Add the second one",
            today=today,
            model_factory=scripted_factory(self.proposed(place_world)),
        )

        assert result.approval is not None
        assert result.approval["tool"] == "add_place_to_today"
        assert result.approval["module"] == "day_plan"
        assert await count(session, ButlerApproval, status=APPROVAL_PENDING) == 1
        assert (
            await count(session, Transaction),
            await count(session, Goal),
            await count(session, Commitment),
        ) == before

    async def test_the_card_names_the_place_the_price_and_the_draft(
        self, session, butler, today, place_world
    ):
        user, thread = butler
        result = await run_turn(
            session,
            user,
            thread,
            text="Add the second one",
            today=today,
            model_factory=scripted_factory(self.proposed(place_world)),
        )

        summary = result.approval["summary"]
        assert summary.startswith("Add Mamak Dua for RM12.50")
        # The one thing the user must not have to infer: this is not a spend.
        assert "draft" in summary
        assert "Nothing counts against today until you confirm it." in summary

    async def test_accepting_leaves_exactly_one_plan_draft(
        self, session, butler, today, place_world
    ):
        user, thread = butler
        factory = scripted_factory(self.proposed(place_world))
        approval = await self.propose(session, user, thread, today, factory)

        result = await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={"action": "accept"},
            today=today,
            model_factory=factory,
        )

        assert result.applied == {
            "tool": "add_place_to_today",
            "summary": approval.summary,
        }
        drafts = await self.plans(session)
        assert len(drafts) == 1
        assert drafts[0].merchant == "Mamak Dua"
        assert drafts[0].amount == Money(1250)
        assert drafts[0].status == TXN_DRAFT
        assert drafts[0].category == "food"
        assert drafts[0].occurred_on == today
        # Mamak Dua's band is "high". The model never sent a percentage and
        # could not have: what a band is worth is the server's to decide.
        assert drafts[0].confidence == 70
        assert await count(session, AuditEvent, action="butler.add_place_to_today") == 1

    async def test_the_day_does_not_move_until_the_draft_is_confirmed(
        self, session, butler, today, place_world
    ):
        user, thread = butler
        factory = scripted_factory(self.proposed(place_world))
        before = (await today_dashboard(session, user, today)).safe_today_sen

        approval = await self.propose(session, user, thread, today, factory)
        await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={"action": "accept"},
            today=today,
            model_factory=factory,
        )
        during = (await today_dashboard(session, user, today)).safe_today_sen

        draft = (await self.plans(session))[0]
        await confirm_draft(session, user, draft.id)
        after = (await today_dashboard(session, user, today)).safe_today_sen

        # An intention costs nothing. The row is there — and the figure the user
        # is judging the rest of the day on has not moved a sen.
        assert during == before
        # Confirmed, and only now, it counts. The drop is not the RM12.50: the
        # allowance is respread over what is left of the cycle.
        assert after < before

    async def test_an_unknown_place_id_is_refused_without_a_write(
        self, session, butler, today, place_world
    ):
        user, thread = butler
        result = await run_turn(
            session,
            user,
            thread,
            text="Add the second one",
            today=today,
            model_factory=scripted_factory(
                (
                    "add_place_to_today",
                    {
                        "place_id": "no-such-place",
                        "name": "Somewhere I Made Up",
                        "total_sen": 1250,
                        **place_world.origin,
                    },
                )
            ),
        )

        # Refused where every other bad call is refused: in the guard, as a tool
        # result the model can read, with no card raised and no row written.
        assert result.approval is None
        assert await count(session, ButlerApproval) == 0
        assert await self.plans(session) == []

    async def test_a_real_place_out_of_range_is_refused_the_same_way(
        self, session, butler, today, place_world
    ):
        """An id is only a handle on a row the user was actually shown.

        Kopi Kaki exists, and from Penang it is 294 km away and in nobody's
        plan. Resolving it anyway would put a place on today that no list this
        conversation produced ever offered.
        """
        user, thread = butler
        result = await run_turn(
            session,
            user,
            thread,
            text="Add the first one",
            today=today,
            model_factory=scripted_factory(
                (
                    "add_place_to_today",
                    {
                        "place_id": place_world.cheap.id,
                        "name": place_world.cheap.name,
                        "total_sen": 900,
                        **place_world.out_of_range,
                    },
                )
            ),
        )

        assert result.approval is None
        assert await count(session, ButlerApproval) == 0
        assert await self.plans(session) == []

    async def test_an_edit_naming_a_place_that_does_not_exist_is_refused(
        self, session, butler, today, place_world
    ):
        """The row is not a licence to execute whatever it happens to contain."""
        user, thread = butler
        factory = scripted_factory(self.proposed(place_world))
        approval = await self.propose(session, user, thread, today, factory)

        result = await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={
                "action": "edit",
                "args": {
                    "place_id": "no-such-place",
                    "name": "Somewhere I Made Up",
                    "total_sen": 1250,
                    **place_world.origin,
                },
            },
            today=today,
            model_factory=factory,
        )

        assert result.applied is None
        assert await self.plans(session) == []
        assert approval.status == APPROVAL_PENDING

    async def test_an_edit_to_another_place_is_resolved_afresh(
        self, session, butler, today, place_world
    ):
        """The checks run against the edited place, not the proposed one.

        Omakase Empat's band is "low" where Mamak Dua's is "high", so the
        percentage on the draft is the tell: 30 could only have come from
        resolving the place the edit named.
        """
        user, thread = butler
        factory = scripted_factory(self.proposed(place_world))
        approval = await self.propose(session, user, thread, today, factory)

        result = await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={
                "action": "edit",
                "args": {
                    "place_id": place_world.pricey.id,
                    "name": place_world.pricey.name,
                    "total_sen": 5000,
                    **place_world.origin,
                },
            },
            today=today,
            model_factory=factory,
        )

        assert result.applied is not None
        drafts = await self.plans(session)
        assert len(drafts) == 1
        assert drafts[0].merchant == "Omakase Empat"
        assert drafts[0].amount == Money(5000)
        assert drafts[0].confidence == 30
        assert drafts[0].status == TXN_DRAFT


class TestApprovalIdempotence:
    async def test_a_replayed_node_does_not_ask_twice(self, session, butler, today):
        """A resumed graph re-runs the node from its start; one question, one row."""
        user, thread = butler
        draft = await a_draft(session, user, today)
        factory = scripted_factory(("confirm_draft", {"transaction_id": str(draft.id)}))
        await run_turn(
            session, user, thread, text="Confirm it", today=today, model_factory=factory
        )
        approval = (await session.execute(select(ButlerApproval).limit(1))).scalar_one()
        await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={"action": "accept"},
            today=today,
            model_factory=factory,
        )
        assert await count(session, ButlerApproval) == 1


class TestAnEditIsRecordedAsWhatRan:
    """What the row, the audit event and the confirmation say after an edit.

    The summary the user approved was composed from the proposal. An edit
    replaces the arguments, so that sentence now describes a change nobody
    made — and it is the sentence that reaches the audit trail, the settled
    approval row and the line the screen confirms with. A record whose words
    and whose arguments describe different writes is worse than no record.
    """

    async def test_the_summary_settled_is_the_one_that_ran(
        self, session, butler, today, place_world
    ):
        user, thread = butler
        factory = scripted_factory(
            (
                "add_place_to_today",
                {
                    "place_id": place_world.mid.id,
                    "name": place_world.mid.name,
                    "total_sen": 1250,
                    **place_world.origin,
                },
            )
        )
        await run_turn(
            session, user, thread, text="Add that one", today=today, model_factory=factory
        )
        approval = (await session.execute(select(ButlerApproval).limit(1))).scalar_one()
        assert approval.summary.startswith("Add Mamak Dua for RM12.50")

        result = await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={
                "action": "edit",
                "args": {
                    "place_id": place_world.pricey.id,
                    "name": place_world.pricey.name,
                    "total_sen": 5000,
                    **place_world.origin,
                },
            },
            today=today,
            model_factory=factory,
        )

        landed = (
            await session.execute(select(Transaction).where(Transaction.source == SOURCE_PLAN))
        ).scalars().one()
        assert (landed.merchant, landed.amount) == ("Omakase Empat", Money(5000))

        # All three say the same thing, and it is the thing that happened.
        assert result.applied["summary"].startswith("Add Omakase Empat for RM50.00")
        assert approval.summary.startswith("Add Omakase Empat for RM50.00")
        event = (
            await session.execute(
                select(AuditEvent).where(AuditEvent.action == "butler.add_place_to_today")
            )
        ).scalars().one()
        assert event.detail["summary"].startswith("Add Omakase Empat for RM50.00")
        assert event.detail["args"]["name"] == "Omakase Empat"

    async def test_an_accept_leaves_the_wording_exactly_as_approved(
        self, session, butler, today, place_world
    ):
        """Nothing edited, nothing reworded: the user's own card, settled."""
        user, thread = butler
        factory = scripted_factory(
            (
                "add_place_to_today",
                {
                    "place_id": place_world.mid.id,
                    "name": place_world.mid.name,
                    "total_sen": 1250,
                    **place_world.origin,
                },
            )
        )
        first = await run_turn(
            session, user, thread, text="Add that one", today=today, model_factory=factory
        )
        approval = (await session.execute(select(ButlerApproval).limit(1))).scalar_one()
        shown = first.approval["summary"]

        result = await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={"action": "accept"},
            today=today,
            model_factory=factory,
        )

        assert result.applied["summary"] == shown
        assert approval.summary == shown
