"""The Butler's graph.

    START
      → load_context
      → agent → insist  ⇄  guard  →  tools          (reads; on to compose)
                           guard  →  approval       (ordinary writes; interrupt())
                           guard  →  goal_workflow  (typed Goal subgraph)
                           guard  →  agent          (all refused, nothing ran; once)
      → compose (ordinary turns; Goal already composed its own response)
      → extract_memory
      → END

The shape is the argument. Reads answer straight through — only a refusal is
worth a second pass — writes leave the loop, and the only path from a write tool
to the database runs through a user's decision.

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
from kira.agent.nodes.execute import tools
from kira.agent.nodes.goal import goal_workflow
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
    builder.add_node("goal_workflow", goal_workflow)
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
            "workflow": "goal_workflow",
            "compose": "compose",
            "agent": "agent",
        },
    )
    # A batch holding both reads and a write executes the reads first, then
    # stops at the write — so the approval card is asked with its evidence
    # already gathered. Reads that ran cleanly go straight to the answer; only a
    # refusal is worth handing back to the model.
    builder.add_conditional_edges(
        "tools",
        route_after_tools,
        {
            "approval": "approval",
            "workflow": "goal_workflow",
            "agent": "agent",
            "compose": "compose",
        },
    )
    # The Goal subgraph already composed the authoritative turn.
    # The ordinary composer would spend a third LLM call; generic memory
    # extraction would also misclassify "I want RM... for a goal" as a durable
    # preference when it is already represented by the Goal domain.
    builder.add_edge("goal_workflow", END)
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
