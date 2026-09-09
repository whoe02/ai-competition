"""Whatever the user showed or said this turn.

Receipt photos and voice notes are read outside the graph, by
`kira.services.capture`, and arrive on the turn as an attachment. This tool is
how the Butler looks at one: the fields, the reader's confidence in each, and
the fact that none of it has touched the ledger.

The seam is deliberate. When a real OCR or speech provider replaces the
deterministic fakes in the adapter registry, nothing in the agent changes.
"""

from __future__ import annotations

from pydantic import BaseModel

from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec

MODULE = "capture"


class NoArgs(BaseModel):
    """Takes nothing: there is at most one attachment on a turn."""


async def _inspect(ctx: ToolContext, _: NoArgs) -> ToolResult:
    attachment = ctx.attachment
    if not attachment:
        return ToolResult(
            {"attached": False},
            (EvidenceRow("Attachment", "none on this message"),),
        )

    fields = attachment.get("fields") or []
    is_transaction = attachment.get("is_transaction", True)
    value = {
        "attached": True,
        "kind": attachment.get("kind"),
        "is_transaction": is_transaction,
        "merchant": attachment.get("merchant"),
        "amount_sen": attachment.get("amount_sen"),
        "occurred_on": attachment.get("occurred_on"),
        "category": attachment.get("category"),
        "transcript": attachment.get("transcript", ""),
        "confidence": attachment.get("confidence"),
        "note": attachment.get("note", ""),
        "on_the_ledger": False,
    }
    evidence = [
        EvidenceRow(
            field.get("label", "Field"),
            f"{field.get('value', '')} · {field.get('confidence', 0)}% sure",
        )
        for field in fields
    ]
    evidence.append(
        EvidenceRow(
            "On the ledger",
            "not until you confirm it" if is_transaction else "no transaction was inferred",
        )
    )
    return ToolResult(value, tuple(evidence))


SPECS = (
    ToolSpec(
        name="inspect_attachment",
        module=MODULE,
        kind="read",
        label="Reading what you showed me",
        description=(
            "Look at the receipt photo or voice note attached to this message: what "
            "was read, and how sure the reader was of each field. Call this whenever "
            "the user refers to something they scanned or said."
        ),
        args_model=NoArgs,
        handler=_inspect,
    ),
)
