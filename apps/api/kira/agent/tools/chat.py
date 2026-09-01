"""The explicit, inspectable decision that a turn is ordinary conversation."""

from __future__ import annotations

from pydantic import BaseModel

from kira.agent.tools.spec import ToolContext, ToolResult, ToolSpec

MODULE = "chat"


class JustTalkArgs(BaseModel):
    """Conversation needs no arguments and reads no financial data."""


async def _just_talk(_: ToolContext, __: JustTalkArgs) -> ToolResult:
    """Mark a warm conversational turn without returning a fact to quote."""
    return ToolResult({"conversation": True})


SPECS = (
    ToolSpec(
        name="just_talk",
        module=MODULE,
        kind="read",
        label="Keeping the conversation going",
        description=(
            "Use for a greeting, thanks, or ordinary conversation that does not need "
            "a financial fact. It records that this turn should answer warmly without "
            "looking up or stating any numbers."
        ),
        args_model=JustTalkArgs,
        handler=_just_talk,
    ),
)
