"""tools — read handlers only, and the place evidence is collected.

A write handler is never invoked from here. The evidence rows gathered are the
exact rows the executed tools returned, which is what makes the "What I used"
panel an artefact of the run rather than a claim about it.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime

from kira.agent import events
from kira.agent.resources import tool_context
from kira.agent.state import ButlerContext, ButlerState
from kira.agent.tools import REGISTRY

log = logging.getLogger("uvicorn.error.kira.butler")


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


async def tools(state: ButlerState, runtime: Runtime[ButlerContext]) -> dict:
    permitted = state.get("approved_reads") or []
    if not permitted:
        return {"approved_reads": []}

    context = await tool_context(runtime, state.get("attachment"))
    responses: list[ToolMessage] = []
    evidence: list[list[str]] = []
    used: list[str] = []

    for call in permitted:
        spec = REGISTRY.get(call["name"])
        if spec is None or spec.is_write or spec.is_workflow:  # pragma: no cover
            continue
        events.emit(
            runtime, events.TOOL, tool=spec.name, module=spec.module, label=spec.human_label()
        )
        try:
            result = await spec.handler(context, spec.args_model.model_validate(call["args"]))
        except Exception as exc:
            log.exception(
                "butler.node tools failed thread_id=%s tool=%s",
                runtime.context.thread_id,
                spec.name,
            )
            responses.append(
                ToolMessage(
                    content=_json({"failed": True, "reason": str(exc)}),
                    name=spec.name,
                    tool_call_id=call["id"],
                    status="error",
                )
            )
            continue

        responses.append(
            ToolMessage(content=_json(result.value), name=spec.name, tool_call_id=call["id"])
        )
        used.append(spec.name)
        log.info(
            "butler.node tools finished thread_id=%s tool=%s evidence_rows=%s",
            runtime.context.thread_id,
            spec.name,
            len(result.evidence),
        )
        if spec.is_ui and isinstance(result.value, dict) and result.value.get("app_action"):
            events.emit(runtime, events.APP_ACTION, **result.value["app_action"])
        if (
            spec.name == "recommend_part_time_jobs"
            and isinstance(result.value, dict)
            and result.value.get("status") == "available"
            and isinstance(result.value.get("goal_id"), str)
        ):
            # This is emitted by the successful, persisted recommendation tool
            # rather than requested from the model. A Butler turn therefore
            # triggers the same ready notice as the Goal Planner page.
            events.emit(
                runtime,
                events.GOAL_RECOMMENDATION_READY,
                goal_id=result.value["goal_id"],
                goal_name=result.value.get("goal_name", ""),
            )
        for row in result.evidence:
            pair = row.as_pair()
            if pair not in evidence:
                evidence.append(pair)

    if evidence:
        events.emit(runtime, events.EVIDENCE, rows=evidence)

    return {
        "messages": responses,
        "evidence": (state.get("evidence") or []) + evidence,
        "tools_used": (state.get("tools_used") or []) + used,
        "approved_reads": [],
    }
