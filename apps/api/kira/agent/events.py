"""Structured progress events, emitted by the graph itself.

DashScope's compatibility mode forbids `tools` with `stream=True`, so the
reasoning turns cannot stream tokens. Progress stays visible anyway because
these events come from the nodes, not from the model.
"""

from __future__ import annotations

from typing import Any

THINKING = "thinking"
TOOL = "tool"
EVIDENCE = "evidence"
TOKEN = "token"
APPROVAL = "approval"
APP_ACTION = "app_action"
DONE = "done"
ERROR = "error"


def emit(runtime: Any, event: str, **data: Any) -> None:
    """Write one event to the stream, or do nothing when nobody is streaming."""
    writer = getattr(runtime, "stream_writer", None)
    if writer is None:
        return
    try:
        writer({"type": event, **data})
    except Exception:  # pragma: no cover - a broken stream must not fail the run
        return
