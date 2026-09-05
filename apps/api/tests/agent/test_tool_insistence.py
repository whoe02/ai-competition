"""The planner runs because the turn is about places, not because a model asked.

Measured against a live Qwen on a fresh thread, "i want eat fried chicken" came
back as a fluent answer with no tool call and no evidence behind it; pushed to
answer anyway, it named a restaurant that is in none of this app's data. The
compose guard turns that into an honest refusal, which is useless. What these
pin is the turn arriving at compose with real rows either way, and the four
things that must not move while it does: a turn about money stays about money,
a tool the model called is not called twice, a write is never run without a
card, and the offline demo behaves exactly as it did.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy import select

from kira.agent.llm import OfflineChatModel
from kira.agent.nodes import insist as insist_node
from kira.agent.nodes.compose import NOTHING_RAN
from kira.agent.run import run_turn
from kira.agent.tools import REGISTRY
from kira.db.models import SOURCE_PLAN, ButlerApproval, Transaction
from tests.agent.conftest import (
    ScriptedModel,
    declining_factory,
    offline_factory,
    scripted_factory,
)

# What the online model actually wrote when it had called nothing. Kept
# verbatim: a test written against invented prose would not be about this bug.
INVENTED = "Try Sushi Tei (Mid Valley Megamall) — about RM42 for two."


async def ask(session, butler, today, text, factory, **kwargs):
    user, thread = butler
    return await run_turn(
        session, user, thread, text=text, today=today, model_factory=factory, **kwargs
    )


class TestAModelThatCallsNothing:
    """The failure this exists for, driven by a model that declines every time."""

    async def test_the_turn_still_ends_with_the_planners_evidence(
        self, session, butler, today, place_world
    ):
        result = await ask(
            session, butler, today, "i want eat fried chicken", declining_factory(INVENTED)
        )
        assert result.tools_used == ["start_day_planning"]
        assert dict(result.evidence)["Safe to spend today"] == "RM52.97"

    async def test_the_answer_is_no_longer_the_refusal(
        self, session, butler, today, place_world
    ):
        result = await ask(
            session, butler, today, "Where can I eat nearby?", declining_factory(INVENTED)
        )
        assert result.answer != NOTHING_RAN
        assert place_world.cheap.name in result.answer

    async def test_the_prose_it_wrote_with_no_evidence_does_not_survive(
        self, session, butler, today, place_world
    ):
        result = await ask(
            session, butler, today, "Where can I eat nearby?", declining_factory(INVENTED)
        )
        assert "Sushi Tei" not in result.answer

    async def test_the_sentence_still_sets_the_filters(
        self, session, butler, today, place_world
    ):
        # The classifier's arguments, not the tool's defaults: an insisted call
        # that dropped the halal filter would answer a question nobody asked.
        result = await ask(
            session,
            butler,
            today,
            "Where can I eat somewhere halal nearby?",
            declining_factory(INVENTED),
        )
        assert place_world.near_non_halal.name not in result.answer
        assert place_world.cheap.name in result.answer

    async def test_a_kind_and_a_ceiling_are_read_out_of_it_too(
        self, session, butler, today, place_world
    ):
        result = await ask(
            session, butler, today, "Where can I eat noodles nearby?", declining_factory("")
        )
        assert place_world.noodles.name in result.answer
        # Half the price and would lead any list the kind filter did not reach.
        assert place_world.cheap.name not in result.answer


class TestWhenTheModelDoesAskForIt:
    """A sentence read as being about places, answered by a model that called
    the planner itself. Its arguments are the better ones — it read the whole
    sentence, where the classifier reads three things out of it."""

    async def test_the_planner_runs_exactly_once(self, session, butler, today, place_world):
        result = await ask(
            session,
            butler,
            today,
            "Where can I eat nearby?",
            scripted_factory(("start_day_planning", {"halal_only": True})),
        )
        assert result.tools_used == ["start_day_planning"]

    async def test_its_own_arguments_are_the_ones_used(
        self, session, butler, today, place_world
    ):
        # Nothing in "where can I eat nearby" says halal, so the classifier
        # would have passed no filter at all and Bak Kut Teh Tiga would be in
        # the list. It is not, which is the model's argument surviving.
        result = await ask(
            session,
            butler,
            today,
            "Where can I eat nearby?",
            scripted_factory(("start_day_planning", {"halal_only": True})),
        )
        assert place_world.near_non_halal.name not in result.answer

    async def test_and_without_them_that_place_comes_back(
        self, session, butler, today, place_world
    ):
        # The other half of the pair: without it, a filter that had quietly
        # stopped working would still pass the test above.
        result = await ask(
            session, butler, today, "Where can I eat nearby?", declining_factory("")
        )
        assert place_world.near_non_halal.name in result.answer


class TestTurnsThatAreNotAboutPlaces:
    """The trigger has to be narrow, or every unanswered question becomes a
    list of restaurants. The router's own ordering does the work: "afford"
    is tried before "places", so a question naming money stays one."""

    async def test_a_question_about_the_balance_reaches_no_planner(
        self, session, butler, today, place_world
    ):
        result = await ask(
            session, butler, today, "Why did my safe to spend drop?", declining_factory(INVENTED)
        )
        assert result.tools_used == []
        # And with nothing to speak from, the honest refusal still stands.
        assert result.answer == NOTHING_RAN

    async def test_a_greeting_overrides_an_unneeded_financial_tool_call(
        self, session, butler, today
    ):
        result = await ask(
            session,
            butler,
            today,
            "Hello",
            scripted_factory(("calculate_safe_to_spend", {})),
        )

        assert result.tools_used == ["just_talk"]
        assert result.evidence == []
        assert result.answer != NOTHING_RAN

    async def test_a_question_naming_an_amount_stays_a_question_about_money(
        self, session, butler, today, place_world
    ):
        # "Dinner" is in the sentence and the planner still must not run: this
        # is a question about whether the money is there.
        result = await ask(
            session,
            butler,
            today,
            "Can I afford RM60 dinner tonight?",
            declining_factory(INVENTED),
        )
        assert "start_day_planning" not in result.tools_used

    async def test_wanting_something_that_is_not_food_is_left_alone(
        self, session, butler, today, place_world
    ):
        result = await ask(
            session,
            butler,
            today,
            "I want to save more for the wedding",
            declining_factory(INVENTED),
        )
        assert "start_day_planning" not in result.tools_used

    async def test_a_receipt_turn_is_about_the_receipt(
        self, session, butler, today, place_world
    ):
        # An attachment decides the turn before any pattern is tried, so
        # "where should I eat" written under a photo of a bill is still about
        # the bill.
        result = await ask(
            session,
            butler,
            today,
            "Where should I eat after this?",
            declining_factory(INVENTED),
            attachment={
                "kind": "receipt",
                "merchant": "Nasi Kandar Pelita",
                "amount_sen": 1890,
                "occurred_on": "2026-09-03",
                "category": "food",
                "confidence": 94,
            },
        )
        assert "start_day_planning" not in result.tools_used


class TestAModelWhoseOnlyCallIsRefused:
    """The hole the guarantee had, found against the live model.

    ``insist`` stands down the moment the model proposes anything, on the
    grounds that a model engaging with its tools has better arguments than a
    regex. But a proposal is not a result: the guard can refuse it, and when
    every call in a turn is refused nothing runs, nothing is left to compose
    from, and the run used to go straight to the "I didn't look anything up"
    refusal — on a turn about places, which is the one turn that must never
    end there.

    Live, on a fresh thread: "i want fried chicken — add the cheapest one to
    today" is read as a places turn, and Qwen answered it by proposing
    add_place_to_today with an id it could not have — the ids are in the
    previous turn's tool payload, and the rendered history carries none of
    them. The guard refused it and the user got the refusal.
    """

    TURN = "i want fried chicken — add the cheapest one to today"

    REFUSED = (
        # A place id the model invented: refused by the policy, since no place
        # of that id is within range of the search.
        (
            "add_place_to_today",
            {
                "place_id": "kl999",
                "name": "Somewhere",
                "total_sen": 1400,
                "lat": 3.1577,
                "lng": 101.7120,
            },
        ),
        # Arguments the schema rejects.
        ("add_place_to_today", {"place_id": "", "name": "", "total_sen": 0}),
        # A tool that does not exist.
        ("apply_plan_change", {"amount_sen": 100}),
    )

    @pytest.mark.parametrize("call", REFUSED)
    async def test_the_planner_still_runs(
        self, session, butler, today, place_world, whole_world_in_range, call
    ):
        result = await ask(session, butler, today, self.TURN, scripted_factory(call))
        assert result.tools_used == ["start_day_planning"]
        assert dict(result.evidence)["Safe to spend today"] == "RM52.97"
        assert result.answer != NOTHING_RAN
        # And on the kind the sentence asked for, not on the tool's defaults:
        # there is no chicken in the fixed world, and the answer says so with
        # the count behind it rather than shrugging.
        assert "No chicken within range of you" in result.answer
        assert ["Nearby places", "7 within range, none of them Chicken"] in result.evidence

    @pytest.mark.parametrize("call", REFUSED)
    async def test_the_refusal_wrote_nothing_on_the_way(
        self, session, butler, today, place_world, call
    ):
        # The second pass is a second go at the tools, not a second go at the
        # write boundary: nothing reached a card and nothing reached the ledger.
        result = await ask(session, butler, today, self.TURN, scripted_factory(call))
        assert result.approval is None
        assert (await session.execute(select(ButlerApproval))).scalars().first() is None
        planned = await session.execute(
            select(Transaction).where(Transaction.source == SOURCE_PLAN)
        )
        assert planned.scalars().first() is None

    async def test_a_refused_call_on_a_turn_that_is_not_about_places_still_stops(
        self, session, butler, today, place_world
    ):
        # The extra lap is for the model to read the refusal and correct
        # itself, not a licence to answer a question about a protected bill
        # with a list of restaurants.
        result = await ask(
            session,
            butler,
            today,
            "Cut the rent",
            scripted_factory(("apply_plan_change", {"amount_sen": 100})),
        )
        assert result.tools_used == []
        assert result.answer == NOTHING_RAN

    async def test_it_goes_round_once_and_not_for_ever(
        self, session, butler, today, place_world
    ):
        """A model that proposes the same refused call again has to stop.

        ``ScriptedModel`` answers the second pass with prose because tool
        results are in the messages by then, so this drives the loop with a
        model that keeps proposing instead — the shape a real one has, and the
        one that would circle until the iteration cap without a bound here.
        """

        passes: list[int] = []

        class Stubborn(ScriptedModel):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                if not self.bound_tools:
                    return OfflineChatModel._generate(self, messages, stop, run_manager, **kwargs)
                passes.append(1)
                calls = [
                    {"name": name, "args": args, "id": f"stubborn-{index}", "type": "tool_call"}
                    for index, (name, args) in enumerate(self.calls)
                ]
                return ChatResult(
                    generations=[
                        ChatGeneration(message=AIMessage(content="", tool_calls=calls))
                    ]
                )

        def factory(**kwargs):
            return Stubborn(
                attachment=kwargs.get("attachment"),
                history=kwargs.get("history", ""),
                calls=[("apply_plan_change", {"amount_sen": 100})],
            )

        result = await ask(session, butler, today, self.TURN, factory)
        # Two goes at the model and no more: the proposal, the refusal, one
        # correction. Counted rather than inferred from the answer, because the
        # answer is the same whether this stopped at two or ran to the
        # iteration cap at six.
        assert len(passes) == 2
        assert result.tools_used == []
        assert result.answer == NOTHING_RAN


class TestNothingIsEverWrittenByThis:
    async def test_the_only_tool_it_may_run_is_a_read(self):
        spec = REGISTRY.get(insist_node.PLANNER)
        assert spec is not None
        assert not spec.is_write

    async def test_it_refuses_to_auto_run_a_write_even_if_pointed_at_one(
        self, session, butler, today, place_world, monkeypatch
    ):
        # The invariant is structural, not a property of the constant being
        # right. Aimed at the write, the node declines rather than proposing it.
        monkeypatch.setattr(insist_node, "PLANNER", "add_place_to_today")
        result = await ask(
            session, butler, today, "Where can I eat nearby?", declining_factory(INVENTED)
        )
        assert result.approval is None
        assert result.tools_used == []
        assert (await session.execute(select(ButlerApproval))).scalars().first() is None
        # The seeded ledger has rows of its own, so what is checked is that no
        # plan draft appeared — the thing that write would have written.
        planned = await session.execute(
            select(Transaction).where(Transaction.source == SOURCE_PLAN)
        )
        assert planned.scalars().first() is None

    async def test_a_write_the_model_proposed_still_reaches_the_card(
        self, session, butler, today, place_world
    ):
        # A sentence this node would classify as being about places, answered
        # by a model that proposed a write. The write goes to the interrupt and
        # the planner is not run underneath it.
        result = await ask(
            session,
            butler,
            today,
            "Where can I eat nearby? Add the mamak.",
            scripted_factory(
                (
                    "add_place_to_today",
                    {
                        "place_id": place_world.mid.id,
                        "name": place_world.mid.name,
                        "total_sen": 1250,
                        **place_world.origin,
                    },
                )
            ),
        )
        assert result.approval is not None
        assert result.approval["tool"] == "add_place_to_today"
        assert result.tools_used == []


class TestTheOfflinePathIsUntouched:
    """Offline the model always calls the planner itself, so this node has
    nothing to do — and the demo the container actually runs must not notice
    it was added."""

    async def test_a_craving_runs_the_planner_once_and_names_what_it_found(
        self, session, butler, today, place_world
    ):
        result = await ask(session, butler, today, "I feel like noodles", offline_factory)
        assert result.tools_used == ["start_day_planning"]
        assert f"{place_world.noodles.name} — RM18" in result.answer

    async def test_a_question_about_bills_still_reads_the_commitments(
        self, session, butler, today, place_world
    ):
        result = await ask(session, butler, today, "What bills are due?", offline_factory)
        assert result.tools_used == ["list_commitments"]


class TestWhatTheNodeItselfReturns:
    """The node in isolation, because one thing it does is invisible from the
    outside: it takes the model's paragraph away rather than adding to it."""

    RUNTIME = object()  # events.emit writes nowhere without a stream_writer

    def state(self, text: str, *messages):
        return {"messages": [HumanMessage(content=text), *messages], "attachment": None}

    async def test_it_replaces_the_unevidenced_paragraph(self):
        reply = AIMessage(id="a1", content=INVENTED)
        added = await insist_node.insist(
            self.state("Where can I eat somewhere halal under RM15?", reply), self.RUNTIME
        )

        (message,) = added["messages"]
        # Same id, so the reducer overwrites the paragraph rather than filing
        # it behind the tool call where compose would still read it.
        assert message.id == "a1"
        assert message.content == ""
        (call,) = message.tool_calls
        assert call["name"] == "start_day_planning"
        # The sentence goes with the filters now. The planner reads it on the
        # turn where it chooses between the places, which is the only turn that
        # can act on "somewhere I can sit for a while".
        assert call["args"] == {
            "halal_only": True,
            "cap_sen": 1500,
            "request": "Where can I eat somewhere halal under RM15?",
        }

    async def test_it_adds_nothing_when_the_model_already_asked(self):
        reply = AIMessage(
            id="a1",
            content="",
            tool_calls=[
                {"name": "start_day_planning", "args": {}, "id": "t1", "type": "tool_call"}
            ],
        )
        added = await insist_node.insist(self.state("Where can I eat?", reply), self.RUNTIME)
        assert added == {}

    async def test_it_adds_nothing_once_the_planner_has_answered(self):
        # Covers the failed and the refused call as well as the successful one:
        # a result of any kind is the turn's answer about the planner.
        ran = ToolMessage(
            content="{}", name="start_day_planning", tool_call_id="t1", status="error"
        )
        added = await insist_node.insist(
            self.state("Where can I eat?", ran, AIMessage(id="a2", content="Sorry.")),
            self.RUNTIME,
        )
        assert added == {}

    async def test_a_combined_dinner_question_hands_the_measured_cost_to_goals(self):
        planned = ToolMessage(
            content=(
                '{"recommendation": {"id": "place-1", "name": "Kopi Kaki", '
                '"total_sen": 1450}}'
            ),
            name="start_day_planning",
            tool_call_id="t1",
        )
        added = await insist_node.insist(
            self.state(
                "Somewhere cheap for dinner — and does it hurt my house goal?",
                planned,
                AIMessage(id="a2", content=""),
            ),
            self.RUNTIME,
        )

        (message,) = added["messages"]
        (call,) = message.tool_calls
        assert call["name"] == "start_goal_planning"
        assert call["args"]["action"] == "impact"
        assert call["args"]["proposed_spend_sen"] == 1450

    @pytest.mark.parametrize(
        "text",
        [
            "Can I afford RM60 dinner tonight?",
            "Why did my safe to spend drop?",
            "How is the wedding goal doing?",
            "Remember that I hate queueing",
            "What bills are due?",
        ],
    )
    async def test_it_adds_nothing_to_a_turn_that_is_not_about_places(self, text):
        added = await insist_node.insist(
            self.state(text, AIMessage(id="a1", content="Some prose.")), self.RUNTIME
        )
        assert added == {}
