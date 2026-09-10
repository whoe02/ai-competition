"""Structured progress events, emitted by the graph itself.

DashScope's compatibility mode forbids `tools` with `stream=True`, so the
reasoning turns cannot stream tokens. Progress stays visible anyway because
these events come from the nodes, not from the model.
"""

from __future__ import annotations

import logging
from typing import Any

# Uvicorn owns the configured stderr handler in local runs and Docker.  Making
# this a child of ``uvicorn.error`` ensures INFO workflow records reach that
# handler instead of depending on an application's root logger configuration.
log = logging.getLogger("uvicorn.error.kira.butler")
log.setLevel(logging.INFO)

THINKING = "thinking"
TOOL = "tool"
EVIDENCE = "evidence"
TOKEN = "token"
APPROVAL = "approval"
APP_ACTION = "app_action"
DONE = "done"
ERROR = "error"


def emit(runtime: Any, event: str, **data: Any) -> None:
    """Write one progress event to the stream and terminal log.

    The log deliberately contains the workflow metadata, not prompts, user
    messages, tool arguments, evidence values, or generated answer text.  That
    makes it useful for following a turn in production without turning the
    application log into another store of financial data.
    """
    context = getattr(runtime, "context", None)
    fields: dict[str, Any] = {
        "thread_id": str(getattr(context, "thread_id", "unknown")),
        "message_id": str(getattr(context, "source_message_id", "")) or "approval-resume",
    }
    if event == THINKING:
        fields["step"] = data.get("text", "")
    elif event == TOOL:
        fields["tool"] = data.get("tool", "")
        fields["module"] = data.get("module", "")
    elif event == EVIDENCE:
        fields["evidence_rows"] = len(data.get("rows", []))
    elif event == APPROVAL:
        fields["tool"] = data.get("tool", "")
        fields["module"] = data.get("module", "")
    elif event == ERROR:
        fields["error"] = data.get("message", "")

    if event != TOKEN:
        log.info(
            "butler.event type=%s %s",
            event,
            " ".join(f"{key}={value}" for key, value in fields.items()),
        )

    writer = getattr(runtime, "stream_writer", None)
    if writer is None:
        return
    try:
        writer({"type": event, **data})
    except Exception:  # pragma: no cover - a broken stream must not fail the run
        return
