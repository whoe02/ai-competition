"""extract_memory — the one write that does not wait for approval.

Pausing to approve every remembered fact would make memory unusable, so
passive extraction writes on its own. The compensating controls are narrow
capability — this node can write to `butler_memories` and nothing else — and
full visibility: every fact is listed, correctable and deletable in the UI.
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from kira.agent import events
from kira.agent.extract import candidates
from kira.agent.state import ButlerContext, ButlerState
from kira.services.butler_memory import InvalidMemory, remember, touch


def _last_human(state: ButlerState) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


async def extract_memory(state: ButlerState, runtime: Runtime[ButlerContext]) -> dict:
    context = runtime.context

    # Facts the answer actually leaned on stay in the working set; the rest
    # age out, so retrieval converges on what matters to this user.
    answer = state.get("answer", "")
    used = [
        memory.id for memory in (context.cache.get("memories") or ()) if _cited(memory.fact, answer)
    ]
    if used:
        await touch(context.session, context.user, used)

    learned: list[str] = []
    for candidate in candidates(_last_human(state)):
        try:
            view = await remember(
                context.session,
                context.user,
                kind=candidate.kind,
                subject=candidate.subject,
                fact=candidate.fact,
                confidence=candidate.confidence,
                source_message_id=context.source_message_id,
            )
        except InvalidMemory:
            continue
        learned.append(view.fact)

    if learned:
        events.emit(runtime, events.THINKING, text="Noting that for next time")
    return {"learned": learned}


STOPWORDS = frozenset(
    "the a an and or of to in on for with is are was were i my me you your it that this "
    "not never always about over under from at as by but so if then than".split()
)


def _salient(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z]{4,}", text.lower()) if word not in STOPWORDS}


def _cited(fact: str, answer: str) -> bool:
    """Did the answer stay in this fact's territory? Word overlap, nothing cleverer."""
    if not answer:
        return False
    words = _salient(fact)
    return bool(words) and len(words & _salient(answer)) >= 2
