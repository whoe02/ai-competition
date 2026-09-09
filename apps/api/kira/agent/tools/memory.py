"""The Butler's memory, as tools the user can direct.

Passive extraction writes to `butler_memories` on its own (see
`nodes/memory.py`); these are the explicit, user-directed path, and the two
that change a fact are writes like any other — "remember that" is a request the
user gets to confirm in the same words Kira will keep.

`forget` and `correct_memory` both take an id, and until the prompt carried one
they were unreachable: the memory block rendered facts as prose and no tool
returned an id, so the model had nothing to name. `list_memories` is the
lookup path — the same one `list_activity` is for a draft — and
`prompt.memory_block` now puts the id on every remembered row as well, because
the common case is a user correcting something they can already see Kira
believes.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec
from kira.db.models import MEMORY_KINDS
from kira.services import butler_memory

MODULE = "memory"


class RememberArgs(BaseModel):
    kind: str = Field(description=f"One of: {', '.join(MEMORY_KINDS)}.")
    subject: str = Field(
        min_length=1,
        max_length=80,
        description="A short noun phrase naming what the fact is about, e.g. 'housemate'.",
    )
    fact: str = Field(
        min_length=1,
        max_length=280,
        description="One sentence, written so the user would recognise it as their own.",
    )
    confidence: int = Field(default=90, ge=0, le=100)


class ForgetArgs(BaseModel):
    memory_id: uuid.UUID = Field(description="The remembered fact to delete.")


class ListArgs(BaseModel):
    """Takes nothing: a user has one working set of facts."""


class CorrectArgs(BaseModel):
    memory_id: uuid.UUID = Field(description="The remembered fact to rewrite.")
    fact: str = Field(
        min_length=1,
        max_length=280,
        description=(
            "The corrected sentence, written whole rather than as a diff. It replaces "
            "the old one, so it must read as a complete fact on its own."
        ),
    )


async def _remember(ctx: ToolContext, args: RememberArgs) -> ToolResult:
    view = await butler_memory.remember(
        ctx.session,
        ctx.user,
        kind=args.kind,
        subject=args.subject,
        fact=args.fact,
        confidence=args.confidence,
    )
    return ToolResult(
        {"id": str(view.id), "fact": view.fact},
        (EvidenceRow("Remembered", view.fact),),
    )


async def _list(ctx: ToolContext, _: ListArgs) -> ToolResult:
    views = await butler_memory.list_memories(ctx.session, ctx.user)
    value = [
        {
            "id": str(view.id),
            "kind": view.kind,
            "subject": view.subject,
            "fact": view.fact,
            "confidence": view.confidence,
        }
        for view in views
    ]
    return ToolResult(
        value,
        tuple(EvidenceRow(view.subject, view.fact) for view in views[:5]),
    )


async def _correct(ctx: ToolContext, args: CorrectArgs) -> ToolResult:
    view = await butler_memory.correct(ctx.session, ctx.user, args.memory_id, args.fact)
    return ToolResult(
        {"id": str(view.id), "fact": view.fact},
        (EvidenceRow("Corrected", view.fact),),
    )


async def _forget(ctx: ToolContext, args: ForgetArgs) -> ToolResult:
    view = await butler_memory.forget(ctx.session, ctx.user, args.memory_id)
    return ToolResult(
        {"id": str(view.id)},
        (EvidenceRow("Forgotten", view.fact),),
    )


SPECS = (
    ToolSpec(
        name="list_memories",
        module=MODULE,
        kind="read",
        label="Reading what I remember",
        description=(
            "Every durable fact Kira holds about the user, with the id each one is "
            "changed by. Use it before forget or correct_memory when the fact the user "
            "means is not one of the remembered rows already in front of you."
        ),
        args_model=ListArgs,
        handler=_list,
    ),
    ToolSpec(
        name="correct_memory",
        module=MODULE,
        kind="write",
        label="Correcting what I remember",
        description=(
            "Rewrite a remembered fact that is wrong or out of date, keeping the same "
            "id. Use it when the user corrects something Kira believes rather than "
            "adding something new; use forget when the fact should not be held at all."
        ),
        args_model=CorrectArgs,
        handler=_correct,
        summarise=lambda args: f"Correct what I remember to: {args.fact}",
    ),
    ToolSpec(
        name="remember",
        module=MODULE,
        kind="write",
        label="Remembering that",
        description=(
            "Keep a durable fact about the user that should shape future answers. Use "
            "it when they ask to be remembered, or state a standing rule."
        ),
        args_model=RememberArgs,
        handler=_remember,
        summarise=lambda args: f"Remember: {args.fact}",
    ),
    ToolSpec(
        name="forget",
        module=MODULE,
        kind="write",
        label="Forgetting that",
        description="Delete a remembered fact by id.",
        args_model=ForgetArgs,
        handler=_forget,
        summarise=lambda args: f"Forget memory {args.memory_id}.",
    ),
)
