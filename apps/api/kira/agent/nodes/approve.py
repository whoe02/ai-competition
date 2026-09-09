"""approval — where a proposed write stops and waits for the user.

The row is written, `interrupt()` is called, the HTTP request ends and the
graph state sits in the checkpointer. Nothing has been written to financial
state, and nothing will be until the user answers.

On resume, the arguments are validated and the policy re-checked before the
handler runs. An approval row is not a licence to execute whatever it happens
to contain.
"""

from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import ValidationError

from kira.agent import events
from kira.agent.policy import refusal_for
from kira.agent.resources import invalidate, tool_context
from kira.agent.state import ButlerContext, ButlerState
from kira.agent.tools import REGISTRY
from kira.services import butler_approvals
from kira.services.audit import ACTOR_USER, record

ACCEPT = "accept"
EDIT = "edit"
REJECT = "reject"


def _message(name: str, call_id: str, payload: dict[str, Any], failed: bool = False) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(payload, default=str),
        name=name,
        tool_call_id=call_id,
        status="error" if failed else "success",
    )


async def approval(
    state: ButlerState, runtime: Runtime[ButlerContext], config: RunnableConfig
) -> dict:
    proposed = state.get("pending_write")
    if not proposed:  # pragma: no cover - the guard routed us here
        return {"pending_write": None}

    if proposed.get("name") == "change_set":
        return await _approve_change_set(state, runtime, config, proposed)

    context = runtime.context
    spec = REGISTRY.get(proposed["name"])
    if spec is None or not spec.is_write:  # pragma: no cover - the guard checked this
        return {"pending_write": None}

    graph_thread_id = str(config.get("configurable", {}).get("thread_id", ""))
    summary = spec.summarise(spec.args_model.model_validate(proposed["args"]))
    row, proposed_now = await butler_approvals.propose(
        context.session,
        context.user,
        thread_id=context.thread_id,
        tool=spec.name,
        args=proposed["args"],
        summary=summary,
        evidence=state.get("evidence") or [],
        graph_thread_id=graph_thread_id,
        tool_call_id=proposed["id"],
    )
    # Only on the pass that raised the card. Resuming replays this node from
    # its first line, and emitting again would put the card back on screen in
    # the middle of applying the decision the user just gave -- so the next
    # click lands on a settled approval and comes back a conflict.
    if proposed_now:
        events.emit(
            runtime,
            events.APPROVAL,
            approval_id=str(row.id),
            tool=spec.name,
            module=spec.module,
            summary=summary,
            args=proposed["args"],
        )

    # The request ends here. What comes back is the user's decision.
    decision = interrupt(
        {
            "approval_id": str(row.id),
            "tool": spec.name,
            "module": spec.module,
            "summary": summary,
            "args": proposed["args"],
        }
    )
    decision = decision or {}
    action = decision.get("action", REJECT)
    if action == REJECT:
        return {
            "pending_write": None,
            "messages": [
                _message(spec.name, proposed["id"], {"applied": False, "reason": "rejected"})
            ],
            "applied": None,
        }

    arguments = decision.get("args") if action == EDIT else proposed["args"]
    try:
        args = spec.args_model.model_validate(arguments or {})
    except ValidationError as exc:
        return {
            "pending_write": None,
            "messages": [
                _message(
                    spec.name,
                    proposed["id"],
                    {"applied": False, "reason": exc.errors()},
                    failed=True,
                )
            ],
            "applied": None,
        }

    # Re-read from the arguments that are actually about to run. An edit changes
    # what the write does, and a summary composed before the interrupt describes
    # the proposal it replaced -- so leaving it standing would file the audit
    # event, settle the row and confirm back to the user in the words of a change
    # nobody made. On an accept the two are the same string.
    summary = spec.summarise(args)

    blocked = await refusal_for(
        context.session, context.user, spec.name, args.model_dump(mode="json")
    )
    if blocked is not None:
        return {
            "pending_write": None,
            "messages": [
                _message(
                    spec.name, proposed["id"], {"applied": False, "reason": blocked}, failed=True
                )
            ],
            "applied": None,
        }

    tools = await tool_context(runtime, state.get("attachment"))
    result = await spec.handler(tools, args)
    invalidate(runtime)
    event = await record(
        context.session,
        context.user,
        actor=ACTOR_USER,
        action=f"butler.{spec.name}",
        detail={"summary": summary, "args": args.model_dump(mode="json"), "result": result.value},
    )
    await butler_approvals.settle(
        context.session,
        row,
        applied=True,
        args=args.model_dump(mode="json"),
        summary=summary,
        audit_event_id=event.id,
    )

    rows = [row_.as_pair() for row_ in result.evidence]
    if rows:
        events.emit(runtime, events.EVIDENCE, rows=rows)
    return {
        "pending_write": None,
        "messages": [_message(spec.name, proposed["id"], {"applied": True, **_dict(result.value)})],
        "evidence": (state.get("evidence") or []) + rows,
        "tools_used": (state.get("tools_used") or []) + [spec.name],
        "applied": {"tool": spec.name, "summary": summary},
        # The clock starts again here, and it has to. `started_at` was set when
        # the turn began; between then and now the run was parked in the
        # checkpointer waiting for a human to look at a card, which is unbounded
        # and not time the user spent waiting on us. Carrying the old mark into
        # the continuation would have the guard's budget check fire on the very
        # first pass after every approval — the whole of what this route is for
        # refused before it ran once.
        "started_at": time.monotonic(),
    }


async def _approve_change_set(
    state: ButlerState,
    runtime: Runtime[ButlerContext],
    config: RunnableConfig,
    proposed: dict[str, Any],
) -> dict:
    """Approve and apply an ordered batch: every enabled line lands or none do."""
    context = runtime.context
    calls = proposed.get("changes") or []
    validated = []
    for call in calls:
        spec = REGISTRY.get(call.get("name", ""))
        if spec is None or not spec.is_write:
            continue
        args = spec.args_model.model_validate(call.get("args") or {})
        validated.append((call, spec, args, spec.summarise(args)))
    if not validated:
        return {"pending_write": None, "pending_writes": []}

    stored = {
        "changes": [
            {
                "id": call["id"],
                "tool": spec.name,
                "args": args.model_dump(mode="json"),
                "summary": summary,
                "enabled": True,
            }
            for call, spec, args, summary in validated
        ]
    }
    summary = f"Apply {len(validated)} changes together: " + " ".join(item[3] for item in validated)
    graph_thread_id = str(config.get("configurable", {}).get("thread_id", ""))
    row, proposed_now = await butler_approvals.propose(
        context.session,
        context.user,
        thread_id=context.thread_id,
        tool="change_set",
        args=stored,
        summary=summary,
        evidence=state.get("evidence") or [],
        graph_thread_id=graph_thread_id,
        tool_call_id="change_set",
    )
    payload = {
        "approval_id": str(row.id),
        "tool": "change_set",
        "module": "change_set",
        "summary": summary,
        "args": stored,
        "changes": stored["changes"],
    }
    if proposed_now:
        events.emit(runtime, events.APPROVAL, **payload)
    decision = interrupt(payload) or {}
    if decision.get("action", REJECT) == REJECT:
        return {
            "pending_write": None,
            "pending_writes": [],
            "applied": None,
            "messages": [
                _message(call["name"], call["id"], {"applied": False, "reason": "rejected"})
                for call in calls
            ],
        }

    decided = decision.get("args") if decision.get("action") == EDIT else stored
    items = (decided or {}).get("changes") if isinstance(decided, dict) else None
    if not isinstance(items, list):
        items = stored["changes"]
    originals = {call["id"]: call for call in calls}
    ready = []
    try:
        for item in items:
            if not isinstance(item, dict) or item.get("enabled", True) is False:
                continue
            original = originals.get(item.get("id"))
            if original is None or item.get("tool") != original["name"]:
                raise ValueError("an edited change-set may not add or replace tools")
            spec = REGISTRY.get(original["name"])
            if spec is None or not spec.is_write:
                raise ValueError("the change is no longer writable")
            args = spec.args_model.model_validate(item.get("args") or {})
            blocked = await refusal_for(
                context.session, context.user, spec.name, args.model_dump(mode="json")
            )
            if blocked is not None:
                raise ValueError(blocked)
            ready.append((original, spec, args, spec.summarise(args)))
    except (ValidationError, ValueError) as exc:
        return {
            "pending_write": None,
            "pending_writes": [],
            "applied": None,
            "messages": [
                _message("change_set", "change_set", {"applied": False, "reason": str(exc)}, True)
            ],
        }

    tools = await tool_context(runtime, state.get("attachment"))
    results = []
    audit_ids = []
    try:
        async with context.session.begin_nested():
            for call, spec, args, line in ready:
                result = await spec.handler(tools, args)
                event = await record(
                    context.session,
                    context.user,
                    actor=ACTOR_USER,
                    action=f"butler.{spec.name}",
                    detail={
                        "summary": line,
                        "args": args.model_dump(mode="json"),
                        "result": result.value,
                        "change_set_id": str(row.id),
                    },
                )
                results.append((call, spec, args, result, line))
                audit_ids.append(event.id)
    except Exception as exc:
        await butler_approvals.settle(context.session, row, applied=False)
        return {
            "pending_write": None,
            "pending_writes": [],
            "applied": None,
            "messages": [
                _message(
                    "change_set",
                    "change_set",
                    {"applied": False, "reason": f"No changes were applied: {exc}"},
                    True,
                )
            ],
        }

    final_args = {
        "changes": [
            {
                "id": call["id"],
                "tool": spec.name,
                "args": args.model_dump(mode="json"),
                "summary": line,
                "enabled": True,
            }
            for call, spec, args, _, line in results
        ]
    }
    final_summary = f"Applied {len(results)} changes together: " + " ".join(
        item[4] for item in results
    )
    await butler_approvals.settle(
        context.session,
        row,
        applied=True,
        args=final_args,
        summary=final_summary,
        audit_event_id=audit_ids[-1] if audit_ids else None,
    )
    invalidate(runtime)
    evidence = [
        evidence_row.as_pair() for _, _, _, result, _ in results for evidence_row in result.evidence
    ]
    if evidence:
        events.emit(runtime, events.EVIDENCE, rows=evidence)
    return {
        "pending_write": None,
        "pending_writes": [],
        "messages": [
            _message(spec.name, call["id"], {"applied": True, **_dict(result.value)})
            for call, spec, _, result, _ in results
        ],
        "evidence": (state.get("evidence") or []) + evidence,
        "tools_used": (state.get("tools_used") or []) + [item[1].name for item in results],
        "applied": {"tool": "change_set", "summary": final_summary, "count": len(results)},
        "started_at": time.monotonic(),
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {"result": value}


def route_after_approval(state: ButlerState) -> str:
    """Back to the model once a change actually ran; otherwise straight to compose.

    A turn used to end at its first applied write, because this node's only
    edge went to `compose`. That made every multi-part request half a request:
    "log my RM12 lunch and my RM5 coffee" proposed the lunch, applied it, and
    composed an answer about it, while the guard's "one change at a time" had
    already turned the coffee away and nothing was left holding the fact that
    it was owed. The user had to notice and ask again.

    So an applied write goes back to the model, which reads `{"applied": true}`
    as the result of the call it made and can propose the next one — or read
    the ledger it just changed, which is the other thing this makes possible
    ("confirm the draft and tell me what's left"). What bounds it is what
    bounds every other loop here: the iteration cap and the wall-clock budget,
    with each write costing a pass of its own.

    A rejection does not come back. The user has just said no to something, and
    the honest next move is to answer them, not to re-enter a loop whose most
    likely first act is proposing a near-identical card over the dismissal. The
    same goes for a write that failed validation or hit the policy: the reason
    is in the message list and belongs in the answer, not in another attempt.
    """
    return "agent" if state.get("applied") else "compose"
