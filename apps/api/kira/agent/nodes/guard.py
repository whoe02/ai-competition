"""guard — the write boundary, and the only place a tool call becomes permitted.

Every proposed call passes through here before anything executes. Unknown
names, arguments that fail validation and protected resources are refused with
a message the model can read; what survives is split by `ToolSpec.kind`, and a
write is routed to approval rather than to execution.
"""

from __future__ import annotations

import json
import logging
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

log = logging.getLogger("uvicorn.error.kira.butler")


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
        log.info("butler.node guard no_calls thread_id=%s", runtime.context.thread_id)
        # Cleared, not left standing. `refusals` says what THIS pass turned
        # away, and `route_after_guard` reads it to decide whether the turn is
        # heading for compose with nothing at all. A pass that proposed nothing
        # refused nothing, and a leftover from the pass before it would send
        # the run back round for a refusal the model has already answered.
        return {
            "approved_reads": [],
            "pending_write": None,
            "pending_writes": [],
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
        log.info(
            "butler.node guard budget_exhausted thread_id=%s calls=%s",
            context.thread_id,
            [call.get("name") for call in calls],
        )
        events.emit(runtime, events.THINKING, text="That is long enough — answering now")
        return {
            "approved_reads": [],
            "pending_write": None,
            "pending_writes": [],
            "pending_workflow": None,
            "refusals": [],
            "messages": [
                _refusal(call, "Time is up for this turn; answer from what you already have.")
                for call in calls
            ],
        }

    if state.get("iterations", 0) > settings.butler_max_tool_iterations:
        log.info(
            "butler.node guard iteration_cap thread_id=%s calls=%s",
            context.thread_id,
            [call.get("name") for call in calls],
        )
        # Refusals cleared for the same reason as above, and here it is
        # load-bearing rather than tidy: this branch is the stop, and a stale
        # list left in the state would have `route_after_guard` send the run
        # back to the model to be stopped again.
        return {
            "approved_reads": [],
            "pending_write": None,
            "pending_writes": [],
            "pending_workflow": None,
            "refusals": [],
            "messages": [
                _refusal(call, "Enough looking; answer from what you already have.")
                for call in calls
            ],
        }

    reads: list[dict[str, Any]] = []
    writes: list[dict[str, Any]] = []
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

        raw_args = call.get("args") or {}
        # Check the unparsed payload too. Pydantic models ignore unknown keys by
        # default; without this, adding ``buffer_sen`` to an otherwise valid
        # call would be silently discarded before policy could see it.
        blocked = await refusal_for(context.session, context.user, name, raw_args)
        if blocked is not None:
            refusals.append(blocked)
            responses.append(_refusal(call, blocked))
            log.info(
                "butler.node guard refused thread_id=%s tool=%s reason=%s",
                context.thread_id,
                name,
                blocked,
            )
            events.emit(runtime, events.THINKING, text="That one is off limits")
            continue

        try:
            args = spec.args_model.model_validate(raw_args)
        except ValidationError as exc:
            reason = f"{name} was called with arguments it cannot accept: {exc.errors()}"
            refusals.append(reason)
            responses.append(_refusal(call, reason))
            log.info(
                "butler.node guard refused thread_id=%s tool=%s reason=%s",
                context.thread_id,
                name,
                reason,
            )
            continue

        # Protected resources are refused whatever the tier, and before anything runs.
        blocked = await refusal_for(
            context.session, context.user, name, args.model_dump(mode="json")
        )
        if blocked is not None:
            refusals.append(blocked)
            responses.append(_refusal(call, blocked))
            log.info(
                "butler.node guard refused thread_id=%s tool=%s reason=%s",
                context.thread_id,
                name,
                blocked,
            )
            events.emit(runtime, events.THINKING, text="That one is off limits")
            continue

        permitted = {
            "id": call.get("id", ""),
            "name": name,
            "args": args.model_dump(mode="json"),
        }
        if spec.is_workflow:
            if workflow is None and not writes:
                workflow = permitted
            else:
                reason = "One financial workflow at a time."
                refusals.append(reason)
                responses.append(_refusal(call, reason))
        elif spec.is_write:
            if workflow is None:
                writes.append(permitted)
            else:
                reason = "A financial workflow and direct changes cannot share one approval."
                refusals.append(reason)
                responses.append(_refusal(call, reason))
        else:
            reads.append(permitted)

    # Reads used to be turned away whenever a workflow was proposed beside
    # them, on the grounds that a specialist measures its own figures and a
    # read beside it would duplicate them. Duplication was never the cost: the
    # panel de-duplicates rows, and the specialist's own numbers still win
    # because it is the one that computed them. The cost was the question. "How
    # are my goals doing, and where should I eat?" is two things, the second is
    # a workflow, and refusing the first meant half the question came back
    # unanswered with nothing on screen saying so. So they run together — the
    # reads first, then the handoff, which `route_after_tools` already does.

    log.info(
        "butler.node guard permitted thread_id=%s reads=%s writes=%s workflow=%s refusals=%s",
        context.thread_id,
        [call["name"] for call in reads],
        [call["name"] for call in writes],
        workflow["name"] if workflow else None,
        len(refusals),
    )
    return {
        "approved_reads": reads,
        "pending_write": writes[0]
        if len(writes) == 1
        else ({"id": "change_set", "name": "change_set", "changes": writes} if writes else None),
        "pending_writes": writes,
        "pending_workflow": workflow,
        "refusals": refusals,
        "messages": responses,
    }


def route_after_guard(state: ButlerState) -> str:
    # Reads first, and the order is the whole of how a read runs beside a
    # workflow or a write: `tools` executes them and then routes on to whatever
    # is still pending, so the specialist runs with the parent's lookups already
    # done and an approval card is raised with its evidence already gathered.
    if state.get("approved_reads"):
        return "tools"
    if state.get("pending_workflow"):
        return "workflow"
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
    # ``just_talk`` is the explicit end to a conversational turn. It gives the
    # composer permission to speak warmly without evidence, and there is no
    # reason to spend a second model pass deciding whether a greeting needs a
    # balance after all.
    if "just_talk" in (state.get("tools_used") or []):
        return "compose"
    if state.get("pending_workflow"):
        return "workflow"
    if state.get("pending_write"):
        return "approval"
    return "agent"
