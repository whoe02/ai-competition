"""The Butler's graph.

    START
      → load_context
      → agent → insist  ⇄  guard  →  tools      → agent   (reads, then read again)
                           guard  →  delegate   → agent   (a specialist reports)
                           guard  →  approval           (writes; interrupt())
                           guard  →  agent              (all refused, nothing ran)
                           guard  →  compose            (nothing left to ask)
      → compose
      → extract_memory
      → END

The shape is the argument. Every result comes back to the model, so a turn can
read a figure, notice what it implies and go and check that too — which is the
whole of what "chain reasoning" means here. What stops it circling is not the
graph but the guard: an iteration cap, and a wall-clock budget that ends the
looking and sends the turn to compose whatever it has.

Writes still leave the loop, and the only path from a write tool to the
database still runs through a user answering a card. A specialist that raises
its own card ends the turn where it stands, because the card is the answer.

`insist` is the one place a tool call is made by the app rather than proposed
by the model, and it is deliberately upstream of the guard: a call this app
adds is checked exactly as hard as one the model asked for.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from kira.agent.nodes.approve import approval
from kira.agent.nodes.compose import compose
from kira.agent.nodes.context import load_context
from kira.agent.nodes.delegate import delegate, route_after_delegate
from kira.agent.nodes.execute import tools
from kira.agent.nodes.guard import guard, route_after_guard, route_after_tools
from kira.agent.nodes.insist import insist
from kira.agent.nodes.memory import extract_memory
from kira.agent.nodes.reason import agent
from kira.agent.state import ButlerContext, ButlerState


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    builder = StateGraph(ButlerState, context_schema=ButlerContext)

    builder.add_node("load_context", load_context)
    builder.add_node("agent", agent)
    builder.add_node("insist", insist)
    builder.add_node("guard", guard)
    builder.add_node("delegate", delegate)
    builder.add_node("tools", tools)
    builder.add_node("approval", approval)
    builder.add_node("compose", compose)
    builder.add_node("extract_memory", extract_memory)

    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "agent")
    builder.add_edge("agent", "insist")
    builder.add_edge("insist", "guard")
    # Back to `agent` is the fourth way out, and the narrow one: every call
    # this pass proposed was refused and nothing has run, so the turn would
    # otherwise compose from no evidence. See `route_after_guard`.
    builder.add_conditional_edges(
        "guard",
        route_after_guard,
        {
            "tools": "tools",
            "approval": "approval",
            "workflow": "delegate",
            "compose": "compose",
            "agent": "agent",
        },
    )
    # A batch holding both reads and a write executes the reads first, then
    # stops at the write — so the approval card is asked with its evidence
    # already gathered. Everything else goes back to the model: results are what
    # a second pass is for, and the guard is what stops there being a tenth.
    builder.add_conditional_edges(
        "tools",
        route_after_tools,
        {
            "approval": "approval",
            "workflow": "delegate",
            "agent": "agent",
        },
    )
    # A specialist reports and the Butler reads the report — except where it
    # raised an approval card, which is a question put to the user and ends the
    # turn. Composing over a proposal the user has not answered yet would be a
    # second opinion about a decision that has not been made.
    builder.add_conditional_edges(
        "delegate",
        route_after_delegate,
        {"agent": "agent", "end": END},
    )
    builder.add_edge("approval", "compose")
    builder.add_edge("compose", "extract_memory")
    builder.add_edge("extract_memory", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())


@lru_cache
def _memory_graph():
    """One in-process graph, used when no Postgres checkpointer is configured."""
    return build_graph()


_graph: Any = None
_saver_context: Any = None


def get_graph():
    """The compiled graph for this process."""
    return _graph if _graph is not None else _memory_graph()


async def setup_checkpointer(dsn: str) -> BaseCheckpointSaver | None:
    """Create LangGraph's own tables and compile the graph against them.

    These tables are LangGraph's schema, not ours, so they are created by an
    idempotent `setup()` at startup rather than by an Alembic migration.
    """
    global _graph, _saver_context
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from kira.agent.goal_graph.graph import checkpoint_serializer

    _saver_context = AsyncPostgresSaver.from_conn_string(dsn, serde=checkpoint_serializer())
    saver = await _saver_context.__aenter__()
    await saver.setup()
    _graph = build_graph(saver)
    from kira.agent.goal_graph.graph import configure_goal_graph

    configure_goal_graph(saver)
    return saver


async def close_checkpointer() -> None:
    """Release the checkpointer's own psycopg pool at shutdown."""
    global _graph, _saver_context
    if _saver_context is not None:
        await _saver_context.__aexit__(None, None, None)
        _saver_context = None
    _graph = None
    from kira.agent.goal_graph.graph import configure_goal_graph

    configure_goal_graph(None)


def graph_thread_id(thread_id: uuid.UUID, message_id: uuid.UUID) -> str:
    """One checkpointed run per turn, so an approval resumes exactly its own run."""
    return f"{thread_id}:{message_id}"
