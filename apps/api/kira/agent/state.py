"""The graph's state, and the run-scoped context that is deliberately not in it.

`ButlerState` is checkpointed, so everything in it is JSON. The session, the
user row and the loaded snapshot are run-scoped and live in `ButlerContext`,
which LangGraph passes to nodes without persisting.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import User


class ButlerState(TypedDict, total=False):
    """Everything the graph carries between nodes."""

    messages: Annotated[list[AnyMessage], add_messages]
    # Rendered once by load_context and pasted into the system prompt.
    context_block: str
    memory_block: str
    history_block: str
    attachment_block: str
    memory_ids: list[str]
    # Evidence rows as executed tools returned them: [[label, value], …].
    # compose renders the panel from this and nothing else.
    evidence: list[list[str]]
    tools_used: list[str]
    iterations: int
    attachment: dict[str, Any] | None
    # Set by the guard when a call is refused, and fed back to the model.
    refusals: list[str]
    # What the guard permitted this turn: reads to execute, and at most one
    # write, which only the approval path can run.
    approved_reads: list[dict[str, Any]]
    pending_write: dict[str, Any] | None
    # A typed handoff to a specialised subgraph. It is validated by the same
    # guard as a tool call, but never executed as a free-form model tool.
    pending_workflow: dict[str, Any] | None
    # Set by the approval node, then read by the API to build the response.
    pending_approval: dict[str, Any] | None
    # Set by the approval node once a write has actually run.
    applied: dict[str, Any] | None
    goal_llm_calls: int
    # Facts extract_memory kept from this turn.
    learned: list[str]
    answer: str


@dataclass(frozen=True, slots=True)
class ButlerContext:
    """Run-scoped handles. Never checkpointed, never serialised."""

    session: AsyncSession
    user: User
    today: date
    thread_id: uuid.UUID
    # The user's message this run is answering, so an extracted fact can point
    # back at the sentence it came from.
    source_message_id: uuid.UUID | None = None
    # Supplied by the caller so a test can drive the graph with a fake model.
    model_factory: Callable[..., Any] | None = None
    # Run-scoped scratch space for the loaded snapshot and dashboard. It lives
    # here rather than in the state because neither is JSON, and the state is
    # checkpointed. Mutable by design; one dict per run.
    cache: dict[str, Any] = field(default_factory=dict)


def initial_state(
    *,
    context_block: str = "",
    memory_block: str = "",
    attachment: dict[str, Any] | None = None,
) -> ButlerState:
    return ButlerState(
        messages=[],
        context_block=context_block,
        memory_block=memory_block,
        history_block="",
        attachment_block="",
        memory_ids=[],
        evidence=[],
        tools_used=[],
        iterations=0,
        attachment=attachment,
        refusals=[],
        approved_reads=[],
        pending_write=None,
        pending_workflow=None,
        pending_approval=None,
        applied=None,
        goal_llm_calls=0,
        answer="",
    )
