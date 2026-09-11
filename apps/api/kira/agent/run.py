"""Running one turn of the Butler, with or without a stream attached.

Both entry points — a new message, and a decision on an approval — go through
here, so the API layer never touches LangGraph directly.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from kira.agent import events
from kira.agent.graph import get_graph, graph_thread_id
from kira.agent.state import ButlerContext, initial_state
from kira.db.models import ButlerThread, User

ModelFactory = Callable[..., Any]
log = logging.getLogger("uvicorn.error.kira.butler")


# What Kira says while a proposal is on screen. It is fixed rather than
# generated: the model never gets to soften the fact that nothing has happened.
PROPOSAL_LEAD = (
    "Here is the change I would make.\n"
    "Nothing has happened yet — it is yours to approve, edit or reject."
)


@dataclass(slots=True)
class TurnResult:
    """What one turn produced, whether or not anyone was watching it stream."""

    answer: str = ""
    evidence: list[list[str]] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    approval: dict[str, Any] | None = None
    applied: dict[str, Any] | None = None
    learned: list[str] = field(default_factory=list)
    # The Butler's own reasoning passes, and the calls its specialists made.
    # Kept apart because they answer different questions: one is how long the
    # turn thought for, the other is what delegation cost.
    iterations: int = 0
    child_llm_calls: int = 0
    work_recommendations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def llm_calls(self) -> int:
        return self.iterations + self.child_llm_calls


def _context(
    session: AsyncSession,
    user: User,
    thread: ButlerThread,
    today: date,
    source_message_id: uuid.UUID | None,
    model_factory: ModelFactory | None,
) -> ButlerContext:
    return ButlerContext(
        session=session,
        user=user,
        today=today,
        thread_id=thread.id,
        source_message_id=source_message_id,
        model_factory=model_factory,
    )


def _config(graph_thread: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": graph_thread}}


def _work_recommendations(messages: list[Any]) -> list[dict[str, Any]]:
    """Return the latest successful saved work result for each goal.

    ToolMessages are the post-validation, provider-grounded records. Reading
    them here keeps Butler's rich rendering and its goal-page notification in
    lockstep without trusting prose generated after the tool ran.
    """
    by_goal: dict[str, dict[str, Any]] = {}
    for message in messages:
        if not isinstance(message, ToolMessage) or message.name != "recommend_part_time_jobs":
            continue
        try:
            value = json.loads(message.content) if isinstance(message.content, str) else None
        except json.JSONDecodeError:
            continue
        if (
            not isinstance(value, dict)
            or value.get("status") != "available"
            or not isinstance(value.get("goal_id"), str)
            or not isinstance(value.get("recommendations"), list)
        ):
            continue
        by_goal[value["goal_id"]] = value
    return list(by_goal.values())


def _debug_value(value: Any) -> str:
    """Keep a complete debug value on one terminal-log line."""
    return json.dumps(value, ensure_ascii=False, default=str)


def _log_user_input(thread: ButlerThread, message_id: uuid.UUID, text: str, mode: str) -> None:
    log.info(
        "butler.input mode=%s thread_id=%s message_id=%s user_input=%s",
        mode,
        thread.id,
        message_id,
        _debug_value(text),
    )


def _log_assistant_output(
    thread: ButlerThread, identifier: str | uuid.UUID, result: TurnResult, mode: str
) -> None:
    log.info(
        "butler.output mode=%s thread_id=%s turn_id=%s assistant_output=%s",
        mode,
        thread.id,
        identifier,
        _debug_value(result.answer),
    )


async def _collect(graph, payload, config, context) -> AsyncIterator[dict[str, Any]]:
    async for event in graph.astream(payload, config=config, context=context, stream_mode="custom"):
        yield event


async def _result(graph, config) -> TurnResult:
    state = await graph.aget_state(config)
    values = state.values or {}
    interrupts = getattr(state, "interrupts", ()) or ()
    approval = dict(interrupts[0].value) if interrupts else values.get("pending_approval")
    return TurnResult(
        answer=values.get("answer") or (PROPOSAL_LEAD if approval else ""),
        evidence=list(values.get("evidence") or []),
        tools_used=list(values.get("tools_used") or []),
        approval=approval,
        applied=values.get("applied"),
        learned=list(values.get("learned") or []),
        iterations=values.get("iterations", 0),
        child_llm_calls=values.get("child_llm_calls", 0),
        work_recommendations=_work_recommendations(list(values.get("messages") or [])),
    )


async def stream_turn(
    session: AsyncSession,
    user: User,
    thread: ButlerThread,
    *,
    text: str,
    message_id: uuid.UUID,
    today: date,
    attachment: dict[str, Any] | None = None,
    model_factory: ModelFactory | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield the turn's events, then one terminal `done` carrying the result."""
    graph = get_graph()
    config = _config(graph_thread_id(thread.id, message_id))
    context = _context(session, user, thread, today, message_id, model_factory)
    payload = initial_state(attachment=attachment)
    payload["messages"] = [HumanMessage(content=text)]
    log.info(
        "butler.turn started mode=stream thread_id=%s message_id=%s attachment=%s",
        thread.id,
        message_id,
        bool(attachment),
    )
    _log_user_input(thread, message_id, text, "stream")

    try:
        async for event in _collect(graph, payload, config, context):
            yield event
    except Exception as exc:
        log.exception(
            "butler.turn failed mode=stream thread_id=%s message_id=%s", thread.id, message_id
        )
        yield {"type": events.ERROR, "message": str(exc)}
        return

    result = await _result(graph, config)
    log.info(
        "butler.turn finished mode=stream thread_id=%s message_id=%s "
        "iterations=%s child_llm_calls=%s tools=%s approval=%s",
        thread.id,
        message_id,
        result.iterations,
        result.child_llm_calls,
        result.tools_used,
        bool(result.approval),
    )
    _log_assistant_output(thread, message_id, result, "stream")
    yield {
        "type": events.DONE,
        "answer": result.answer,
        "evidence": result.evidence,
        "tools_used": result.tools_used,
        "approval": result.approval,
        "learned": result.learned,
        "llm_calls": result.llm_calls,
        "work_recommendations": result.work_recommendations,
    }


async def stream_interrupted_turn(
    session: AsyncSession,
    user: User,
    thread: ButlerThread,
    *,
    message_id: uuid.UUID,
    today: date,
    model_factory: ModelFactory | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Continue the checkpoint belonging to an unanswered user message.

    A new payload would replay the request and could repeat a goal workflow or
    another side effect.  ``None`` tells LangGraph to continue the durable
    checkpoint instead.  A checkpoint that already reached END is useful too:
    the graph result may have finished immediately before the API process died,
    in which case we only need to publish and persist that existing result.
    """
    graph = get_graph()
    graph_thread = graph_thread_id(thread.id, message_id)
    config = _config(graph_thread)
    context = _context(session, user, thread, today, message_id, model_factory)
    snapshot = await graph.aget_state(config)
    if not snapshot.values:
        yield {
            "type": events.ERROR,
            "message": (
                "This answer cannot be resumed because its saved workflow is no longer "
                "available. Please send the request again."
            ),
        }
        return

    log.info(
        "butler.turn resume started mode=stream thread_id=%s message_id=%s next=%s",
        thread.id,
        message_id,
        list(snapshot.next),
    )
    try:
        if snapshot.next:
            async for event in _collect(graph, None, config, context):
                yield event
    except Exception as exc:
        log.exception(
            "butler.turn resume failed mode=stream thread_id=%s message_id=%s",
            thread.id,
            message_id,
        )
        yield {"type": events.ERROR, "message": str(exc)}
        return

    result = await _result(graph, config)
    log.info(
        "butler.turn resume finished mode=stream thread_id=%s message_id=%s "
        "iterations=%s child_llm_calls=%s tools=%s approval=%s",
        thread.id,
        message_id,
        result.iterations,
        result.child_llm_calls,
        result.tools_used,
        bool(result.approval),
    )
    _log_assistant_output(thread, message_id, result, "interrupted-stream")
    yield {
        "type": events.DONE,
        "answer": result.answer,
        "evidence": result.evidence,
        "tools_used": result.tools_used,
        "approval": result.approval,
        "applied": result.applied,
        "learned": result.learned,
        "llm_calls": result.llm_calls,
        "work_recommendations": result.work_recommendations,
    }


async def run_turn(
    session: AsyncSession,
    user: User,
    thread: ButlerThread,
    *,
    text: str,
    message_id: uuid.UUID | None = None,
    today: date,
    attachment: dict[str, Any] | None = None,
    model_factory: ModelFactory | None = None,
) -> TurnResult:
    """The same turn, collected rather than streamed."""
    message_id = message_id or uuid.uuid4()
    graph = get_graph()
    config = _config(graph_thread_id(thread.id, message_id))
    context = _context(session, user, thread, today, message_id, model_factory)
    payload = initial_state(attachment=attachment)
    payload["messages"] = [HumanMessage(content=text)]
    log.info(
        "butler.turn started mode=collected thread_id=%s message_id=%s attachment=%s",
        thread.id,
        message_id,
        bool(attachment),
    )
    _log_user_input(thread, message_id, text, "collected")

    try:
        async for _ in _collect(graph, payload, config, context):
            pass
        result = await _result(graph, config)
    except Exception:
        log.exception(
            "butler.turn failed mode=collected thread_id=%s message_id=%s", thread.id, message_id
        )
        raise
    log.info(
        "butler.turn finished mode=collected thread_id=%s message_id=%s "
        "iterations=%s child_llm_calls=%s tools=%s approval=%s",
        thread.id,
        message_id,
        result.iterations,
        result.child_llm_calls,
        result.tools_used,
        bool(result.approval),
    )
    _log_assistant_output(thread, message_id, result, "collected")
    return result


async def resume_approval(
    session: AsyncSession,
    user: User,
    thread: ButlerThread,
    *,
    graph_thread: str,
    decision: dict[str, Any],
    today: date,
    model_factory: ModelFactory | None = None,
) -> TurnResult:
    """Hand the user's decision back to the paused run and let it finish."""
    graph = get_graph()
    config = _config(graph_thread)
    context = _context(session, user, thread, today, None, model_factory)
    log.info(
        "butler.approval resume started mode=collected thread_id=%s graph_thread=%s",
        thread.id,
        graph_thread,
    )
    log.info(
        "butler.approval input mode=collected thread_id=%s graph_thread=%s user_decision=%s",
        thread.id,
        graph_thread,
        _debug_value(decision),
    )
    try:
        async for _ in _collect(graph, Command(resume=decision), config, context):
            pass
        result = await _result(graph, config)
    except Exception:
        log.exception(
            "butler.approval resume failed mode=collected thread_id=%s graph_thread=%s",
            thread.id,
            graph_thread,
        )
        raise
    log.info(
        "butler.approval resume finished mode=collected thread_id=%s "
        "graph_thread=%s tools=%s approval=%s",
        thread.id,
        graph_thread,
        result.tools_used,
        bool(result.approval),
    )
    _log_assistant_output(thread, graph_thread, result, "approval-collected")
    return result


async def stream_resume(
    session: AsyncSession,
    user: User,
    thread: ButlerThread,
    *,
    graph_thread: str,
    decision: dict[str, Any],
    today: date,
    model_factory: ModelFactory | None = None,
) -> AsyncIterator[dict[str, Any]]:
    graph = get_graph()
    config = _config(graph_thread)
    context = _context(session, user, thread, today, None, model_factory)
    log.info(
        "butler.approval resume started mode=stream thread_id=%s graph_thread=%s",
        thread.id,
        graph_thread,
    )
    log.info(
        "butler.approval input mode=stream thread_id=%s graph_thread=%s user_decision=%s",
        thread.id,
        graph_thread,
        _debug_value(decision),
    )
    try:
        async for event in _collect(graph, Command(resume=decision), config, context):
            yield event
    except Exception as exc:
        log.exception(
            "butler.approval resume failed mode=stream thread_id=%s graph_thread=%s",
            thread.id,
            graph_thread,
        )
        yield {"type": events.ERROR, "message": str(exc)}
        return
    result = await _result(graph, config)
    log.info(
        "butler.approval resume finished mode=stream thread_id=%s "
        "graph_thread=%s tools=%s approval=%s",
        thread.id,
        graph_thread,
        result.tools_used,
        bool(result.approval),
    )
    _log_assistant_output(thread, graph_thread, result, "approval-stream")
    yield {
        "type": events.DONE,
        "answer": result.answer,
        "evidence": result.evidence,
        "tools_used": result.tools_used,
        # Not hardcoded to None any more, and it cannot be. A resume used to
        # run to the end of the turn no matter what, so there was never a card
        # standing when it finished. Now an applied write goes back to the
        # model, and the next thing the model proposes may be another write —
        # a second card, raised on this very stream. `done` is what the client
        # reads as "a proposal is still standing", so reporting None here would
        # emit the card mid-stream and then wipe it one event later.
        #
        # It stays None on the ordinary path: a run that reached END has no
        # interrupt, and `_result` only finds one when the graph is genuinely
        # parked on a fresh proposal.
        "approval": result.approval,
        "applied": result.applied,
    }
