"""The nightly money check, as something the Butler can be asked about.

`kira.services.briefings` runs on a schedule and leaves a summary plus, where a
detector found something safe to act on, a handful of pending proposals. The
Today screen shows it. Until this tool existed the Butler could not: "what did
you find last night?" reached a model with a full picture of the user's money
and no way to see the one thing the question was about, so it answered from the
dashboard and said nothing about the briefing at all.

Reading only, and deliberately. Running a briefing is the scheduler's job, and
a proposal it left is answered on its own card — the approvals it raised carry
`graph_thread_id = "briefing:<date>"` and settle through
`kira.agent.scheduled_approvals`, not through this graph.
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, Field

from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec
from kira.services import briefings as briefing_service

MODULE = "briefing"


class BriefingArgs(BaseModel):
    on_date: date | None = Field(
        default=None,
        description=(
            "The day whose briefing to read, as YYYY-MM-DD. Leave it out for today's, "
            "which is what almost every question means."
        ),
    )


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


async def _read(ctx: ToolContext, args: BriefingArgs) -> ToolResult:
    on_date = args.on_date or ctx.today
    inbox = await briefing_service.briefing_inbox(ctx.session, ctx.user, on_date)

    if inbox is None:
        # A missing briefing is a fact about the night, not a failure. Said
        # plainly so the model reports "there wasn't one" rather than inventing
        # the contents of one that never ran.
        yesterday = on_date - timedelta(days=1)
        return ToolResult(
            {
                "found": False,
                "on_date": on_date.isoformat(),
                "reason": (
                    "No money check has been run for that day. The nightly one covers "
                    f"the day it runs on, so {yesterday.isoformat()} may have one."
                ),
            },
            (EvidenceRow("Money check", f"none run for {on_date.isoformat()}"),),
        )

    value = {
        "found": True,
        "on_date": inbox.on_date.isoformat(),
        "summary": inbox.summary,
        "proposal_count": inbox.proposal_count,
        "pending_proposal_count": inbox.pending_proposal_count,
    }
    evidence = [EvidenceRow(f"Money check {inbox.on_date.isoformat()}", inbox.summary)]
    if inbox.proposal_count:
        evidence.append(
            EvidenceRow(
                "Left for you",
                f"{_plural(inbox.proposal_count, 'proposal')}, "
                f"{inbox.pending_proposal_count} still waiting",
            )
        )
    return ToolResult(value, tuple(evidence))


async def _run(ctx: ToolContext, args: BriefingArgs) -> ToolResult:
    on_date = args.on_date or ctx.today
    result = await briefing_service.nightly_briefing(ctx.session, ctx.user, on_date)
    return ToolResult(
        {
            "id": str(result.id),
            "on_date": result.on_date.isoformat(),
            "summary": result.summary,
            "proposal_count": result.proposal_count,
            "created": result.created,
        },
        (EvidenceRow(f"Money check {result.on_date.isoformat()}", result.summary),),
    )


def _summarise_run(args: BriefingArgs) -> str:
    return f"Run the money check for {args.on_date.isoformat() if args.on_date else 'today'}."


SPECS = (
    ToolSpec(
        name="read_briefing",
        module=MODULE,
        kind="read",
        label="Reading your money check",
        description=(
            "The nightly money check for a day: what Kira found while the user was "
            "away, and how many proposals it left waiting. Call it for 'what did you "
            "find', 'anything overnight', 'what is in my briefing' or any question "
            "about what Kira noticed rather than what the numbers are now."
        ),
        args_model=BriefingArgs,
        handler=_read,
    ),
    ToolSpec(
        name="run_briefing",
        module=MODULE,
        kind="write",
        label="Running your money check",
        description="Run the idempotent money briefing for today or a specified day.",
        args_model=BriefingArgs,
        handler=_run,
        summarise=_summarise_run,
    ),
)
