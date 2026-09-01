"""Execute a user-confirmed worker proposal without inventing a graph checkpoint.

Worker proposals have the same durable approval record as a conversational
proposal, but they were not produced by a paused LangGraph turn. They still
validate the edited arguments, re-run policy, audit, and settle exactly at the
moment the user accepts them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from kira.agent.policy import refusal_for
from kira.agent.tools import REGISTRY, ToolContext
from kira.db.models import ButlerApproval, User
from kira.services import butler_approvals
from kira.services.audit import ACTOR_USER, record
from kira.services.dashboard import today_dashboard
from kira.services.snapshot import load_snapshot


class ScheduledApprovalError(ValueError):
    """The proposal cannot be applied and remains pending for the user."""


@dataclass(frozen=True, slots=True)
class ScheduledApprovalResult:
    answer: str
    evidence: list[list[str]]


async def apply_scheduled_approval(
    session: AsyncSession,
    user: User,
    approval: ButlerApproval,
    *,
    arguments: dict[str, Any],
    today: date,
) -> ScheduledApprovalResult:
    """Apply one scheduled proposal only after validation and policy re-checks."""
    spec = REGISTRY.get(approval.tool)
    if spec is None or not spec.is_write:
        raise ScheduledApprovalError("This scheduled proposal is no longer a permitted write.")
    try:
        args = spec.args_model.model_validate(arguments)
    except ValidationError as exc:
        raise ScheduledApprovalError(str(exc.errors())) from exc

    serialised_args = args.model_dump(mode="json")
    blocked = await refusal_for(session, user, spec.name, serialised_args)
    if blocked is not None:
        raise ScheduledApprovalError(blocked)

    context = ToolContext(
        session=session,
        user=user,
        today=today,
        snapshot=await load_snapshot(session, user, today),
        dashboard=await today_dashboard(session, user, today),
    )
    result = await spec.handler(context, args)
    event = await record(
        session,
        user,
        actor=ACTOR_USER,
        action=f"butler.{spec.name}",
        detail={"summary": approval.summary, "args": serialised_args, "result": result.value},
    )
    await butler_approvals.settle(
        session,
        approval,
        applied=True,
        args=serialised_args,
        audit_event_id=event.id,
    )
    evidence = [row.as_pair() for row in result.evidence]
    return ScheduledApprovalResult(
        answer=f"Done — {approval.summary}",
        evidence=evidence,
    )
