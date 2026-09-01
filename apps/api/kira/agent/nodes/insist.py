"""insist — the planner runs because the turn is about places, not because the
model felt like asking.

Whether any evidence is gathered is otherwise entirely the online model's
choice, and measured against a live Qwen it declines. "i want eat fried
chicken" came back as fluent prose with no tool call and nothing behind it;
told more firmly to answer, it named a restaurant that is not in the data at
all. Instructing it harder made it worse rather than better — more text on the
tool-calling turn pushed it out of calling tools altogether — so the decision
is taken here, in code, where it cannot be talked out of.

The offline router already reads these sentences correctly, and reads the kind
of food, the halal filter and the ceiling out of them besides. This is that
same classification applied to the online path, not a second opinion about what
a request for food looks like: one pattern, one place it lives.

Where it sits is the design. Before ``agent`` it would decide the arguments in
the model's place on every such turn, and the model reads "somewhere halal that
isn't a long walk" better than a regex ever will. After ``guard`` — as a
fallback once nothing ran — the call it added would be the only call in the app
that never crossed the write boundary: arguments unvalidated, protected
resources unchecked. Between the two, the model proposes first and keeps its own
arguments whenever it proposed any, and what this node adds is checked by
exactly the same guard as everything else.

An edge condition could not do the job at all. An edge chooses where the run
goes next; it cannot put the call into the state for the guard to read.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from kira.agent import events
from kira.agent.llm import _today_from, route_for
from kira.agent.state import ButlerContext, ButlerState
from kira.agent.tools import REGISTRY

# The one tool this node may run on its own. Several other reads are skipped by
# the online model in the same way, but each needs its own answer to "what does
# such a turn look like", and one deterministic call is enough to reason about.
PLANNER = "build_day_plan"

# The route whose pattern decides. Named rather than taken from whichever route
# happens to mention the planner, so widening the offline router later cannot
# quietly widen this with it.
PLACES = "places"

# Only ever attached to a call this node added, so a transcript says plainly
# which calls the model asked for and which one it did not.
CALL_ID = "insisted-build_day_plan"


def _last_ai(messages: Sequence[BaseMessage]) -> AIMessage | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


def _last_human(messages: Sequence[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


def _already_answered(messages: Sequence[BaseMessage]) -> bool:
    """Whether the planner has already come back this turn, however it went.

    A refusal from the guard and a handler that raised are both results here,
    on purpose: either way the turn has its answer about the planner, and
    insisting a second time would only ask the same question again.
    """
    return any(
        isinstance(message, ToolMessage) and message.name == PLANNER for message in messages
    )


async def insist(state: ButlerState, runtime: Runtime[ButlerContext]) -> dict:
    messages = state.get("messages", [])
    reply = _last_ai(messages)
    if reply is None:  # pragma: no cover - agent always leaves one behind
        return {}

    # The model asked for something, so it is engaging with its tools and its
    # arguments are better than this node's. That covers the write path too: a
    # proposed add_place_to_today is left alone to reach the approval card.
    if getattr(reply, "tool_calls", None):
        return {}

    if _already_answered(messages):
        return {}

    text, attachment = _last_human(messages), state.get("attachment")
    # Read with the conversation behind it, so "what about korean then" is the
    # request for food it plainly is rather than an unreadable fragment. The
    # online model is no better at this on its own: with nothing to go on it
    # answered the same sentence out of its own head.
    route = route_for(text, attachment, state.get("history_block", ""))
    if route.name != PLACES:
        return {}

    # Structural rather than trusting: whatever PLANNER names, this node will
    # not auto-run it if it is a write. Nothing may reach the database without
    # the user answering a card, and that must not rest on a constant above
    # being the right one.
    spec = REGISTRY.get(PLANNER)
    if spec is None or spec.is_write:
        return {}

    # Read out of the sentence by the route itself, so the ceiling, the halal
    # filter and the kind of food come from the one parser the offline path
    # already uses rather than from a second copy of it here.
    # `arguments` also builds date-bearing calls, so it is handed the date the
    # prompt states — the same one the offline model reads.
    arguments = (
        route.arguments(text, attachment, _today_from(state["messages"]))
        if route.arguments
        else {}
    )
    events.emit(runtime, events.THINKING, text="Checking what is actually near you")

    # The model's reply is replaced rather than followed, because what it wrote
    # is prose composed with no evidence at all — the invented restaurant, in
    # the case this exists for. Left in the messages it would still be there at
    # compose, which reads the whole conversation and has already been caught
    # copying place names out of it. So the turn keeps the model's place in the
    # history and loses the paragraph it should not have written.
    call = {
        "name": PLANNER,
        "args": arguments.get(PLANNER, {}),
        "id": CALL_ID,
        "type": "tool_call",
    }
    return {"messages": [AIMessage(id=reply.id, content="", tool_calls=[call])]}
