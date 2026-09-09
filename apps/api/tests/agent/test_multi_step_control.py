"""What the Butler can carry out, rather than only propose.

Three gaps closed here, and they are all the same gap seen from different
sides: the user said something, the app can do it, and the Butler could not.

- A turn used to end at its first applied write, so half of "log the lunch and
  the coffee" was silently dropped.
- `forget` and `correct_memory` take an id that nothing in the turn ever
  produced, so a memory the user could see and delete in the UI was one the
  Butler could not touch.
- The nightly money check was on the Today screen and in no tool.
"""

from __future__ import annotations

from sqlalchemy import func, select

from kira.agent import prompt
from kira.agent.nodes.approve import route_after_approval
from kira.agent.run import resume_approval, run_turn
from kira.agent.tools import REGISTRY, ToolContext
from kira.db.models import TXN_DRAFT, ButlerApproval, ButlerMemory, Transaction
from kira.seed.demo import DEMO_TODAY
from kira.services import briefings as briefing_service
from kira.services import butler_memory
from kira.services.dashboard import today_dashboard
from kira.services.snapshot import load_snapshot
from tests.agent.conftest import scripted_factory, sequenced_factory


async def pending(session, thread, tool: str) -> ButlerApproval:
    """The card currently waiting on this thread for this tool."""
    return (
        await session.execute(
            select(ButlerApproval)
            .where(
                ButlerApproval.thread_id == thread.id,
                ButlerApproval.tool == tool,
                ButlerApproval.status == "pending",
            )
            .order_by(ButlerApproval.created_at.desc())
        )
    ).scalars().first()


async def drafts(session, user) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.user_id == user.id, Transaction.status == TXN_DRAFT)
        )
    ).scalar_one()


def two_lunches(today):
    """A turn that owes two writes: the model proposes them one pass apart."""
    return sequenced_factory(
        [("add_transaction", {
            "merchant": "Nasi Kandar", "amount_sen": 1200,
            "occurred_on": today.isoformat(), "category": "food",
        })],
        [("add_transaction", {
            "merchant": "Kopitiam", "amount_sen": 500,
            "occurred_on": today.isoformat(), "category": "food",
        })],
    )


class TestATurnFinishesWhatItStarted:
    """The user said two things. Both of them happen, or the turn says why."""

    async def test_approving_the_first_write_raises_the_second(
        self, session, butler, today
    ):
        user, thread = butler
        before = await drafts(session, user)
        factory = two_lunches(today)

        result = await run_turn(
            session, user, thread,
            text="log my RM12 lunch and my RM5 coffee",
            today=today, model_factory=factory,
        )
        assert result.approval["tool"] == "add_transaction"
        assert await drafts(session, user) == before

        first = await pending(session, thread, "add_transaction")
        result = await resume_approval(
            session, user, thread, graph_thread=first.graph_thread_id,
            decision={"action": "accept"}, today=today, model_factory=factory,
        )

        # The turn did not end at the lunch. This is the whole fix: the model
        # read `{"applied": true}` as a result and proposed the coffee.
        assert result.applied["tool"] == "add_transaction"
        assert result.approval is not None
        assert result.approval["args"]["merchant"] == "Kopitiam"
        assert await drafts(session, user) == before + 1

    async def test_both_land_once_both_are_approved(self, session, butler, today):
        user, thread = butler
        before = await drafts(session, user)
        factory = two_lunches(today)

        await run_turn(
            session, user, thread,
            text="log my RM12 lunch and my RM5 coffee",
            today=today, model_factory=factory,
        )
        for _ in range(2):
            card = await pending(session, thread, "add_transaction")
            assert card is not None
            await resume_approval(
                session, user, thread, graph_thread=card.graph_thread_id,
                decision={"action": "accept"}, today=today, model_factory=factory,
            )

        assert await drafts(session, user) == before + 2
        assert await pending(session, thread, "add_transaction") is None

    async def test_a_rejection_does_not_re_enter_the_loop(self, session, butler, today):
        """Saying no ends the turn. It does not invite the next proposal."""
        user, thread = butler
        before = await drafts(session, user)
        factory = two_lunches(today)

        await run_turn(
            session, user, thread,
            text="log my RM12 lunch and my RM5 coffee",
            today=today, model_factory=factory,
        )
        first = await pending(session, thread, "add_transaction")
        result = await resume_approval(
            session, user, thread, graph_thread=first.graph_thread_id,
            decision={"action": "reject"}, today=today, model_factory=factory,
        )

        assert result.applied is None
        assert result.approval is None
        assert await drafts(session, user) == before

    async def test_the_route_is_what_says_so(self):
        """The rule, stated once, where the graph reads it."""
        assert route_after_approval({"applied": {"tool": "add_transaction"}}) == "agent"
        assert route_after_approval({"applied": None}) == "compose"
        assert route_after_approval({}) == "compose"

    async def test_an_approved_write_restarts_the_wall_clock(
        self, session, butler, today
    ):
        """A user staring at a card is not the turn spending its budget.

        Without this the continuation is refused on its first pass every time:
        `started_at` was marked before the interrupt, and the wait between is
        however long a human took to read a sentence.
        """
        user, thread = butler
        factory = two_lunches(today)
        await run_turn(
            session, user, thread,
            text="log my RM12 lunch and my RM5 coffee",
            today=today, model_factory=factory,
        )
        first = await pending(session, thread, "add_transaction")
        result = await resume_approval(
            session, user, thread, graph_thread=first.graph_thread_id,
            decision={"action": "accept"}, today=today, model_factory=factory,
        )
        # A stale clock would have the guard refuse everything on the pass after
        # the approval, and no second card could exist.
        assert result.approval is not None


class TestTheMemoryLoopCloses:
    """A fact the user can see is a fact the Butler can be told to change."""

    async def test_the_remembered_rows_carry_the_id_the_tools_take(
        self, session, butler
    ):
        user, _ = butler
        view = await butler_memory.remember(
            session, user, kind="preference", subject="sushi",
            fact="They do not like sushi.",
        )
        block = prompt.memory_block(
            await butler_memory.list_memories(session, user)
        )
        assert str(view.id) in block
        assert "They do not like sushi." in block
        # Said out loud in the block itself, because an id read aloud is worse
        # than no id at all.
        assert "never say one out loud" in block

    async def test_list_memories_hands_back_the_id_not_just_the_words(
        self, session, butler
    ):
        """The lookup exists to produce ids, so that is what is asserted.

        A version returning only the prose would read correctly in the panel and
        still leave `forget` uncallable, which is the bug this closes.
        """
        user, _ = butler
        view = await butler_memory.remember(
            session, user, kind="preference", subject="sushi",
            fact="They do not like sushi.",
        )
        spec = REGISTRY.get("list_memories")
        result = await spec.handler(
            ToolContext(
                session=session,
                user=user,
                today=DEMO_TODAY,
                snapshot=await load_snapshot(session, user, DEMO_TODAY),
                dashboard=await today_dashboard(session, user, DEMO_TODAY),
            ),
            spec.args_model.model_validate({}),
        )
        assert [row["id"] for row in result.value] == [str(view.id)]
        assert result.value[0]["fact"] == "They do not like sushi."

    async def test_the_lookup_reaches_the_model_through_the_graph(
        self, session, butler, today
    ):
        user, thread = butler
        await butler_memory.remember(
            session, user, kind="preference", subject="sushi",
            fact="They do not like sushi.",
        )
        result = await run_turn(
            session, user, thread, text="what do you remember about me",
            today=today, model_factory=scripted_factory(("list_memories", {})),
        )
        assert "list_memories" in result.tools_used
        assert any(row[1] == "They do not like sushi." for row in result.evidence)

    async def test_forgetting_a_fact_waits_for_approval_and_then_deletes_it(
        self, session, butler, today
    ):
        user, thread = butler
        view = await butler_memory.remember(
            session, user, kind="preference", subject="sushi",
            fact="They do not like sushi.",
        )
        factory = scripted_factory(("forget", {"memory_id": str(view.id)}))

        result = await run_turn(
            session, user, thread, text="forget that I dislike sushi",
            today=today, model_factory=factory,
        )
        assert result.approval["tool"] == "forget"
        assert len(await butler_memory.list_memories(session, user)) == 1

        card = await pending(session, thread, "forget")
        await resume_approval(
            session, user, thread, graph_thread=card.graph_thread_id,
            decision={"action": "accept"}, today=today, model_factory=factory,
        )
        assert await butler_memory.list_memories(session, user) == ()

    async def test_correcting_a_fact_rewrites_it_in_place(
        self, session, butler, today
    ):
        user, thread = butler
        view = await butler_memory.remember(
            session, user, kind="person", subject="housemate",
            fact="Their housemate is called Sam.",
        )
        factory = scripted_factory(("correct_memory", {
            "memory_id": str(view.id), "fact": "Their housemate is called Sam Tan.",
        }))

        result = await run_turn(
            session, user, thread, text="my housemate is Sam Tan actually",
            today=today, model_factory=factory,
        )
        assert result.approval["tool"] == "correct_memory"
        assert "Sam Tan" in result.approval["summary"]

        card = await pending(session, thread, "correct_memory")
        await resume_approval(
            session, user, thread, graph_thread=card.graph_thread_id,
            decision={"action": "accept"}, today=today, model_factory=factory,
        )
        row = (
            await session.execute(
                select(ButlerMemory).where(ButlerMemory.id == view.id)
            )
        ).scalar_one()
        # The same row, corrected — not a second fact sitting beside the wrong one.
        assert row.fact == "Their housemate is called Sam Tan."
        assert len(await butler_memory.list_memories(session, user)) == 1

    async def test_a_correction_is_a_write_and_a_lookup_is_not(self):
        assert REGISTRY.get("correct_memory").is_write
        assert not REGISTRY.get("list_memories").is_write


class TestTheNightlyCheckIsReadable:
    async def test_it_reports_the_night_that_ran(self, session, butler, today):
        user, thread = butler
        run = await briefing_service.nightly_briefing(session, user, today)

        result = await run_turn(
            session, user, thread, text="what did you find last night",
            today=today, model_factory=scripted_factory(("read_briefing", {})),
        )
        assert "read_briefing" in result.tools_used
        assert any(run.summary == row[1] for row in result.evidence)

    async def test_a_night_that_never_ran_is_said_plainly(
        self, session, butler, today
    ):
        """No briefing is a fact to report, not a blank to fill in."""
        user, thread = butler
        result = await run_turn(
            session, user, thread, text="what did you find last night",
            today=today, model_factory=scripted_factory(("read_briefing", {})),
        )
        assert "read_briefing" in result.tools_used
        assert any("none run" in row[1] for row in result.evidence)

    async def test_reading_it_changes_nothing(self):
        assert not REGISTRY.get("read_briefing").is_write
