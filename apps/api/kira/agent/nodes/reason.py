"""agent — the model bound to the registry's tools.

This turn never streams: DashScope's compatibility mode forbids `tools` with
`stream=True`, and a turn that emits tool calls rather than prose has nothing
worth streaming anyway.
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.runtime import Runtime

from kira.agent import events, prompt
from kira.agent.llm import OfflineChatModel, _last_human, get_chat_model, route_for
from kira.agent.state import ButlerContext, ButlerState
from kira.agent.tools import REGISTRY
from kira.config import get_settings

log = logging.getLogger("uvicorn.error.kira.butler")


def _model(runtime: Runtime[ButlerContext], attachment, history):
    factory = runtime.context.model_factory
    if factory is not None:
        return factory(streaming=False, attachment=attachment, history=history)
    return get_chat_model(
        streaming=False,
        attachment=attachment,
        history=history,
        # Choosing is a classification. Two identical questions that pick
        # different tools is not variety, it is the thing an eval cannot hold
        # still long enough to measure.
        temperature=get_settings().butler_reasoning_temperature,
    )


async def agent(state: ButlerState, runtime: Runtime[ButlerContext]) -> dict:
    attachment = state.get("attachment")
    # Handed to the model as well as pasted into the prompt. Online it is read
    # there; offline it is what tells a bare "what about korean then" that the
    # turn before it was about where to eat.
    history = state.get("history_block", "")
    system = SystemMessage(
        prompt.reasoning_prompt(
            context=state.get("context_block", ""),
            memory=state.get("memory_block", ""),
            history=history,
            attachment=state.get("attachment_block", ""),
            tool_names=tuple(spec.name for spec in REGISTRY),
            workflow_names=tuple(spec.name for spec in REGISTRY.workflows()),
        )
    )
    conversation = [system, *state.get("messages", [])]

    iteration = state.get("iterations", 0) + 1
    log.info(
        "butler.node agent started thread_id=%s iteration=%s", runtime.context.thread_id, iteration
    )
    model = _model(runtime, attachment, history).bind_tools(REGISTRY.schemas())
    try:
        reply = await model.ainvoke(conversation)
    except Exception as exc:  # the venue's network is not the user's problem
        log.warning(
            "butler.node agent model_failed thread_id=%s iteration=%s fallback=offline error=%s",
            runtime.context.thread_id,
            iteration,
            exc,
        )
        events.emit(runtime, events.THINKING, text="Working from what is already here")
        fallback = OfflineChatModel(attachment=attachment, history=history).bind_tools(
            REGISTRY.schemas()
        )
        reply = await fallback.ainvoke(conversation)
        reply.response_metadata["kira_fallback"] = str(exc)

    # Some online models answer a goal follow-up in prose instead of continuing
    # the typed workflow. The user has supplied the missing fields, so leaving
    # the turn tool-less would discard the conversation and trigger the compose
    # node's honest no-results response. Recover only for the deterministic goal
    # route; ordinary conversation should remain entirely model-driven.
    if isinstance(reply, AIMessage) and not reply.tool_calls:
        route = route_for(_last_human(conversation), attachment, history)
        if route.name == "goal_workflow":
            fallback = OfflineChatModel(attachment=attachment, history=history).bind_tools(
                REGISTRY.schemas()
            )
            reply = await fallback.ainvoke(conversation)

    if not isinstance(reply, AIMessage):  # pragma: no cover - defensive
        reply = AIMessage(content=str(reply))
    log.info(
        "butler.node agent finished thread_id=%s iteration=%s proposed_tools=%s",
        runtime.context.thread_id,
        iteration,
        [call.get("name") for call in (reply.tool_calls or [])],
    )
    return {"messages": [reply], "iterations": iteration}
