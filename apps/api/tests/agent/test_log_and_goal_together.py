"""One real turn that failed, and the four separate defects behind it.

The sentence, typed by a user on 2026-09-08:

    "I have ate RM 35 of chicken rice and i want to set a goal of having a
     saviwng of 1 million"

The chicken rice was logged. The goal never happened, and what the user read
instead was the string "<tool_code>\\n</tool_code>". Four things had to be wrong
at once for that to be the outcome, and each is pinned here:

1. The turn ended at the first applied write, so nothing went looking for the
   second half. (Fixed separately; `test_multi_step_control.py` holds that.)
2. `insist` forced the day planner and nothing else, so a model that declined
   to call the goal specialist was never overruled.
3. "1 million" parsed as RM1.00, so even a forced call would have proposed a
   one-ringgit goal.
4. The first amount in the sentence was taken as the target, so the goal would
   have been for the price of the chicken rice.
"""

from __future__ import annotations

from datetime import date

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from kira.agent.llm import _amount_sen, _amounts_sen, _goal_workflow_args, route_for
from kira.agent.nodes.compose import _clean
from kira.agent.nodes.insist import GOALS, insist
from kira.agent.run import resume_approval, run_turn
from kira.agent.state import ButlerContext, ButlerState
from tests.agent.conftest import sequenced_factory
from tests.agent.test_multi_agent import Runtime
from tests.agent.test_multi_step_control import pending

REAL = "I have ate RM 35 of chicken rice and i want to set a goal of having a saviwng of 1 million"
ONE_MILLION_SEN = 100_000_000


class TestAnAmountWithAScaleOnIt:
    """ "1 million" is not one ringgit, and for a while it was."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("1 million", ONE_MILLION_SEN),
            ("one million", ONE_MILLION_SEN),
            ("RM1 million", ONE_MILLION_SEN),
            ("1.5 million", 150_000_000),
            ("1 juta", ONE_MILLION_SEN),
            ("500k", 50_000_000),
            ("2 ribu", 200_000),
            ("3 thousand", 300_000),
        ],
    )
    def test_the_scale_is_read_rather_than_dropped(self, text, expected):
        assert _amount_sen(text) == expected

    def test_a_plain_amount_still_reads_the_way_it_did(self):
        assert _amount_sen("RM35") == 3500
        assert _amount_sen("RM1,000") == 100_000
        assert _amount_sen("twelve fifty") == 1250

    def test_a_scaled_amount_is_not_also_counted_as_its_own_prefix(self):
        """ "RM1 million" is one amount, not RM1,000,000 and RM1 besides."""
        assert _amounts_sen("RM1 million") == [ONE_MILLION_SEN]

    def test_both_amounts_come_back_in_the_order_written(self):
        assert _amounts_sen(REAL) == [3500, ONE_MILLION_SEN]


class TestTheTargetComesFromTheGoalClause:
    def test_the_lunch_is_not_mistaken_for_the_target(self):
        args = _goal_workflow_args(REAL, None)
        assert args["action"] == "create"
        assert args["target_amount_sen"] == ONE_MILLION_SEN

    def test_a_sentence_with_only_a_goal_in_it_is_unchanged(self):
        args = _goal_workflow_args("i want to set a goal of saving 1 million", None)
        assert args["target_amount_sen"] == ONE_MILLION_SEN
        assert args["current_saved_sen"] == 0

    def test_long_term_becomes_an_editable_five_year_draft(self):
        args = _goal_workflow_args(
            "set my 1 million savings as a long-term goal",
            None,
            date(2026, 9, 9),
        )
        assert args["target_date"] == "2031-09-09"
        assert args["current_saved_sen"] == 0

    def test_money_already_put_aside_is_not_the_target(self):
        """The marker list excludes "save" precisely because of this sentence."""
        args = _goal_workflow_args(
            "I want RM1,000 for a Penang trip by December 2026. I already saved RM200.",
            None,
        )
        assert args["target_amount_sen"] == 100_000
        assert args["current_saved_sen"] == 20_000


class TestTheGoalSpecialistIsInsistedOnToo:
    """The planner had a safety net for this. The goal specialist did not."""

    def _state(self, text: str, *, proposed) -> ButlerState:
        return ButlerState(
            messages=[HumanMessage(content=text), AIMessage(content="", tool_calls=proposed)],
            history_block="",
            iterations=1,
        )

    async def test_the_router_always_read_this_sentence_correctly(self):
        """The reading was never the problem; acting on it was."""
        assert route_for(REAL).tools == (GOALS,)

    def test_a_terse_goal_followup_stays_in_the_goal_workflow(self):
        history = "User: Hi i want to set a saving 1 million goal\nKira: What target date?"
        assert route_for("make it as long term goal", None, history).name == "goal_workflow"

    async def test_a_terse_followup_carries_the_original_target(self, session, butler, today):
        user, thread = butler
        runtime = Runtime(
            ButlerContext(session=session, user=user, today=today, thread_id=thread.id)
        )
        state = self._state("make it as long term goal", proposed=[])
        state["history_block"] = (
            "User: Hi i want to set a saving 1 million goal\nKira: What target date?"
        )
        update = await insist(state, runtime)
        call = update["messages"][0].tool_calls[0]
        assert call["name"] == GOALS
        assert call["args"]["target_amount_sen"] == ONE_MILLION_SEN

    def test_plan_my_day_is_a_day_planning_request(self):
        assert route_for("plan my day according to what I can spend today").name == "places"

    def test_foresight_opens_the_forecast_view(self):
        route = route_for("show me my foresight")
        assert route.name == "foresight"
        assert route.tools == ("project_future", "control_app")
        assert route.arguments("show me my foresight", None)["control_app"] == {
            "action": "set_plan_view",
            "plan_view": "foresight",
        }

    async def test_a_model_that_proposes_nothing_is_overruled(self, session, butler, today):
        user, thread = butler
        runtime = Runtime(
            ButlerContext(session=session, user=user, today=today, thread_id=thread.id)
        )
        update = await insist(self._state(REAL, proposed=[]), runtime)

        calls = update["messages"][0].tool_calls
        assert [call["name"] for call in calls] == [GOALS]
        assert calls[0]["args"]["target_amount_sen"] == ONE_MILLION_SEN

    async def test_a_model_that_did_propose_something_keeps_its_own_call(
        self, session, butler, today
    ):
        """Insistence is a floor, not an override."""
        user, thread = butler
        runtime = Runtime(
            ButlerContext(session=session, user=user, today=today, thread_id=thread.id)
        )
        proposed = [{"name": "add_transaction", "args": {}, "id": "c0", "type": "tool_call"}]
        assert await insist(self._state(REAL, proposed=proposed), runtime) == {}


class TestMachineryNeverReachesTheUser:
    def test_a_tool_code_block_is_taken_out_whole(self):
        assert _clean("<tool_code>\n</tool_code>") == ""
        assert _clean("<tool_code>start_goal_planning(x)</tool_code>") == ""

    def test_a_fenced_python_tool_call_is_taken_out_whole(self):
        leaked = "```python start_goal_planning(action='create', target_amount_sen=100) ```"
        assert _clean(leaked) == ""

    @pytest.mark.parametrize(
        "leaked",
        [
            "<tool_call>foo</tool_call>",
            "<tool_use>foo</tool_use>",
            "<function_call>foo</function_call>",
        ],
    )
    def test_every_shape_of_it_is_stripped(self, leaked):
        assert _clean(f"Here you go. {leaked} Done.") == "Here you go.  Done."

    def test_an_ordinary_answer_is_left_exactly_alone(self):
        answer = "You have RM52.97 safe to spend today.\n\nThat is your balance minus bills."
        assert _clean(answer) == answer


class TestTheWholeTurnEndToEnd:
    async def test_the_goal_is_reached_after_the_lunch_is_approved(self, session, butler, today):
        """The live failure, replayed against the live model's own behaviour.

        Qwen proposed the transaction and then, on the pass that should have
        proposed the goal, called nothing at all. That second batch is empty on
        purpose: it is the model declining, which is the case `insist` exists
        for and the one that had no cover for goals.
        """
        user, thread = butler
        factory = sequenced_factory(
            [
                (
                    "add_transaction",
                    {
                        "merchant": "chicken rice",
                        "amount_sen": 3500,
                        "occurred_on": today.isoformat(),
                        "category": "food",
                    },
                )
            ],
            [],
        )

        result = await run_turn(
            session, user, thread, text=REAL, today=today, model_factory=factory
        )
        assert result.approval["tool"] == "add_transaction"

        card = await pending(session, thread, "add_transaction")
        result = await resume_approval(
            session,
            user,
            thread,
            graph_thread=card.graph_thread_id,
            decision={"action": "accept"},
            today=today,
            model_factory=factory,
        )

        # Both halves of the sentence were acted on: the lunch is on the ledger
        # as a draft, and the goal specialist actually ran.
        assert result.applied["tool"] == "add_transaction"
        assert GOALS in result.tools_used
        # Whatever it answers, it is not machinery.
        assert "<tool_code>" not in result.answer
