"""The specialist contract, and the loop that now reads what a specialist says.

A module with a model in it reaches the Butler as `kind="workflow"` with an
`agent`, and everything downstream of the registry treats its report exactly as
it treats a tool result. These are the properties that make that true.
"""

from __future__ import annotations

import time
import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel

from kira.agent import prompt
from kira.agent.nodes.delegate import delegate, route_after_delegate
from kira.agent.nodes.guard import guard, route_after_tools
from kira.agent.state import initial_state
from kira.agent.tools import REGISTRY
from kira.agent.tools.spec import (
    AgentContext,
    AgentReport,
    EvidenceRow,
    ToolResult,
    ToolSpec,
    ToolSpecError,
)


class Args(BaseModel):
    note: str = ""


async def _never(_ctx, _args) -> ToolResult:  # pragma: no cover - never invoked
    raise RuntimeError("not runnable")


async def _report(_ctx: AgentContext, args: Args) -> AgentReport:
    return AgentReport(
        findings={"heard": args.note},
        evidence=(EvidenceRow("Checked", args.note),),
        answer="A specialist looked at it.",
        llm_calls=2,
    )


def _spec(**overrides) -> ToolSpec:
    fields = {
        "name": "start_pretend_planning",
        "module": "pretend",
        "kind": "workflow",
        "description": "A stand-in specialist.",
        "args_model": Args,
        "handler": _never,
        "agent": _report,
    }
    return ToolSpec(**(fields | overrides))


class Runtime:
    """Enough of LangGraph's runtime for a node, with the stream captured."""

    def __init__(self, context):
        self.context = context
        self.events: list[dict] = []
        self.stream_writer = self.events.append


class TestTheContract:
    def test_a_workflow_without_an_agent_cannot_be_registered(self):
        with pytest.raises(ToolSpecError, match="no agent"):
            _spec(agent=None)

    def test_a_read_cannot_declare_an_agent(self):
        # Otherwise the agent would be silently unreachable: only the workflow
        # route ever looks at the field.
        with pytest.raises(ToolSpecError, match="declares an agent"):
            _spec(kind="read", agent=_report)

    def test_every_registered_workflow_has_one(self):
        for spec in REGISTRY.workflows():
            assert spec.agent is not None, spec.name


class TestDelegation:
    """The node that runs a specialist, in isolation from the graph."""

    @pytest.fixture
    def registered(self):
        spec = _spec()
        REGISTRY.register(spec)
        yield spec
        REGISTRY._specs.pop(spec.name)

    async def _run(self, registered, session, butler, today, agent=None):
        user, thread = butler
        if agent is not None:
            REGISTRY._specs[registered.name] = _spec(agent=agent)
        from kira.agent.state import ButlerContext

        runtime = Runtime(
            ButlerContext(
                session=session,
                user=user,
                today=today,
                thread_id=thread.id,
                source_message_id=uuid.uuid4(),
            )
        )
        state = initial_state()
        state["pending_workflow"] = {
            "id": "call-1",
            "name": registered.name,
            "args": {"note": "the rent"},
        }
        return await delegate(state, runtime), runtime

    async def test_findings_come_back_as_an_ordinary_tool_message(
        self, registered, session, butler, today
    ):
        update, _ = await self._run(registered, session, butler, today)
        message = update["messages"][0]

        assert isinstance(message, ToolMessage)
        assert message.tool_call_id == "call-1"
        assert "the rent" in message.content
        assert message.status != "error"

    async def test_the_report_goes_back_to_the_butler_to_answer_from(
        self, registered, session, butler, today
    ):
        update, _ = await self._run(registered, session, butler, today)

        assert route_after_delegate({**update}) == "agent"
        assert update["evidence"] == [["Checked", "the rent"]]
        assert update["tools_used"] == [registered.name]
        assert update["reports"] == ["A specialist looked at it."]
        assert update["child_llm_calls"] == 2

    async def test_the_child_s_calls_are_counted_and_the_butler_s_are_not(
        self, registered, session, butler, today
    ):
        # `iterations` counts the Butler's own passes. Delegating already cost
        # one to propose, so moving it here would report the same call twice.
        update, _ = await self._run(registered, session, butler, today)
        assert "iterations" not in update

    async def test_the_panel_gets_the_child_s_rows(
        self, registered, session, butler, today
    ):
        _, runtime = await self._run(registered, session, butler, today)
        rows = [event for event in runtime.events if event["type"] == "evidence"]
        assert rows == [{"type": "evidence", "rows": [["Checked", "the rent"]]}]

    async def test_a_card_from_the_child_ends_the_turn(
        self, registered, session, butler, today
    ):
        async def raises_a_card(_ctx, _args):
            return AgentReport(
                findings={},
                answer="Here is what I would change.",
                approval={
                    "approval_id": "a-1",
                    "tool": "apply_goal_plan_change",
                    "summary": "Move the target date.",
                },
            )

        update, runtime = await self._run(
            registered, session, butler, today, agent=raises_a_card
        )

        assert route_after_delegate({**update}) == "end"
        assert update["answer"] == "Here is what I would change."
        assert [event["type"] for event in runtime.events] == [
            "tool",
            "token",
            "approval",
        ]

    async def test_a_specialist_that_raises_answers_the_call_anyway(
        self, registered, session, butler, today
    ):
        async def breaks(_ctx, _args):
            raise RuntimeError("the planner is down")

        update, _ = await self._run(registered, session, butler, today, agent=breaks)
        message = update["messages"][0]

        # Unanswered tool calls make the next request malformed, so a child that
        # died still comes back as a result the model can read and speak to.
        assert message.status == "error"
        assert message.tool_call_id == "call-1"
        assert "the planner is down" in message.content
        assert route_after_delegate({**update}) == "agent"


class TestTheGuardBoundsTheLoop:
    def _runtime(self, session, butler, today):
        from kira.agent.state import ButlerContext

        user, thread = butler
        return Runtime(
            ButlerContext(
                session=session, user=user, today=today, thread_id=thread.id
            )
        )

    def _state(self, *calls, **extra):
        state = initial_state()
        state["messages"] = [
            HumanMessage(content="what can I afford"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": name, "args": args, "id": f"c{i}", "type": "tool_call"}
                    for i, (name, args) in enumerate(calls)
                ],
            ),
        ]
        state["iterations"] = 1
        state.update(extra)
        return state

    async def test_reads_beside_a_specialist_are_refused_not_dropped(
        self, session, butler, today
    ):
        state = self._state(
            ("start_goal_planning", {"action": "create"}),
            ("list_goals", {}),
        )
        update = await guard(state, self._runtime(session, butler, today))

        assert update["pending_workflow"]["name"] == "start_goal_planning"
        assert update["approved_reads"] == []
        # The dropped read used to leave its call unanswered, which was
        # harmless only while a workflow ended the turn. It no longer does.
        answered = {message.tool_call_id for message in update["messages"]}
        assert answered == {"c1"}

    async def test_a_blown_budget_stops_the_looking(self, session, butler, today):
        state = self._state(
            ("list_goals", {}), started_at=time.monotonic() - 999.0
        )
        update = await guard(state, self._runtime(session, butler, today))

        assert update["approved_reads"] == []
        assert update["pending_write"] is None
        assert "Time is up" in update["messages"][0].content
        # Refusals are cleared so the run does not go back to the model to be
        # stopped a second time.
        assert update["refusals"] == []

    async def test_an_unstarted_clock_does_not_stop_anything(
        self, session, butler, today
    ):
        # A state checkpointed before this field existed, and any caller that
        # drives the guard directly. Neither should lose its tools.
        state = self._state(("list_goals", {}))
        state["started_at"] = 0.0
        update = await guard(state, self._runtime(session, butler, today))

        assert [call["name"] for call in update["approved_reads"]] == ["list_goals"]


class TestTheLoopCloses:
    def test_a_clean_read_goes_back_to_the_model(self):
        # This is the change that makes chaining possible: the pass that could
        # have asked the follow-up question used to be spent already.
        state = {"tools_used": ["list_goals"], "evidence": [["a", "b"]]}
        assert route_after_tools(state) == "agent"

    def test_a_write_still_leaves_the_loop(self):
        assert route_after_tools({"pending_write": {"name": "add_transaction"}}) == "approval"

    def test_a_specialist_still_takes_the_workflow_door(self):
        assert route_after_tools({"pending_workflow": {"name": "x"}}) == "workflow"


class TestTheTwoTurnsReadDifferentPrompts:
    def test_the_choosing_turn_is_not_handed_the_voice(self):
        text = prompt.reasoning_prompt(
            context="Balance RM10.00", memory="", history="", tool_names=("list_goals",)
        )
        # The register rules, the ringgit formatting and the "never say as an
        # AI" clause bear on nothing this turn does, and more prose on it
        # measurably pushed a live model out of calling tools at all.
        assert "two registers" not in text
        assert "RM1,234.56" not in text
        assert "list_goals" in text
        assert "Balance RM10.00" in text

    def test_the_writing_turn_is_not_handed_the_tools(self):
        text = prompt.composing_prompt(
            context="Balance RM10.00", memory="", history="", evidence="- Balance: RM10.00"
        )
        assert "Tools available this turn" not in text
        assert "two registers" in text
        assert "- Balance: RM10.00" in text
        assert "Write the answer now." in text

    def test_the_choosing_turn_is_told_which_of_them_reason(self):
        text = prompt.reasoning_prompt(
            context="",
            memory="",
            history="",
            tool_names=("list_goals", "start_goal_planning"),
            workflow_names=("start_goal_planning",),
        )
        assert "specialists rather than lookups" in text
        assert "The specialists this turn: start_goal_planning." in text
