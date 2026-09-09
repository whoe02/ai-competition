"""tools — read handlers only, and the place evidence is collected.

A write handler is never invoked from here. The evidence rows gathered are the
exact rows the executed tools returned, which is what makes the "What I used"
panel an artefact of the run rather than a claim about it.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime

from kira.agent import events
from kira.agent.resources import tool_context
from kira.agent.state import ButlerContext, ButlerState
from kira.agent.tools import REGISTRY


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
        if spec.is_ui and isinstance(result.value, dict) and result.value.get("app_action"):
            events.emit(runtime, events.APP_ACTION, **result.value["app_action"])
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
