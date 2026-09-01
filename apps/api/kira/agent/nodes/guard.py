"""guard — the write boundary, and the only place a tool call becomes permitted.

Every proposed call passes through here before anything executes. Unknown
names, arguments that fail validation and protected resources are refused with
a message the model can read; what survives is split by `ToolSpec.kind`, and a
write is routed to approval rather than to execution.
"""

from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime
from pydantic import ValidationError

from kira.agent import events
from kira.agent.policy import refusal_for
from kira.agent.state import ButlerContext, ButlerState
from kira.agent.tools import REGISTRY
from kira.config import get_settings


def _last_ai(state: ButlerState) -> AIMessage | None:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage):
            return message
    return None


def _refusal(call: dict[str, Any], reason: str) -> ToolMessage:
    """A refusal is a tool result, not an error: the model has to see it."""
    return ToolMessage(
        content=json.dumps({"refused": True, "reason": reason}),
        name=call.get("name", "unknown"),
        tool_call_id=call.get("id", ""),
        status="error",
    )


async def guard(state: ButlerState, runtime: Runtime[ButlerContext]) -> dict:
    reply = _last_ai(state)
    calls = list(getattr(reply, "tool_calls", None) or [])
    if not calls:
        # Cleared, not left standing. `refusals` says what THIS pass turned
        # away, and `route_after_guard` reads it to decide whether the turn is
        # heading for compose with nothing at all. A pass that proposed nothing
        # refused nothing, and a leftover from the pass before it would send
        # the run back round for a refusal the model has already answered.
        return {
            "approved_reads": [],
            "pending_write": None,
            "pending_workflow": None,
            "refusals": [],
        }

    context = runtime.context
    settings = get_settings()

    # Two stops, and they answer different questions. The iteration cap bounds
    # how many times the model may go round; the budget bounds how long the
    # user waits. Neither implies the other: six passes over a warm cache are
    # quick, and two over a cold routing call are not. Both are needed now that
    # every result comes back to the model rather than straight to the answer.
    started = state.get("started_at") or 0.0
    if started and time.monotonic() - started > settings.butler_turn_budget_seconds:
        events.emit(runtime, events.THINKING, text="That is long enough — answering now")
        return {
            "approved_reads": [],
            "pending_write": None,
            "pending_workflow": None,
            "refusals": [],
            "messages": [
                _refusal(call, "Time is up for this turn; answer from what you already have.")
                for call in calls
            ],
        }

    if state.get("iterations", 0) > settings.butler_max_tool_iterations:
        # Refusals cleared for the same reason as above, and here it is
        # load-bearing rather than tidy: this branch is the stop, and a stale
        # list left in the state would have `route_after_guard` send the run
        # back to the model to be stopped again.
        return {
            "approved_reads": [],
            "pending_write": None,
            "pending_workflow": None,
            "refusals": [],
            "messages": [
                _refusal(call, "Enough looking; answer from what you already have.")
                for call in calls
            ],
        }

    reads: list[dict[str, Any]] = []
    write: dict[str, Any] | None = None
    workflow: dict[str, Any] | None = None
    refusals: list[str] = []
    responses: list[ToolMessage] = []

    for call in calls:
        name = call.get("name", "")
        spec = REGISTRY.get(name)
        if spec is None:
            reason = f"There is no tool called {name}."
            refusals.append(reason)
            responses.append(_refusal(call, reason))
            continue

        try:
            args = spec.args_model.model_validate(call.get("args") or {})
        except ValidationError as exc:
            reason = f"{name} was called with arguments it cannot accept: {exc.errors()}"
            refusals.append(reason)
            responses.append(_refusal(call, reason))
            continue

        # Protected resources are refused whatever the tier, and before anything runs.
        blocked = await refusal_for(
            context.session, context.user, name, args.model_dump(mode="json")
        )
        if blocked is not None:
            refusals.append(blocked)
            responses.append(_refusal(call, blocked))
            events.emit(runtime, events.THINKING, text="That one is off limits")
            continue

        permitted = {
            "id": call.get("id", ""),
            "name": name,
            "args": args.model_dump(mode="json"),
        }
        if spec.is_workflow:
            if workflow is None and write is None:
                workflow = permitted
            else:
                reason = "One financial workflow at a time."
                refusals.append(reason)
                responses.append(_refusal(call, reason))
        elif spec.is_write:
            # Only the first write is ever proposed: an approval card asks about
            # one change, and the user answering it is the point.
            if write is None and workflow is None:
                write = permitted
            else:
                reason = "One change at a time. Ask me again once this one is decided."
                refusals.append(reason)
                responses.append(_refusal(call, reason))
        else:
            reads.append(permitted)

    if workflow and reads:
        # A specialised workflow loads its own confirmed snapshot, so running
        # unrelated reads beside it would duplicate facts the child is about to
        # measure properly. They are turned away rather than dropped: every
        # call the model made has to come back with a result or the next
        # request is malformed, and the model can simply ask again next pass
        # now that a workflow no longer ends the turn.
        reason = (
            "The specialist gathers its own figures. "
            "Ask for this afterwards if you still need it."
        )
        for call in reads:
            refusals.append(reason)
            responses.append(_refusal(call, reason))
        reads = []

    return {
        "approved_reads": reads,
        "pending_write": write,
        "pending_workflow": workflow,
        "refusals": refusals,
        "messages": responses,
    }


def route_after_guard(state: ButlerState) -> str:
    if state.get("pending_workflow"):
        return "workflow"
    if state.get("approved_reads"):
        return "tools"
    if state.get("pending_write"):
        return "approval"
    # Everything the model asked for was refused, and nothing has run this
    # turn. Straight on to compose, that is an answer built from no evidence at
    # all -- the honest refusal, which is the one outcome the whole insistence
    # design exists to stop a question about places reaching. Measured against
    # a live Qwen: "i want fried chicken — add the cheapest one to today" is a
    # places turn, the model answered it by proposing add_place_to_today with
    # an id it could not have (the ids are in the previous turn's tool payload,
    # and the rendered history carries none), the guard refused it, and
    # `insist` had already stood down on the grounds that the model was
    # engaging with its tools. The planner never ran and the user got "I didn't
    # look anything up for that."
    #
    # So the run goes back to the model instead, which is also the only way the
    # refusal is ever read: `_refusal` writes it as a tool result precisely so
    # the model can see it, and a turn where every call was refused is exactly
    # the turn where nobody would have. On that pass the model can correct its
    # call, and `insist` gets the go it was denied.
    #
    # Once only, and that is enough for both jobs: the refusal has been read
    # and insist has had its chance, so a second lap would be the same lap.
    # `iterations` counts the model's own turns and is one here. The bound is
    # not decoration -- without it a model that keeps proposing the same
    # refused call circles until the recursion limit, because the iteration cap
    # above is itself a refusal with nothing permitted.
    if state.get("refusals") and not state.get("tools_used") and state.get("iterations", 0) <= 1:
        return "agent"
    return "compose"


# The one route that says "stop looking". Everything else in this file decides
# where the run goes next; this decides that it does not go anywhere.


def route_after_tools(state: ButlerState) -> str:
    """Where a turn goes once its reads have run: back to the model.

    It used to go to compose whenever nothing was refused, on the grounds that
    a second tool-bound round trip is latency the user pays for nothing. That
    was true while a turn was one question and one lookup. It is what stopped
    the Butler ever noticing something in a result and going to check it —
    reading that a bill lands on Thursday and never asking what is in the
    account on Thursday — because the only pass that could have asked had
    already been spent.

    So results come back, and the cost is bounded where cost belongs: the guard
    stops the loop on the iteration cap or the wall-clock budget, and a pass
    with nothing left to ask proposes no call and falls through to compose.
    """
    if state.get("pending_workflow"):
        return "workflow"
    if state.get("pending_write"):
        return "approval"
    return "agent"
