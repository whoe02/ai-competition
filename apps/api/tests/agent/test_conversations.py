"""Golden conversations: fixed question, asserted tools, asserted evidence.

No network and no API key. What is being pinned is the graph's behaviour —
which tools ran, what they returned, and what reached the approval boundary —
not the model's prose.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from kira.agent import prompt
from kira.agent.llm import OfflineChatModel, _amount_sen, route_for
from kira.agent.run import run_turn
from kira.agent.tools import REGISTRY
from kira.db.models import ROLE_KIRA, ROLE_USER, TXN_CONFIRMED, TXN_DRAFT, Transaction
from kira.money import Money
from kira.services import butler_thread
from kira.services.butler_thread import MessageView
from kira.services.day_plan import known_kinds
from tests.agent.conftest import offline_factory
from tests.conftest import serving


async def ask(session, butler, today, text, **kwargs):
    user, thread = butler
    return await run_turn(
        session,
        user,
        thread,
        text=text,
        today=today,
        model_factory=offline_factory,
        **kwargs,
    )


# Kept out of the model rather than on it: the model is a pydantic object, and a
# list field would be validated into a copy the caller never sees again.
COMPOSED: list[str] = []


class ComposeSpy(OfflineChatModel):
    """The offline model, keeping the system prompt of the composing turn.

    "No tools bound" is exactly that turn: compose binds none, which is what
    lets it stream, and is also why a tool's own description never reaches it.
    """

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if not self.bound_tools:
            COMPOSED.append(
                "\n\n".join(
                    message.content
                    for message in messages
                    if isinstance(message, SystemMessage)
                )
            )
        return super()._generate(messages, stop, run_manager, **kwargs)


def compose_spy_factory(**kwargs):
    return ComposeSpy(attachment=kwargs.get("attachment"), history=kwargs.get("history", ""))


async def compose_prompt(session, butler, today, text) -> str:
    """Everything the turn that writes the answer was told, for one question."""
    COMPOSED.clear()
    user, thread = butler
    await run_turn(
        session, user, thread, text=text, today=today, model_factory=compose_spy_factory
    )
    assert COMPOSED, "compose never ran"
    return COMPOSED[-1]


async def say(session, butler, today, text, **kwargs):
    """One turn with the conversation on the thread, the way the API runs it.

    `load_context` reads the history out of `butler_messages` and drops the
    last row as the one being answered, so `ask` on its own is a turn with no
    history at all. That is the right default for every test above; it is
    exactly the wrong one for a follow-up, which has no meaning without it.
    """
    user, thread = butler
    await butler_thread.append(session, user, thread, role=ROLE_USER, content=text)
    result = await ask(session, butler, today, text, **kwargs)
    await butler_thread.append(session, user, thread, role=ROLE_KIRA, content=result.answer)
    return result


def tool_call(text: str, tool: str) -> dict:
    """The arguments one sentence reaches a tool with, before anything runs.

    Bound to the real registry rather than to a list of names, so this is the
    same call the graph would execute -- what the answer says about it is a
    separate question, asked separately below.
    """
    reply = OfflineChatModel().bind_tools(REGISTRY.schemas()).invoke([HumanMessage(content=text)])
    calls = {call["name"]: call["args"] for call in reply.tool_calls}
    assert tool in calls, f"{text!r} reached {sorted(calls)} rather than {tool}"
    return calls[tool]


def labels(result) -> list[str]:
    return [label for label, _ in result.evidence]


class TestAffordability:
    async def test_it_checks_the_amount_against_todays_room(self, session, butler, today):
        result = await ask(session, butler, today, "Can I afford RM60 dinner tonight?")
        assert result.tools_used == ["calculate_safe_to_spend"]
        assert dict(result.evidence)["Safe to spend today"] == "RM52.97"
        assert dict(result.evidence)["Dinner"] == "RM60.00"
        assert "Over by" in labels(result)

    async def test_a_smaller_amount_fits(self, session, butler, today):
        result = await ask(session, butler, today, "Can I afford RM20 lunch?")
        assert dict(result.evidence)["Left after it"] == "RM32.97"

    async def test_the_answer_carries_the_number(self, session, butler, today):
        result = await ask(session, butler, today, "Can I afford RM20 lunch?")
        assert "RM20" in result.answer
        assert result.answer.strip()


class TestWhyItMoved:
    async def test_it_reads_the_snapshot_and_the_ledger(self, session, butler, today):
        result = await ask(session, butler, today, "Why did safe-to-spend drop?")
        assert result.tools_used == ["get_financial_snapshot", "list_activity"]
        assert dict(result.evidence)["Balance"] == "RM4,180.40"
        assert dict(result.evidence)["Reserved for bills"] == "RM2,003.00"
        assert dict(result.evidence)["Buffer held back"] == "RM800.00"


class TestGoals:
    async def test_it_reads_the_goals(self, session, butler, today):
        result = await ask(session, butler, today, "How is my wedding goal doing?")
        assert result.tools_used == ["list_goals"]
        assert "Wedding" in labels(result)
        assert "Wedding" in result.answer


class TestBills:
    async def test_it_reads_the_commitments(self, session, butler, today):
        result = await ask(session, butler, today, "What bills are due?")
        assert result.tools_used == ["list_commitments"]
        assert "Rent · protected" in labels(result)


class TestEvidenceIsRecordedNotClaimed:
    async def test_every_row_came_from_a_tool_that_ran(self, session, butler, today):
        result = await ask(session, butler, today, "Where do I stand today?")
        assert result.tools_used
        assert result.evidence
        for label, value in result.evidence:
            assert isinstance(label, str) and label
            assert isinstance(value, str) and value

    async def test_the_numbers_track_the_ledger(self, session, butler, today):
        """Confirm a transaction and the evidence moves with it, not with the prose."""
        user, _ = butler
        before = await ask(session, butler, today, "Where do I stand today?")
        session.add(
            Transaction(
                user_id=user.id,
                merchant="Zus Coffee",
                amount=Money(1200),
                category="food",
                occurred_on=today,
                status=TXN_CONFIRMED,
                source="manual",
            )
        )
        await session.flush()
        after = await ask(session, butler, today, "Where do I stand today?")
        assert dict(before.evidence)["Safe to spend today"] == "RM52.97"
        assert dict(after.evidence)["Safe to spend today"] == "RM40.42"

    async def test_a_draft_moves_nothing(self, session, butler, today):
        user, _ = butler
        session.add(
            Transaction(
                user_id=user.id,
                merchant="Big draft",
                amount=Money(50000),
                category="food",
                occurred_on=today,
                status=TXN_DRAFT,
                source="manual",
            )
        )
        await session.flush()
        result = await ask(session, butler, today, "Where do I stand today?")
        assert dict(result.evidence)["Safe to spend today"] == "RM52.97"


class TestAttachments:
    """Receipt and voice capture reach the Butler as an attachment on the turn."""

    RECEIPT = {
        "kind": "receipt",
        "merchant": "Nasi Kandar Pelita",
        "amount_sen": 1890,
        "occurred_on": "2026-09-03",
        "category": "food",
        "confidence": 94,
        "note": "Line item total matched.",
        "fields": [
            {"label": "Merchant", "value": "Nasi Kandar Pelita", "confidence": 94},
            {"label": "Total", "value": "RM18.90", "confidence": 94},
        ],
    }

    async def test_it_reads_what_was_scanned(self, session, butler, today):
        result = await ask(
            session,
            butler,
            today,
            "What does this receipt do to my day?",
            attachment=self.RECEIPT,
        )
        assert "inspect_attachment" in result.tools_used
        assert "calculate_safe_to_spend" in result.tools_used
        assert dict(result.evidence)["Merchant"] == "Nasi Kandar Pelita · 94% sure"
        assert dict(result.evidence)["On the ledger"] == "not until you confirm it"

    async def test_the_amount_read_is_the_amount_tested(self, session, butler, today):
        result = await ask(
            session,
            butler,
            today,
            "What does this receipt do to my day?",
            attachment=self.RECEIPT,
        )
        assert dict(result.evidence)["Left after it"] == "RM34.07"

    async def test_without_an_attachment_it_says_so(self, session, butler, today):
        result = await ask(session, butler, today, "What did that receipt say?")
        assert dict(result.evidence)["Attachment"] == "none on this message"


class TestLoggingSpending:
    """A sentence about money already spent is a proposal to log it.

    People do not speak in fields. "Grabbed lunch at the mamak, twelve fifty" has
    to reach the same approval card as a structured request, and reach it without
    touching the ledger on the way.
    """

    async def test_it_proposes_the_transaction_it_heard(self, session, butler, today):
        result = await ask(session, butler, today, "I spent RM12.50 at the mamak on lunch")
        assert result.approval is not None
        assert result.approval["tool"] == "add_transaction"
        assert result.approval["args"]["amount_sen"] == 1250

    async def test_it_hears_an_amount_that_was_spoken_rather_than_typed(
        self, session, butler, today
    ):
        result = await ask(session, butler, today, "Grabbed lunch at the mamak, twelve fifty")
        assert result.approval["args"]["amount_sen"] == 1250

    async def test_it_reads_the_merchant_out_of_the_sentence(self, session, butler, today):
        result = await ask(session, butler, today, "I paid RM45 at Village Grocer")
        assert result.approval["args"]["merchant"] == "Village Grocer"

    async def test_it_infers_the_category_rather_than_hardcoding_one(
        self, session, butler, today
    ):
        result = await ask(session, butler, today, "Topped up petrol, RM60")
        assert result.approval["args"]["category"] == "transport"

    async def test_it_dates_it_today_unless_told_otherwise(self, session, butler, today):
        result = await ask(session, butler, today, "Bought roti canai for RM4")
        assert result.approval["args"]["occurred_on"] == today.isoformat()

    async def test_yesterday_means_yesterday(self, session, butler, today):
        result = await ask(session, butler, today, "I spent RM30 on groceries yesterday")
        expected = today.fromordinal(today.toordinal() - 1)
        assert result.approval["args"]["occurred_on"] == expected.isoformat()

    async def test_without_an_amount_it_asks_instead_of_inventing_one(
        self, session, butler, today
    ):
        result = await ask(session, butler, today, "I bought lunch at the mamak")
        assert result.approval is None
        assert "how much" in result.answer.lower()

    async def test_nothing_reaches_the_ledger_before_the_user_approves(
        self, session, butler, today
    ):
        from sqlalchemy import func, select

        async def rows() -> int:
            return (
                await session.execute(select(func.count()).select_from(Transaction))
            ).scalar_one()

        before = await rows()
        result = await ask(session, butler, today, "I spent RM12.50 at the mamak on lunch")
        assert result.approval is not None
        assert await rows() == before

    async def test_the_summary_says_what_will_be_added(self, session, butler, today):
        result = await ask(session, butler, today, "I spent RM12.50 at the mamak on lunch")
        assert "RM12.50" in result.approval["summary"]


class TestComposingWhenNoProposalWasMade:
    """The offline model also composes as a safety net for the online one.

    When the vendor returns nothing, `compose` falls back to the offline model
    for the prose alone — with no tool having run. Its answer must describe what
    actually happened, not what the route would have done.
    """

    async def test_it_does_not_claim_a_draft_that_was_never_proposed(self):
        from langchain_core.messages import HumanMessage

        from kira.agent.llm import OfflineChatModel

        reply = await OfflineChatModel().ainvoke(
            [HumanMessage("grabbed lunch at the mamak, twelve fifty")]
        )
        assert "draft" not in str(reply.content).lower()

    async def test_it_still_says_so_once_the_draft_is_real(self, session, butler, today):
        from sqlalchemy import select

        from kira.agent.run import resume_approval
        from kira.db.models import ButlerApproval

        user, thread = butler
        first = await ask(session, butler, today, "I spent RM12.50 at the mamak on lunch")
        assert first.approval is not None
        approval = (await session.execute(select(ButlerApproval).limit(1))).scalar_one()

        result = await resume_approval(
            session,
            user,
            thread,
            graph_thread=approval.graph_thread_id,
            decision={"action": "accept"},
            today=today,
            model_factory=offline_factory,
        )
        assert "draft" in result.answer.lower()


class TestWhereToEat:
    """The day planner, reached by asking rather than by tapping.

    The offline model is the one the demo runs on -- the container carries no
    API key -- so without a route here the Butler answers "where can I eat"
    with today's balance and never touches the planner at all.
    """

    async def test_it_reaches_the_day_planner(self, session, butler, today):
        result = await ask(session, butler, today, "Where can I eat nearby today?")
        assert result.tools_used == ["start_day_planning"]

    async def test_a_question_naming_an_amount_still_goes_to_affordability(
        self, session, butler, today
    ):
        # "Can I afford RM60 dinner" is a question about money, not a request
        # for somewhere to go, and must not be answered with a list of shops.
        result = await ask(session, butler, today, "Can I afford RM60 dinner tonight?")
        assert result.tools_used == ["calculate_safe_to_spend"]

    async def test_the_evidence_states_the_room_it_judged_against(
        self, session, butler, today
    ):
        result = await ask(session, butler, today, "Where should I eat?")
        assert dict(result.evidence)["Safe to spend today"] == "RM52.97"

    async def test_the_answer_names_a_place_and_a_price(self, session, butler, today):
        result = await ask(session, butler, today, "I'm hungry, where should I go?")
        assert "RM" in result.answer
        assert "estimate" in result.answer.lower()


class TestWhatTheOfflinePlannerDoesWithTheRequest:
    """"Somewhere halal under RM15" used to reach the planner as no arguments.

    The list came back unfiltered and the answer read as though the whole
    sentence had been understood, which on halal is a wrong answer rather than
    a wide one. These run against the fixed world rather than the shipped KL
    set: two of its five places are not halal, which is what makes a dropped
    filter something a test can see instead of something to take on trust.
    """

    async def test_a_halal_request_leaves_the_others_out(
        self, session, butler, today, place_world
    ):
        result = await ask(session, butler, today, "Where can I eat somewhere halal nearby?")
        assert place_world.near_non_halal.name not in result.answer
        assert place_world.far_non_halal.name not in result.answer

    async def test_the_same_search_without_the_word_returns_them(
        self, session, butler, today, place_world
    ):
        # The other half of the pair. Without it, a filter that had quietly
        # stopped working would still pass the test above.
        result = await ask(session, butler, today, "Where can I eat nearby?")
        assert place_world.near_non_halal.name in result.answer

    async def test_a_price_in_the_request_becomes_the_ceiling(
        self, session, butler, today, place_world
    ):
        # RM10 is a hundred times 10, and the gap between the two survivors is
        # RM3.50 -- so a ceiling read in ringgit, or not read at all, changes
        # which names come back.
        result = await ask(session, butler, today, "Where can I eat for under RM10?")
        assert place_world.cheap.name in result.answer
        assert place_world.mid.name not in result.answer

    async def test_it_states_what_it_read_and_that_it_read_nothing_else(
        self, session, butler, today, place_world
    ):
        result = await ask(session, butler, today, "Where can I eat somewhere halal under RM15?")
        assert "I read halal only and a ceiling of RM15, and nothing else" in result.answer
        assert "any other condition in it went unread" in result.answer

    async def test_a_request_it_cannot_read_is_answered_as_one_it_could_not_read(
        self, session, butler, today, place_world
    ):
        result = await ask(session, butler, today, "Where can I eat somewhere quiet with a view?")
        assert "I found none of them in what you asked" in result.answer
        assert "nothing in it narrowed this" in result.answer

    async def test_a_ceiling_it_was_given_is_not_narrated_as_todays_room(
        self, session, butler, today, place_world
    ):
        # RM1 admits nothing, and the reason it admits nothing is the user's own
        # ceiling. Today has RM52.97, and saying otherwise would be a claim
        # about their money that no figure here supports.
        result = await ask(session, butler, today, "Where can I eat for under RM1?")
        assert "the ceiling I read out of what you asked" in result.answer
        assert "today itself has room for RM52.97" in result.answer

    async def test_it_names_a_place_it_actually_found(
        self, session, butler, today, place_world
    ):
        # Kopi Kaki is RM9 and 50 m away, so walking is free and the whole
        # outing is the meal. A price range with no name attached is the answer
        # this is here to rule out.
        result = await ask(session, butler, today, "Where can I eat somewhere halal nearby?")
        assert f"{place_world.cheap.name} — RM9 " in result.answer


class TestAskingTheButlerForOneKindOfFood:
    """"I want noodles" was unanswerable: nothing in the planner's arguments
    carried what kind of food it was for, so the reply was the same
    cheapest-first list with that half of the request dropped out of it."""

    async def test_a_kind_in_the_sentence_narrows_the_list(
        self, session, butler, today, place_world
    ):
        result = await ask(session, butler, today, "Where can I eat noodles nearby?")
        assert place_world.noodles.name in result.answer
        # Kopi Kaki is half the price and would lead any unfiltered list.
        assert place_world.cheap.name not in result.answer

    async def test_it_says_it_read_the_kind(self, session, butler, today, place_world):
        result = await ask(session, butler, today, "Where can I eat noodles nearby?")
        assert "I read noodles to eat, and nothing else" in result.answer

    async def test_a_kind_that_is_not_around_here_is_not_blamed_on_the_ceiling(
        self, session, butler, today, place_world
    ):
        # There is no Korean food in the fixed world, and today has RM52.97.
        # Sending the user at the ceiling here would aim them at a slider that
        # cannot reach what is actually in the way.
        result = await ask(session, butler, today, "Where can I eat korean food nearby?")
        assert "No korean within range of you" in result.answer
        assert "no ceiling is what is in the way" in result.answer
        # And it says what is there instead, which is the whole of the answer:
        # "no Korean" on its own sends them back to a screen they have read.
        assert "What is around you: cafe from RM9" in result.answer

    async def test_a_ceiling_that_empties_one_kind_does_not_claim_it_emptied_them_all(
        self, session, butler, today, place_world
    ):
        # Omakase Empat is RM50 and the only Japanese place; Kopi Kaki is RM9.
        # "There are places nearby, but none under RM15" would be false, and
        # the price that kind starts at is what says how far off RM15 is.
        result = await ask(session, butler, today, "Where can I eat japanese under RM15?")
        assert "The japanese places within range start at RM50, over RM15" in result.answer
        assert "RM15 reaches cafe from RM9" in result.answer

    async def test_a_word_that_is_no_kind_of_food_reads_as_a_kind_of_nothing(
        self, session, butler, today, place_world
    ):
        # "Restaurant" is a kind in the curated data and not one in a sentence,
        # and "hawker" is not a kind anywhere. Neither may narrow the list.
        for sentence in ("Where can I eat, any restaurant?", "Where can I eat hawker food?"):
            result = await ask(session, butler, today, sentence)
            assert place_world.cheap.name in result.answer, sentence

    async def test_the_ceiling_and_the_kind_are_read_out_of_one_sentence(
        self, session, butler, today, place_world
    ):
        result = await ask(session, butler, today, "Where can I eat halal noodles under RM20?")
        assert "I read halal only, a ceiling of RM20 and noodles to eat" in result.answer
        assert place_world.noodles.name in result.answer

    async def test_the_count_of_the_rest_is_the_search_not_the_message(
        self, session, butler, today, place_world
    ):
        # The planner hands over the cheapest dozen of what it found. Thirteen
        # places are under the ceiling here, so three named and "nine more"
        # would be a figure about the size of the message rather than about the
        # neighbourhood — and the user has no way to see which it was.
        with serving(places=place_world.crowd):
            result = await ask(session, butler, today, "Where can I eat under RM25?")
        assert "10 more came in under RM25 as well" in result.answer


class TestTheOfflineAnswerHasNoMenuInItsHead:
    """The planner now hands over the places a kind filter turned away.

    Online that is the point: a model can know that McDonald's, tagged burgers,
    fries chicken all day, and say so. Offline there is no model -- there is a
    handful of regexes, which know the word "noodles" and nothing whatever
    about what any shop cooks. So the near misses arrive and go unspoken. Not
    as a rule being obeyed: there is simply nothing here that could honestly
    say anything about them, and a guess made off a name would be a menu
    invented out of nothing.
    """

    def _unmatched(self, world):
        return (
            world.cheap,
            world.mid,
            world.near_non_halal,
            world.pricey,
            world.far_non_halal,
            world.second_cafe,
        )

    async def test_it_names_the_place_that_matched_and_none_of_the_rest(
        self, session, butler, today, place_world
    ):
        result = await ask(session, butler, today, "Where can I eat noodles nearby?")
        assert place_world.noodles.name in result.answer
        for place in self._unmatched(place_world):
            assert place.name not in result.answer, place.name

    async def test_a_kind_nothing_matched_is_answered_without_naming_a_shop(
        self, session, butler, today, place_world
    ):
        # There is no Korean food in the fixed world, and four places the
        # search turned away are sitting in the payload. Offline the answer is
        # what kinds of food are around, priced -- never one of those four
        # renamed as somewhere that might do Korean after all.
        result = await ask(session, butler, today, "Where can I eat korean food nearby?")
        assert "No korean within range of you" in result.answer
        assert "What is around you: cafe from RM9" in result.answer
        for place in self._unmatched(place_world):
            assert place.name not in result.answer, place.name
        assert place_world.noodles.name not in result.answer

    async def test_the_panel_still_records_them_and_says_what_they_are(
        self, session, butler, today, place_world
    ):
        # Unspoken is not unrecorded. The tool returned them and the evidence
        # says so, at the kinds the data gives them -- which is the same panel
        # the online model's suggestion would have to stand next to.
        result = await ask(session, butler, today, "Where can I eat noodles nearby?")
        also = [value for label, value in result.evidence if label == "Also nearby"]
        assert f"{place_world.mid.name} · Mamak · RM12.50" in also
        assert not any("Noodles" in value for value in also)


class TestTheOfflineAnswerSaysWhichMatchesWereGuessed:
    """The widened filter reaches the offline demo for free, and it has to.

    ``also_serves`` is baked into the shipped file, so a search offline matches
    the same beliefs an online one does and the list is the same width. What
    offline cannot do is stand behind them: there is no model here, only a
    handful of regexes, and "it does chicken" is a menu nothing in this process
    has read. So the reason travels with the place and the sentence says only
    that -- why the shop is on the list, never what it sells.
    """

    async def test_it_says_a_named_place_is_here_on_a_belief(
        self, session, butler, today, place_world
    ):
        with serving(places=place_world.believed):
            result = await ask(session, butler, today, "Where can I eat chicken nearby?")
        # The tagged pair lead on price and the burger shop is named after them,
        # so the sentence has to reach past the first name to qualify it.
        assert place_world.tagged_chicken.name in result.answer
        assert (
            f"{place_world.believed_chicken.name} is on this list on a belief that it "
            "also does chicken, not on a tag saying so." in result.answer
        )

    async def test_it_says_it_of_the_place_it_led_with(
        self, session, butler, today, place_world
    ):
        with serving(places=(place_world.believed_chicken, place_world.no_chicken)):
            result = await ask(session, butler, today, "Where can I eat chicken nearby?")
        assert f"{place_world.believed_chicken.name} — RM16 " in result.answer
        assert "is on this list on a belief that it also does chicken" in result.answer

    async def test_it_claims_nothing_about_what_the_place_serves(
        self, session, butler, today, place_world
    ):
        # The one sentence this composer may not write. It has read no menu, and
        # "also does chicken" said flatly is a menu -- said of the shop rather
        # than of the record, and unbacked by anything in this process.
        with serving(places=(place_world.believed_chicken, place_world.no_chicken)):
            result = await ask(session, butler, today, "Where can I eat chicken nearby?")
        name = place_world.believed_chicken.name
        assert f"{name} does chicken" not in result.answer
        assert f"{name} serves chicken" not in result.answer
        assert f"{name} also does chicken" not in result.answer

    async def test_a_tagged_list_is_qualified_by_nothing(
        self, session, butler, today, place_world
    ):
        # Nothing believed among the names, so nothing to say. A qualification
        # on a list of tags would be an apology for data that is not a guess.
        with serving(places=(place_world.tagged_chicken, place_world.both_ways)):
            result = await ask(session, butler, today, "Where can I eat chicken nearby?")
        assert place_world.tagged_chicken.name in result.answer
        assert "on a belief" not in result.answer

    async def test_a_list_nobody_narrowed_is_qualified_by_nothing_either(
        self, session, butler, today, place_world
    ):
        with serving(places=place_world.believed):
            result = await ask(session, butler, today, "Where can I eat nearby?")
        assert "on a belief" not in result.answer


class TestTheTurnThatWritesTheAnswerIsToldTheRules:
    """Where the near-miss rules have to be, rather than where they were.

    They were written into ``start_day_planning``'s description, and a tool
    description is bound to the reasoning turns and to nothing else. Compose
    binds no tools — that is what lets it stream — so the turn whose sentence
    the user actually reads was handed four places the kind filter turned away,
    as "Also nearby: Kopi Kaki · Cafe · RM9.00", with nothing above it saying
    they had not matched and nothing forbidding a fifth name that came back
    from no search at all. That is the shape of the failure this project has
    already shipped once, so both rules are now stated where this turn reads
    them.
    """

    async def test_compose_is_handed_the_near_misses(
        self, session, butler, today, place_world
    ):
        # The half that makes the other half matter: these names really do
        # reach the turn that writes the prose, in the payload and in the rows.
        seen = await compose_prompt(session, butler, today, "Where can I eat noodles nearby?")
        assert f"Also nearby: {place_world.cheap.name} · Cafe · RM9.00" in seen

    async def test_it_is_forbidden_to_name_anything_else(
        self, session, butler, today, place_world
    ):
        seen = await compose_prompt(session, butler, today, "Where can I eat noodles nearby?")
        assert "Name only what the tools above actually returned" in seen
        assert "A name\nin none of them is one you invented" in seen

    async def test_it_is_told_what_an_also_nearby_row_is(
        self, session, butler, today, place_world
    ):
        seen = await compose_prompt(session, butler, today, "Where can I eat noodles nearby?")
        assert 'A place given as "also nearby"' in seen
        assert "is one the search turned away" in seen
        # Suggestion, never assertion: the menu claim is the model's and the
        # price is the row's.
        assert "yours to suggest" in seen
        assert "quote no price but the one on its row" in seen

    async def test_the_rule_is_there_on_a_turn_with_no_places_in_it(
        self, session, butler, today, place_world
    ):
        # A merchant and a bill are names too. The instruction is one string on
        # every composing turn rather than something the planner switches on.
        seen = await compose_prompt(session, butler, today, "What bills are due?")
        assert "Name only what the tools above actually returned" in seen


class TestTheAnswerChoosesInsteadOfEnumerating:
    """"You have RM52.97 available today, and all five halal options — from
    RM13.00 to RM14.00 — fit comfortably within that limit" is a true sentence
    that answers nothing. It named none of the five. The user asked where to
    eat and was handed a description of the filter, so what these pin is the
    answer being a choice: one place, named, priced, and with the reason it was
    the one that was picked."""

    def test_a_craving_reaches_the_planner_carrying_the_kind(self):
        args = tool_call("I feel like noodles", "start_day_planning")
        # In the curated set's own spelling, because a word it does not carry
        # matches nothing and the search would come back empty behind it.
        assert args["kind"] == "Noodles"
        assert args["kind"] in known_kinds()

    async def test_that_craving_runs_the_planner_and_names_what_it_found(
        self, session, butler, today, place_world
    ):
        result = await ask(session, butler, today, "I feel like noodles")
        assert result.tools_used == ["start_day_planning"]
        assert f"{place_world.noodles.name} — RM18" in result.answer

    async def test_it_names_one_place_and_says_why_that_one(
        self, session, butler, today, place_world
    ):
        result = await ask(session, butler, today, "Where can I eat somewhere halal nearby?")
        assert f"{place_world.cheap.name} — RM9 for the whole outing" in result.answer
        # The reason, which is the half a list leaves out. Offline the only
        # thing that can be weighed is the price order, and it says so.
        assert "the cheapest of the 5 that came in under RM52.97" in result.answer
        assert "17% of today's room" in result.answer

    async def test_a_ceiling_that_rules_out_whole_kinds_says_which_and_from_what(
        self, session, butler, today, place_world
    ):
        # RM15 reaches the cafe and the mamak. The chinese, noodles, western and
        # japanese places all start above it, and the cheapest of those is RM16
        # -- which is the figure that says how close the ceiling came.
        result = await ask(session, butler, today, "Where can I eat under RM15?")
        assert f"{place_world.cheap.name} — RM9" in result.answer
        assert (
            "RM15 will not reach 4 other kinds of food around you, which start at RM16"
            in result.answer
        )

    async def test_a_ceiling_nothing_reaches_names_the_nearest_place_and_its_price(
        self, session, butler, today, place_world
    ):
        # RM5 buys nothing in the fixed world. "Nothing found" leaves the user
        # with no move to make, and the search already knows the cheapest thing
        # around is Kopi Kaki at RM9 -- so the answer is a name and a price, and
        # in the same breath how far over the ceiling it is.
        result = await ask(session, butler, today, "Where can I eat for under RM5?")
        assert "There are places nearby, but none under RM5." in result.answer
        assert (
            f"The closest I can get you is {place_world.cheap.name} at RM9, RM4 over RM5."
            in result.answer
        )
        # Named as over rather than offered as though it fitted, and the ceiling
        # it could not meet is still not narrated as their day.
        assert "today itself has room for RM52.97" in result.answer
        # The panel backs the name the sentence used, and labels it as what it
        # is: nothing here may read as a place that came in under the ceiling.
        rows = dict(result.evidence)
        assert rows["Closest above the ceiling"] == f"{place_world.cheap.name} at RM9.00"
        assert rows["Over the ceiling by"] == "RM4.00"

    async def test_the_kinds_the_money_does_reach_stand_beside_the_nearest_place(
        self, session, butler, today, place_world
    ):
        # A kind filter is what empties this list, not the money: RM20 reaches
        # the cafe, the mamak and the chinese place, and no japanese under RM50.
        # Both facts are worth saying, and they are different facts.
        result = await ask(session, butler, today, "Where can I eat japanese under RM20?")
        assert (
            f"The closest I can get you is {place_world.pricey.name} at RM50, RM30 over RM20."
            in result.answer
        )
        assert "RM20 reaches cafe from RM9, mamak from RM12.50 and chinese from RM16." in (
            result.answer
        )


class TestReadingAnAmountOutOfASentence:
    """The offline parser against the way this app writes ringgit at the user.

    ``Money.ringgit_str`` groups thousands and the house style in
    ``kira.agent.prompt`` says RM1,234.56, so a user quoting a figure back at
    the Butler is quoting one with a group separator in it. Reading that comma
    as a decimal point divides the amount by a thousand, which offline made
    "can I afford RM1,500" a question about RM1.50 — answered yes, in earnest.
    """

    @pytest.mark.parametrize(
        ("text", "sen"),
        [
            ("can I afford RM15?", 1500),
            ("can I afford RM15.50?", 1550),
            ("can I afford RM 15?", 1500),
            ("can I afford 15 ringgit?", 1500),
            # The group separator, which is the one that was wrong.
            ("can I afford RM1,500?", 150_000),
            ("can I afford RM1,200.00?", 120_000),
            ("can I afford RM1,234,567?", 123_456_700),
            # And the decimal comma it has to stay told apart from.
            ("can I afford RM15,50?", 1550),
            ("can I afford RM1,5?", 150),
        ],
    )
    def test_what_a_written_amount_is_worth(self, text, sen):
        assert _amount_sen(text) == sen

    async def test_a_grouped_ceiling_is_not_divided_by_a_thousand(
        self, session, butler, today, place_world
    ):
        # Every place in the fixed world is under RM1,500 and none is under
        # RM1.50, so which of the two the parser read is the difference between
        # a full list and an empty one.
        result = await ask(session, butler, today, "Where can I eat under RM1,500?")
        assert "a ceiling of RM1,500" in result.answer
        assert place_world.cheap.name in result.answer


class TestHowPeopleActuallyAskForFood:
    """The offline model is what the demo runs on, so the route has to catch
    the phrasings a person uses rather than the one the tests were written in.
    """

    async def test_a_craving_with_words_in_the_way_still_reaches_the_planner(
        self, session, butler, today
    ):
        # "i want eat fried chicken" puts two words between the wanting and the
        # food, and named a dish rather than the data's heading for it. It was
        # answered with today's balance.
        result = await ask(session, butler, today, "i want eat fried chicken")
        assert result.tools_used == ["start_day_planning"]

    async def test_halal_alone_is_a_question_about_food(self, session, butler, today):
        result = await ask(session, butler, today, "somewhere halal under RM15")
        assert result.tools_used == ["start_day_planning"]

    async def test_wanting_something_that_is_not_food_is_left_alone(
        self, session, butler, today
    ):
        # The craving trigger must land on a real kind word, or "I want" turns
        # every sentence into a request for lunch.
        result = await ask(session, butler, today, "I want to save more for the wedding")
        assert "start_day_planning" not in result.tools_used


def rendered(*turns: str) -> str:
    """A conversation as the system prompt renders it, user turns only.

    Built through `prompt.history_block` rather than typed out, so the one test
    below that reads the classifier directly is reading the real format and not
    a copy of it that could drift.
    """
    return prompt.history_block(
        tuple(
            MessageView(
                id=uuid.uuid4(),
                role=ROLE_USER,
                content=turn,
                evidence=(),
                attachment=None,
                created_at=datetime.now(UTC),
            )
            for turn in turns
        )
    )


class TestAFollowUpThatNamesOnlyAKindOfFood:
    """"I feel like japanese" reached the planner and "what about japanese
    instead" reached today's balance, which is the same request twice with the
    second one answered as small talk.

    A bare kind word carries no verb, no place and no money, so nothing in the
    sentence itself says it is about food. What says so is the turn before it.
    These pin both halves of that: the follow-up read as food when the
    conversation was already about food, and the same words left alone when it
    was not.
    """

    def test_the_classifier_reads_it_as_places_and_carries_the_kind(self):
        text = "what about japanese instead"
        cold = route_for(text)
        warm = route_for(text, None, rendered("Where can I eat nearby?"))
        assert cold.name == "snapshot"
        assert warm.name == "places"
        # In the curated set's own spelling, because a word the data does not
        # carry matches nothing and the search comes back empty behind it.
        assert (
            warm.arguments(text, None, date(2026, 9, 3))["start_day_planning"]["kind"]
            == "Japanese"
        )

    async def test_it_searches_for_the_food_it_named(
        self, session, butler, today, place_world
    ):
        await say(session, butler, today, "Where can I eat nearby?")
        result = await say(session, butler, today, "what about japanese instead")
        assert result.tools_used == ["start_day_planning"]
        # Omakase Empat is the only Japanese place in the fixed world, and at
        # RM50 it is the one an unfiltered list would never lead with.
        assert f"{place_world.pricey.name} — RM50" in result.answer
        assert "I read japanese to eat, and nothing else" in result.answer

    async def test_a_kind_with_nothing_behind_it_is_still_answered_as_food(
        self, session, butler, today, place_world
    ):
        await say(session, butler, today, "Where can I eat nearby?")
        result = await say(session, butler, today, "korean then")
        assert result.tools_used == ["start_day_planning"]
        # There is no Korean food in the fixed world, and saying so is a real
        # answer. Today's balance is not.
        assert "No korean within range of you" in result.answer

    @pytest.mark.parametrize("text", ["what about japanese instead", "korean then"])
    async def test_the_same_words_cold_are_not_about_food(
        self, session, butler, today, place_world, text
    ):
        result = await say(session, butler, today, text)
        assert "start_day_planning" not in result.tools_used

    async def test_a_turn_about_something_else_ends_the_run(
        self, session, butler, today, place_world
    ):
        # The context is the turn before, not a mood the thread is stuck in.
        await say(session, butler, today, "Where can I eat nearby?")
        await say(session, butler, today, "What bills are due?")
        result = await say(session, butler, today, "korean then")
        assert "start_day_planning" not in result.tools_used

    async def test_a_run_of_follow_ups_keeps_its_footing(
        self, session, butler, today, place_world
    ):
        # Only the first of these three says in words that it is about food, so
        # by the third the context has to have been carried rather than reread.
        await say(session, butler, today, "I feel like japanese")
        await say(session, butler, today, "or korean")
        result = await say(session, butler, today, "noodles then")
        assert result.tools_used == ["start_day_planning"]
        assert f"{place_world.noodles.name} — RM18" in result.answer

    async def test_a_kind_word_inside_a_sentence_about_something_else_is_not_food(
        self, session, butler, today, place_world
    ):
        # The sentence this rule exists to keep its hands off. "Japanese" is in
        # it, and it is about a holiday: read as a craving it would reach the
        # planner, and places is tried before goals, so it would get there.
        cold = await say(session, butler, today, "I want to save for a japanese trip")
        assert "start_day_planning" not in cold.tools_used
        await say(session, butler, today, "Where can I eat nearby?")
        warm = await say(session, butler, today, "I want to save for a japanese trip")
        assert "start_day_planning" not in warm.tools_used
