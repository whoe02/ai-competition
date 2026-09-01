"""Running one turn of the Butler, with or without a stream attached.

Both entry points — a new message, and a decision on an approval — go through
here, so the API layer never touches LangGraph directly.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from kira.agent import events
from kira.agent.graph import get_graph, graph_thread_id
from kira.agent.state import ButlerContext, initial_state
from kira.db.models import ButlerThread, User

ModelFactory = Callable[..., Any]


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
    goal_llm_calls: int = 0


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


async def _collect(graph, payload, config, context) -> AsyncIterator[dict[str, Any]]:
    async for event in graph.astream(
        payload, config=config, context=context, stream_mode="custom"
    ):
        yield event


async def _result(graph, config) -> TurnResult:
    state = await graph.aget_state(config)
    values = state.values or {}
    interrupts = getattr(state, "interrupts", ()) or ()
    approval = (
        dict(interrupts[0].value)
        if interrupts
        else values.get("pending_approval")
    )
    return TurnResult(
        answer=values.get("answer") or (PROPOSAL_LEAD if approval else ""),
        evidence=list(values.get("evidence") or []),
        tools_used=list(values.get("tools_used") or []),
        approval=approval,
        applied=values.get("applied"),
        learned=list(values.get("learned") or []),
        goal_llm_calls=values.get("goal_llm_calls", 0),
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

    try:
        async for event in _collect(graph, payload, config, context):
            yield event
    except Exception as exc:
        yield {"type": events.ERROR, "message": str(exc)}
        return

    result = await _result(graph, config)
    yield {
        "type": events.DONE,
        "answer": result.answer,
        "evidence": result.evidence,
        "tools_used": result.tools_used,
        "approval": result.approval,
        "learned": result.learned,
        "llm_calls": result.goal_llm_calls,
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

    async for _ in _collect(graph, payload, config, context):
        pass
    return await _result(graph, config)


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
    async for _ in _collect(graph, Command(resume=decision), config, context):
        pass
    return await _result(graph, config)


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
    try:
        async for event in _collect(graph, Command(resume=decision), config, context):
            yield event
    except Exception as exc:
        yield {"type": events.ERROR, "message": str(exc)}
        return
    result = await _result(graph, config)
    yield {
        "type": events.DONE,
        "answer": result.answer,
        "evidence": result.evidence,
        "tools_used": result.tools_used,
        "approval": None,
        "applied": result.applied,
    }
