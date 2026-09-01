"""delegate — a guarded workflow call handed to the module that owns it.

This is the whole of the multi-agent machinery. A `kind="workflow"` spec names
an `agent`, the guard permits at most one per pass, and this node runs it and
puts what came back into the conversation as an ordinary `ToolMessage`. The
reasoning loop upstream cannot tell the difference between that and a tool
result, which is the point: adding a specialist adds a file and a registry
line, and no node changes.

Two things leave by a different door than a tool result would.

`evidence` goes onto the parent's panel already formatted, because the child
measured it and the Butler must not restate a figure it did not compute. And an
approval raised by the child ends the turn where it stands: a card is on screen
with the child's own sentence above it, and the Butler composing a second
opinion over the top of a proposal the user is being asked to decide is not a
better answer, it is a contradiction waiting to happen.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime

from kira.agent import events
from kira.agent.resources import tool_context
from kira.agent.state import ButlerContext, ButlerState
from kira.agent.tools import REGISTRY
from kira.agent.tools.spec import AgentContext


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def _merge(existing: list[list[str]], rows: list[list[str]]) -> list[list[str]]:
    """Append the child's rows, skipping any the parent already has."""
    merged = list(existing)
    for row in rows:
        if row not in merged:
            merged.append(row)
    return merged


def _failed(call: dict[str, Any], reason: str) -> ToolMessage:
    """A child that raised is a result, not a crash.

    It comes back as a tool result the model can read for the same reason a
    refusal does: the turn still owes the user an answer, and "the goal planner
    could not run" is one the Butler can honestly give. Swallowing it would
    leave the model's tool call unanswered, which the API rejects outright.
    """
    return ToolMessage(
        content=_json({"failed": True, "reason": reason}),
        name=call.get("name", "unknown"),
        tool_call_id=call.get("id", ""),
        status="error",
    )


async def delegate(state: ButlerState, runtime: Runtime[ButlerContext]) -> dict:
    call = state.get("pending_workflow")
    if not call:  # pragma: no cover - only reachable via the guard, which sets it
        return {"pending_workflow": None}

    spec = REGISTRY.get(call.get("name", ""))
    if spec is None or spec.agent is None:  # pragma: no cover - the guard checked both
        return {
            "pending_workflow": None,
            "messages": [_failed(call, "That specialist is not available.")],
        }

    context = runtime.context
    events.emit(
        runtime, events.TOOL, tool=spec.name, module=spec.module, label=spec.human_label()
    )

    agent_context = AgentContext(
        tools=await tool_context(runtime, state.get("attachment")),
        thread_id=context.thread_id,
        request_id=context.source_message_id or uuid.uuid4(),
        model_factory=context.model_factory,
        emit=lambda event, **data: events.emit(runtime, event, **data),
    )
    try:
        report = await spec.agent(agent_context, spec.args_model.model_validate(call["args"]))
    except Exception as exc:
        return {
            "pending_workflow": None,
            "messages": [_failed(call, str(exc))],
        }

    rows = [row.as_pair() for row in report.evidence]
    if rows:
        events.emit(runtime, events.EVIDENCE, rows=rows)

    update: dict[str, Any] = {
        "messages": [
            ToolMessage(
                content=_json(report.findings),
                name=spec.name,
                tool_call_id=call.get("id", ""),
            )
        ],
        "evidence": _merge(state.get("evidence") or [], rows),
        "tools_used": (state.get("tools_used") or []) + [spec.name],
        "reports": (state.get("reports") or []) + ([report.answer] if report.answer else []),
        "pending_workflow": None,
        "child_llm_calls": state.get("child_llm_calls", 0) + report.llm_calls,
        # `iterations` deliberately does not move here. It counts the Butler's
        # own passes, and every delegation already cost one to propose — so the
        # cap bounds repeated delegation without this node touching it, and
        # `llm_calls` does not report the same call twice.
    }

    if report.approval is not None:
        # The child's own words are the turn. Streamed here rather than left to
        # compose, because compose is not going to run.
        if report.answer:
            events.emit(runtime, events.TOKEN, text=report.answer)
        events.emit(
            runtime,
            events.APPROVAL,
            approval_id=report.approval["approval_id"],
            tool=report.approval["tool"],
            module=spec.module,
            summary=report.approval["summary"],
            args={
                "before": report.approval.get("before"),
                "after": report.approval.get("after"),
                "base_plan_version": report.approval.get("base_plan_version"),
            },
            before=report.approval.get("before"),
            after=report.approval.get("after"),
            base_plan_version=report.approval.get("base_plan_version"),
        )
        update["answer"] = report.answer
        update["pending_approval"] = report.approval

    return update


def route_after_delegate(state: ButlerState) -> str:
    """Back to the Butler, unless the specialist raised a card.

    A card is a question put to the user, and the run stops at it exactly as an
    ordinary write does. Everything else is a report, and a report is only
    useful once something reads it.
    """
    if state.get("pending_approval"):
        return "end"
    return "agent"
