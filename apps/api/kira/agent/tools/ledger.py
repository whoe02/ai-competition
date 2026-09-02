"""The ledger, under the Butler's control: reading it, and settling it.

Every settlement here is a write, so none of these handlers can be reached
from the tool loop — only from an approved `butler_approvals` row.
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field, field_validator

from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec, money_str
from kira.categories import UNCATEGORISED, slugs
from kira.db.models import INCOME_OTHER, INCOME_SALARY, SOURCE_MANUAL, TXN_INCOME
from kira.money import Money
from kira.services import transactions as ledger

MODULE = "ledger"


class ActivityArgs(BaseModel):
    category: str | None = Field(
        default=None,
        description=f"Narrow the confirmed ledger to one category. One of: {', '.join(slugs())}.",
    )
    days: int = Field(
        default=7, ge=1, le=90, description="How many recent days of the ledger to read."
    )


class TransactionArgs(BaseModel):
    transaction_id: uuid.UUID = Field(description="The transaction's id.")


class AddTransactionArgs(BaseModel):
    merchant: str = Field(min_length=1, max_length=120, description="Who was paid.")
    amount_sen: int = Field(gt=0, description="The amount in sen (RM1 is 100 sen).")
    occurred_on: date = Field(description="The day it happened, as YYYY-MM-DD.")
    category: str = Field(default=UNCATEGORISED, description="One of the known categories.")

    @field_validator("category")
    @classmethod
    def _known(cls, value: str) -> str:
        """An edited approval is user input, and free text fragments the ledger."""
        if value not in slugs():
            raise ValueError(f"category must be one of: {', '.join(slugs())}")
        return value
    note: str = Field(default="", max_length=280, description="Anything worth recording.")


class AddIncomeArgs(BaseModel):
    source_name: str = Field(
        min_length=1, max_length=120, description="Who or what paid the user."
    )
    amount_sen: int = Field(gt=0, description="The received amount in integer sen.")
    occurred_on: date = Field(description="The day the income arrived, as YYYY-MM-DD.")
    income_type: str = Field(
        default=INCOME_OTHER, description="Either salary or other."
    )
    note: str = Field(default="", max_length=280)

    @field_validator("income_type")
    @classmethod
    def _income_type(cls, value: str) -> str:
        if value not in (INCOME_SALARY, INCOME_OTHER):
            raise ValueError("income_type must be salary or other")
        return value


class UpdateIncomeProfileArgs(BaseModel):
    monthly_income_sen: int = Field(
        ge=0,
        description=(
            "The user's recurring monthly salary/income forecast in integer sen. "
            "Use only when they explicitly say their recurring income changed."
        ),
    )
    next_payday: date | None = Field(
        default=None, description="The next payday, only when explicitly stated."
    )


async def _list_activity(ctx: ToolContext, args: ActivityArgs) -> ToolResult:
    activity = await ledger.list_activity(ctx.session, ctx.user, args.category)
    cutoff = ctx.today.toordinal() - args.days
    days = [day for day in activity.days if day.date.toordinal() > cutoff]
    value = {
        "drafts": [
            {
                "id": str(draft.id),
                "merchant": draft.merchant,
                "amount_sen": draft.amount_sen,
                "occurred_on": draft.occurred_on.isoformat(),
                "source": draft.source,
                "confidence": draft.confidence,
                "direction": draft.direction,
                "income_type": draft.income_type,
            }
            for draft in activity.drafts
        ],
        "draft_total_sen": activity.draft_total_sen,
        "spent_this_cycle_sen": activity.spent_this_cycle_sen,
        "income_this_cycle_sen": activity.income_this_cycle_sen,
        "days": [
            {
                "date": day.date.isoformat(),
                "total_sen": day.total_sen,
                "transactions": [
                    {
                        "id": str(txn.id),
                        "merchant": txn.merchant,
                        "amount_sen": txn.amount_sen,
                        "category": txn.category,
                        "direction": txn.direction,
                        "income_type": txn.income_type,
                    }
                    for txn in day.transactions
                ],
            }
            for day in days
        ],
        "categories": [
            {"slug": row.slug, "label": row.label, "spent_this_cycle_sen": row.spent_this_cycle_sen}
            for row in activity.categories
        ],
    }
    currency = ctx.currency
    evidence = [
        EvidenceRow(
            "Spent this cycle", money_str(Money(activity.spent_this_cycle_sen, currency))
        ),
        EvidenceRow("Drafts waiting", str(len(activity.drafts))),
    ]
    if activity.drafts:
        evidence.append(
            EvidenceRow(
                "Waiting to be settled", money_str(Money(activity.draft_total_sen, currency))
            )
        )
    if activity.categories:
        top = activity.categories[0]
        evidence.append(
            EvidenceRow(
                f"Most spent — {top.label}",
                money_str(Money(top.spent_this_cycle_sen, currency)),
            )
        )
    return ToolResult(value, tuple(evidence))


def _settled(view: ledger.TransactionView, currency: str) -> ToolResult:
    return ToolResult(
        {
            "id": str(view.id),
            "merchant": view.merchant,
            "amount_sen": view.amount_sen,
            "status": view.status,
            "direction": view.direction,
            "income_type": view.income_type,
        },
        (
            EvidenceRow(view.merchant, money_str(Money(view.amount_sen, currency))),
            EvidenceRow("Now", view.status),
        ),
    )


async def _confirm(ctx: ToolContext, args: TransactionArgs) -> ToolResult:
    view = await ledger.confirm_draft(ctx.session, ctx.user, args.transaction_id)
    return _settled(view, ctx.currency)


async def _discard(ctx: ToolContext, args: TransactionArgs) -> ToolResult:
    view = await ledger.discard_draft(ctx.session, ctx.user, args.transaction_id)
    return _settled(view, ctx.currency)


async def _unconfirm(ctx: ToolContext, args: TransactionArgs) -> ToolResult:
    view = await ledger.unconfirm(ctx.session, ctx.user, args.transaction_id)
    return _settled(view, ctx.currency)


async def _add(ctx: ToolContext, args: AddTransactionArgs) -> ToolResult:
    view = await ledger.create_transaction(
        ctx.session,
        ctx.user,
        merchant=args.merchant,
        amount_sen=args.amount_sen,
        occurred_on=args.occurred_on,
        category=args.category,
        source=SOURCE_MANUAL,
        note=args.note,
    )
    return _settled(view, ctx.currency)


async def _add_income(ctx: ToolContext, args: AddIncomeArgs) -> ToolResult:
    view = await ledger.create_transaction(
        ctx.session,
        ctx.user,
        merchant=args.source_name,
        amount_sen=args.amount_sen,
        occurred_on=args.occurred_on,
        category="income",
        source=SOURCE_MANUAL,
        note=args.note,
        direction=TXN_INCOME,
        income_type=args.income_type,
    )
    return ToolResult(
        {
            "id": str(view.id),
            "source_name": view.merchant,
            "amount_sen": view.amount_sen,
            "income_type": view.income_type,
            "status": view.status,
        },
        (
            EvidenceRow(view.merchant, money_str(Money(view.amount_sen, ctx.currency))),
            EvidenceRow("Now", "income draft — not counted until confirmed"),
        ),
    )


async def _update_income_profile(
    ctx: ToolContext, args: UpdateIncomeProfileArgs
) -> ToolResult:
    ctx.user.monthly_income = Money(args.monthly_income_sen, ctx.currency)
    if args.next_payday is not None:
        ctx.user.next_payday = args.next_payday
    await ctx.session.flush()
    return ToolResult(
        {
            "monthly_income_sen": ctx.user.monthly_income.sen,
            "next_payday": ctx.user.next_payday.isoformat(),
        },
        (
            EvidenceRow("Recurring income", money_str(ctx.user.monthly_income)),
            EvidenceRow("Next payday", ctx.user.next_payday.isoformat()),
        ),
    )


def _summarise_id(verb: str):
    def summarise(args: TransactionArgs) -> str:
        return f"{verb} transaction {args.transaction_id}."

    return summarise


def _summarise_add(args: AddTransactionArgs) -> str:
    return (
        f"Add {args.merchant} for RM{Money(args.amount_sen).ringgit_str()} on "
        f"{args.occurred_on.isoformat()} as a draft."
    )


def _summarise_income(args: AddIncomeArgs) -> str:
    return (
        f"Add {args.income_type} income from {args.source_name} for "
        f"RM{Money(args.amount_sen).ringgit_str()} on {args.occurred_on.isoformat()} as a draft."
    )


def _summarise_income_profile(args: UpdateIncomeProfileArgs) -> str:
    payday = f" and next payday {args.next_payday.isoformat()}" if args.next_payday else ""
    return (
        f"Set recurring monthly income to RM{Money(args.monthly_income_sen).ringgit_str()}"
        f"{payday}."
    )


SPECS = (
    ToolSpec(
        name="list_activity",
        module=MODULE,
        kind="read",
        label="Reading your ledger",
        description=(
            "Recent confirmed spending grouped by day, the drafts still waiting for a "
            "decision, and this cycle's totals by category."
        ),
        args_model=ActivityArgs,
        handler=_list_activity,
    ),
    ToolSpec(
        name="confirm_draft",
        module=MODULE,
        kind="write",
        label="Confirming a draft",
        description="Put a waiting draft onto the ledger so it counts against safe-to-spend.",
        args_model=TransactionArgs,
        handler=_confirm,
        summarise=_summarise_id("Confirm"),
    ),
    ToolSpec(
        name="discard_draft",
        module=MODULE,
        kind="write",
        label="Discarding a draft",
        description="Retire a waiting draft. The row stays for the record; the money never counts.",
        args_model=TransactionArgs,
        handler=_discard,
        summarise=_summarise_id("Discard"),
    ),
    ToolSpec(
        name="unconfirm_transaction",
        module=MODULE,
        kind="write",
        label="Taking one back off the ledger",
        description="Return a confirmed transaction to the drafts, undoing a mis-tap.",
        args_model=TransactionArgs,
        handler=_unconfirm,
        summarise=_summarise_id("Take back off the ledger:"),
    ),
    ToolSpec(
        name="add_transaction",
        module=MODULE,
        kind="write",
        label="Adding a draft",
        description=(
            "Record spending the user describes. It lands as a draft, never straight "
            "onto the ledger."
        ),
        args_model=AddTransactionArgs,
        handler=_add,
        summarise=_summarise_add,
    ),
    ToolSpec(
        name="add_income",
        module=MODULE,
        kind="write",
        label="Adding income",
        description=(
            "Record salary or other income the user says has arrived. It becomes a draft "
            "for confirmation; it does not update recurring salary by itself."
        ),
        args_model=AddIncomeArgs,
        handler=_add_income,
        summarise=_summarise_income,
    ),
    ToolSpec(
        name="update_income_profile",
        module=MODULE,
        kind="write",
        label="Updating recurring income",
        description=(
            "Update the user's forecast monthly income when they explicitly say their "
            "salary or recurring income changed. This forecast does not create cash."
        ),
        args_model=UpdateIncomeProfileArgs,
        handler=_update_income_profile,
        summarise=_summarise_income_profile,
    ),
)
