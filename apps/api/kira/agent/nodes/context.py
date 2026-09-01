"""load_context — deterministic, and the reason the Butler cannot invent a number.

It calls no model. It loads the same snapshot and the same dashboard the Today
screen loads, so there is no second read path that could disagree with the app.
"""

from __future__ import annotations

import time

from langgraph.runtime import Runtime

from kira.agent import events, prompt
from kira.agent.state import ButlerContext, ButlerState
from kira.config import get_settings
from kira.services.butler_memory import list_memories
from kira.services.butler_thread import get_thread, messages
from kira.services.dashboard import today_dashboard
from kira.services.snapshot import load_snapshot

HISTORY_TURNS = 12


async def load_context(
    state: ButlerState, runtime: Runtime[ButlerContext]
) -> dict:
    context = runtime.context
    events.emit(runtime, events.THINKING, text="Reading your accounts")

    board = await today_dashboard(context.session, context.user, context.today)
    thread = await get_thread(context.session, context.user, context.thread_id)
    history = await messages(context.session, thread, limit=HISTORY_TURNS)
    remembered = await list_memories(
        context.session, context.user, limit=get_settings().butler_memory_limit
    )

    # Warmed here and handed to every tool, so no handler reads a clock or
    # widens ownership on its own.
    context.cache["board"] = board
    context.cache["memories"] = remembered
    context.cache["snapshot"] = await load_snapshot(
        context.session, context.user, context.today
    )

    return {
        "context_block": prompt.context_block(board, context.today, context.user.currency),
        "memory_block": prompt.memory_block(remembered),
        "history_block": prompt.history_block(history[:-1] if history else ()),
        "attachment_block": prompt.attachment_block(state.get("attachment")),
        "memory_ids": [str(memory.id) for memory in remembered],
        # Started here rather than in the guard, so the budget covers the
        # loading as well as the thinking. It is what the user is waiting
        # through either way.
        "started_at": time.monotonic(),
    }
