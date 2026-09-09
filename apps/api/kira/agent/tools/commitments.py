"""Commitments: the bills reserved before anything is safe to spend."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field

from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec, money_str
from kira.money import Money
from kira.services import commitments as commitment_service

MODULE = "commitments"


class ListArgs(BaseModel):
    upcoming_only: bool = Field(default=True, description="Only bills still due on or after today.")


class CreateCommitmentArgs(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    amount_sen: int = Field(gt=0, description="The amount in sen.")
    due_date: date = Field(description="When it falls due, as YYYY-MM-DD.")


class UpdateCommitmentArgs(BaseModel):
    commitment_id: uuid.UUID
    name: str | None = Field(default=None, max_length=80)
    amount_sen: int | None = Field(default=None, gt=0)
    due_date: date | None = None


async def _list(ctx: ToolContext, args: ListArgs) -> ToolResult:
    views = await commitment_service.list_commitments(
        ctx.session, ctx.user, ctx.today, upcoming_only=args.upcoming_only
    )
    currency = ctx.currency
    value = [
        {
            "id": str(view.id),
            "name": view.name,
            "amount_sen": view.amount_sen,
            "due_date": view.due_date.isoformat(),
            "days_until": view.days_until,
            "protected": view.protected,
        }
        for view in views
    ]
    evidence = tuple(
        EvidenceRow(
            view.name + (" · protected" if view.protected else ""),
            f"{money_str(Money(view.amount_sen, currency))} in {view.days_until} days",
        )
        for view in views[:5]
    )
    return ToolResult(value, evidence)


async def _create(ctx: ToolContext, args: CreateCommitmentArgs) -> ToolResult:
    view = await commitment_service.create_commitment(
        ctx.session,
        ctx.user,
        name=args.name,
        amount_sen=args.amount_sen,
        due_date=args.due_date,
    )
    return ToolResult({"id": str(view.id), "name": view.name}, ())


async def _update(ctx: ToolContext, args: UpdateCommitmentArgs) -> ToolResult:
    view = await commitment_service.update_commitment(
        ctx.session,
        ctx.user,
        args.commitment_id,
        ctx.today,
        name=args.name,
        amount_sen=args.amount_sen,
        due_date=args.due_date,
    )
    return ToolResult({"id": str(view.id), "name": view.name}, ())


def _summarise_create(args: CreateCommitmentArgs) -> str:
    return (
        f"Add the bill “{args.name}”: RM{Money(args.amount_sen).ringgit_str()} due "
        f"{args.due_date.isoformat()}."
    )


def _summarise_update(args: UpdateCommitmentArgs) -> str:
    changes = []
    if args.name is not None:
        changes.append(f"rename to “{args.name}”")
    if args.amount_sen is not None:
        changes.append(f"amount RM{Money(args.amount_sen).ringgit_str()}")
    if args.due_date is not None:
        changes.append(f"due {args.due_date.isoformat()}")
    return f"Update bill {args.commitment_id}: {', '.join(changes) or 'no change'}."


SPECS = (
    ToolSpec(
        name="list_commitments",
        module=MODULE,
        kind="read",
        label="Reading your bills",
        description=(
            "The user's committed bills, what each costs and how many days until each is due."
        ),
        args_model=ListArgs,
        handler=_list,
    ),
    ToolSpec(
        name="create_commitment",
        module=MODULE,
        kind="write",
        label="Adding a bill",
        description="Record a recurring or one-off bill so it is reserved before safe-to-spend.",
        args_model=CreateCommitmentArgs,
        handler=_create,
        summarise=_summarise_create,
    ),
    ToolSpec(
        name="update_commitment",
        module=MODULE,
        kind="write",
        label="Updating a bill",
        description=(
            "Change an unprotected bill's name, amount or due date. Protected bills "
            "refuse every change."
        ),
        args_model=UpdateCommitmentArgs,
        handler=_update,
        summarise=_summarise_update,
    ),
)
