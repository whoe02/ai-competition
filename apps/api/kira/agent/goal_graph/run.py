"""Start and resume goal graph runs without exposing LangGraph to the API."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from kira.agent.goal_graph.graph import get_goal_graph
from kira.agent.goal_graph.schemas import GoalIntent
from kira.agent.goal_graph.state import (
    GoalGraphContext,
    GoalGraphState,
    initial_goal_state,
)
from kira.db.models import User


@dataclass(frozen=True, slots=True)
class GoalRunResult:
    request_id: uuid.UUID
    state: GoalGraphState
    approval: dict[str, Any] | None

    @property
    def final_response(self) -> str:
        return self.state.get("final_response", "")

    @property
    def llm_calls(self) -> int:
        return self.state.get("llm_calls", 0)


def goal_graph_thread_id(thread_id: uuid.UUID, request_id: uuid.UUID) -> str:
    return f"goal:{thread_id}:{request_id}"


def _config(thread_id: uuid.UUID, request_id: uuid.UUID) -> dict[str, Any]:
    return {"configurable": {"thread_id": goal_graph_thread_id(thread_id, request_id)}}


def _context(
    session: AsyncSession,
    user: User,
    thread_id: uuid.UUID,
    as_of_date: date,
    model_factory,
    structured_intent,
    explain: bool,
) -> GoalGraphContext:
    return GoalGraphContext(
        session=session,
        user=user,
        as_of_utc=datetime.combine(as_of_date, time.min, tzinfo=UTC),
        thread_id=thread_id,
        model_factory=model_factory,
        structured_intent=structured_intent,
        explain=explain,
    )


async def _result(graph, config, request_id: uuid.UUID) -> GoalRunResult:
    snapshot = await graph.aget_state(config)
    state = GoalGraphState(**(snapshot.values or {}))
    interrupts = getattr(snapshot, "interrupts", ()) or ()
    approval = dict(interrupts[0].value) if interrupts else None
    return GoalRunResult(request_id=request_id, state=state, approval=approval)


async def run_goal_request(
    session: AsyncSession,
    user: User,
    *,
    thread_id: uuid.UUID,
    message: str,
    as_of_date: date,
    request_id: uuid.UUID | None = None,
    structured_intent: GoalIntent | dict[str, Any] | None = None,
    model_factory=None,
    explain: bool = True,
) -> GoalRunResult:
    request_id = request_id or uuid.uuid4()
    graph = get_goal_graph()
    config = _config(thread_id, request_id)
    context = _context(
        session,
        user,
        thread_id,
        as_of_date,
        model_factory,
        structured_intent,
        explain,
    )
    payload = initial_goal_state(
        request_id=request_id,
        thread_id=thread_id,
        user_id=user.id,
        message=message,
    )
    await graph.ainvoke(payload, config=config, context=context)
    await session.commit()
    return await _result(graph, config, request_id)


async def resume_goal_run(
    session: AsyncSession,
    user: User,
    *,
    thread_id: uuid.UUID,
    request_id: uuid.UUID,
    decision: dict[str, Any],
    as_of_date: date,
    model_factory=None,
    explain: bool = True,
) -> GoalRunResult:
    graph = get_goal_graph()
    config = _config(thread_id, request_id)
    context = _context(
        session,
        user,
        thread_id,
        as_of_date,
        model_factory,
        None,
        explain,
    )
    await graph.ainvoke(Command(resume=decision), config=config, context=context)
    await session.commit()
    return await _result(graph, config, request_id)
