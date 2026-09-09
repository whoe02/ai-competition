"""Declarative record coverage and the Butler's one general-purpose selector.

The declaration is the allowlist: a resource names the fields the model may
read, filter and change.  Search compiles only those names and operators.  The
write factory binds handlers to service functions; it never mutates an ORM row.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import asc, desc, select

from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec
from kira.categories import slugs
from kira.db.models import Account, Briefing, Commitment, Goal, Transaction, User
from kira.money import Money
from kira.services import accounts, goals, transactions
from kira.services.profile import update_profile

MODULE = "records"
FilterOp = Literal["eq", "ne", "contains", "gte", "lte", "in"]
ResourceName = Literal["transactions", "goals", "commitments", "accounts", "profile", "briefings"]


@dataclass(frozen=True, slots=True)
class Resource:
    name: str
    model: type
    readable: tuple[str, ...]
    filterable: tuple[str, ...]
    writable: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    summarise: Callable[[Any], str] = lambda row: str(getattr(row, "id", "record"))


RESOURCES = {
    item.name: item
    for item in (
        Resource(
            "transactions",
            Transaction,
            (
                "id",
                "merchant",
                "amount_sen",
                "category",
                "occurred_on",
                "status",
                "source",
                "direction",
                "income_type",
                "note",
            ),
            (
                "id",
                "merchant",
                "amount_sen",
                "category",
                "occurred_on",
                "status",
                "source",
                "direction",
                "income_type",
            ),
            ("merchant", "amount_sen", "category", "occurred_on", "status", "note"),
            ("confirmed rows must be unconfirmed before correction",),
        ),
        Resource(
            "goals",
            Goal,
            (
                "id",
                "name",
                "horizon",
                "target_sen",
                "saved_sen",
                "monthly_sen",
                "target_date",
                "priority",
                "status",
                "note",
            ),
            (
                "id",
                "name",
                "horizon",
                "target_sen",
                "saved_sen",
                "monthly_sen",
                "target_date",
                "priority",
                "status",
            ),
            (
                "name",
                "horizon",
                "target_sen",
                "saved_sen",
                "monthly_sen",
                "target_date",
                "status",
                "note",
            ),
            ("retirement is status=cancelled; no delete",),
        ),
        Resource(
            "commitments",
            Commitment,
            ("id", "name", "amount_sen", "due_date", "protected"),
            ("id", "name", "amount_sen", "due_date", "protected"),
            ("name", "amount_sen", "due_date"),
            ("protected commitments cannot be changed",),
        ),
        Resource(
            "accounts",
            Account,
            ("id", "name", "kind", "opening_balance_sen"),
            ("id", "name", "kind", "opening_balance_sen"),
            ("name", "kind"),
            ("balances are derived and untouchable",),
        ),
        Resource(
            "profile",
            User,
            (
                "id",
                "display_name",
                "currency",
                "monthly_income_sen",
                "next_payday",
                "cycle_start",
                "cycle_days",
            ),
            ("display_name", "currency", "next_payday", "cycle_start", "cycle_days"),
            (
                "display_name",
                "monthly_income_sen",
                "next_payday",
                "cycle_start",
                "cycle_days",
            ),
            ("buffer and balance are never writable",),
        ),
        Resource(
            "briefings",
            Briefing,
            ("id", "on_date", "summary", "created_at"),
            ("id", "on_date", "created_at"),
            (),
            ("briefings are append-only runs",),
        ),
    )
}


class RecordFilter(BaseModel):
    field: str = Field(description="An allowlisted filter field for the selected resource.")
    op: FilterOp = "eq"
    value: Any


class SearchRecordsArgs(BaseModel):
    resource: ResourceName
    filters: list[RecordFilter] = Field(default_factory=list, max_length=8)
    order_by: str | None = None
    descending: bool = True
    limit: int = Field(default=25, ge=1, le=100)

    @model_validator(mode="after")
    def fields_are_declared(self):
        resource = RESOURCES[self.resource]
        invalid = [item.field for item in self.filters if item.field not in resource.filterable]
        if self.order_by is not None and self.order_by not in resource.filterable:
            invalid.append(self.order_by)
        if invalid:
            raise ValueError(f"fields not filterable on {self.resource}: {', '.join(invalid)}")
        return self


_MONEY_FIELDS = {
    "amount_sen": "amount",
    "target_sen": "target",
    "saved_sen": "saved",
    "monthly_sen": "monthly",
    "opening_balance_sen": "opening_balance",
    "monthly_income_sen": "monthly_income",
}


def _column(resource: Resource, field: str):
    return getattr(resource.model, _MONEY_FIELDS.get(field, field))


def _coerce(column, field: str, value: Any, currency: str) -> Any:
    if field in _MONEY_FIELDS:
        return Money(int(value), currency)
    python_type = getattr(column.type, "python_type", None)
    if python_type is date and not isinstance(value, date):
        return date.fromisoformat(str(value))
    if python_type is uuid.UUID and not isinstance(value, uuid.UUID):
        return uuid.UUID(str(value))
    return value


def _clause(resource: Resource, item: RecordFilter, currency: str):
    column = _column(resource, item.field)
    if item.op == "contains":
        return column.ilike(f"%{str(item.value)}%")
    if item.op == "in":
        if not isinstance(item.value, list):
            raise ValueError("the in operator requires a list")
        return column.in_([_coerce(column, item.field, value, currency) for value in item.value])
    value = _coerce(column, item.field, item.value, currency)
    return {
        "eq": column == value,
        "ne": column != value,
        "gte": column >= value,
        "lte": column <= value,
    }[item.op]


def _serialise(row: Any, resource: Resource) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in resource.readable:
        value = getattr(row, _MONEY_FIELDS.get(field, field))
        if isinstance(value, Money):
            value = value.sen
        elif isinstance(value, (date, datetime)):
            value = value.isoformat()
        elif isinstance(value, uuid.UUID):
            value = str(value)
        result[field] = value
    return result


async def _search(ctx: ToolContext, args: SearchRecordsArgs) -> ToolResult:
    resource = RESOURCES[args.resource]
    query = select(resource.model)
    if resource.model is User:
        query = query.where(User.id == ctx.user.id)
    else:
        query = query.where(resource.model.user_id == ctx.user.id)
    for item in args.filters:
        query = query.where(_clause(resource, item, ctx.currency))
    order_name = args.order_by or (
        "created_at" if "created_at" in resource.filterable else resource.filterable[0]
    )
    order = _column(resource, order_name)
    query = query.order_by(desc(order) if args.descending else asc(order)).limit(args.limit)
    rows = (await ctx.session.execute(query)).scalars().all()
    values = [_serialise(row, resource) for row in rows]
    return ToolResult(
        {"resource": args.resource, "count": len(values), "records": values},
        (EvidenceRow(f"{args.resource.capitalize()} found", str(len(values))),),
    )


class CreateGoalArgs(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    horizon: Literal["short", "long"]
    target_sen: int = Field(gt=0)
    monthly_sen: int = Field(gt=0)
    saved_sen: int = Field(default=0, ge=0)
    note: str = Field(default="", max_length=280)


class UpdateGoalArgs(BaseModel):
    goal_id: uuid.UUID
    name: str | None = Field(default=None, min_length=1, max_length=80)
    target_sen: int | None = Field(default=None, gt=0)
    monthly_sen: int | None = Field(default=None, gt=0)
    target_date: date | None = None
    status: Literal["active", "paused", "achieved", "cancelled"] | None = None
    note: str | None = Field(default=None, max_length=280)

    @model_validator(mode="after")
    def has_change(self):
        if not self.model_dump(exclude={"goal_id"}, exclude_none=True):
            raise ValueError("provide at least one goal change")
        return self


class GoalContributionArgs(BaseModel):
    goal_id: uuid.UUID
    amount_sen: int = Field(gt=0)
    contributed_on: date


class UpdateTransactionArgs(BaseModel):
    transaction_id: uuid.UUID
    merchant: str | None = Field(default=None, min_length=1, max_length=120)
    amount_sen: int | None = Field(default=None, gt=0)
    category: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=280)

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str | None) -> str | None:
        if value is not None and value not in slugs():
            raise ValueError("choose a known category")
        return value

    @model_validator(mode="after")
    def has_change(self):
        if not self.model_dump(exclude={"transaction_id"}, exclude_none=True):
            raise ValueError("provide at least one transaction change")
        return self


class CreateAccountArgs(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["bank", "ewallet", "cash"]


class UpdateAccountArgs(BaseModel):
    account_id: uuid.UUID
    name: str | None = Field(default=None, min_length=1, max_length=80)
    kind: Literal["bank", "ewallet", "cash"] | None = None

    @model_validator(mode="after")
    def has_change(self):
        if self.name is None and self.kind is None:
            raise ValueError("provide at least one account change")
        return self


class UpdateProfileArgs(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    monthly_income_sen: int | None = Field(default=None, ge=0)
    next_payday: date | None = None
    cycle_start: date | None = None
    cycle_days: int | None = Field(default=None, ge=1, le=62)

    @model_validator(mode="after")
    def has_change(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("provide at least one profile change")
        return self


async def _create_goal(ctx: ToolContext, args: CreateGoalArgs) -> ToolResult:
    view = await goals.create_goal(ctx.session, ctx.user, **args.model_dump())
    return ToolResult({"id": str(view.id), "name": view.name, "status": view.status})


async def _update_goal(ctx: ToolContext, args: UpdateGoalArgs) -> ToolResult:
    view = await goals.update_goal(
        ctx.session,
        ctx.user,
        args.goal_id,
        **args.model_dump(exclude={"goal_id"}, exclude_none=True),
    )
    return ToolResult({"id": str(view.id), "name": view.name, "status": view.status})


async def _contribute(ctx: ToolContext, args: GoalContributionArgs) -> ToolResult:
    view = await goals.record_contribution(
        ctx.session,
        ctx.user,
        args.goal_id,
        amount_sen=args.amount_sen,
        contributed_on=args.contributed_on,
    )
    return ToolResult({"id": str(view.id), "name": view.name, "saved_sen": view.saved_sen})


async def _update_transaction(ctx: ToolContext, args: UpdateTransactionArgs) -> ToolResult:
    """Correct a draft or confirmed row without model-managed status choreography."""
    before = await transactions.get_transaction(ctx.session, ctx.user, args.transaction_id)
    was_confirmed = before.status == "confirmed"
    if was_confirmed:
        await transactions.unconfirm(ctx.session, ctx.user, args.transaction_id)
    view = await transactions.correct_draft(
        ctx.session,
        ctx.user,
        args.transaction_id,
        **args.model_dump(exclude={"transaction_id"}, exclude_none=True),
    )
    if was_confirmed:
        view = await transactions.confirm_draft(ctx.session, ctx.user, args.transaction_id)
    return ToolResult(
        {
            "id": str(view.id),
            "merchant": view.merchant,
            "amount_sen": view.amount_sen,
            "status": view.status,
        }
    )


async def _create_account(ctx: ToolContext, args: CreateAccountArgs) -> ToolResult:
    view = await accounts.create_account(ctx.session, ctx.user, **args.model_dump())
    return ToolResult({"id": str(view.id), "name": view.name, "kind": view.kind})


async def _update_account(ctx: ToolContext, args: UpdateAccountArgs) -> ToolResult:
    view = await accounts.update_account(
        ctx.session,
        ctx.user,
        args.account_id,
        **args.model_dump(exclude={"account_id"}, exclude_none=True),
    )
    return ToolResult({"id": str(view.id), "name": view.name, "kind": view.kind})


async def _update_profile(ctx: ToolContext, args: UpdateProfileArgs) -> ToolResult:
    user = await update_profile(ctx.session, ctx.user, **args.model_dump(exclude_none=True))
    return ToolResult(
        {
            "display_name": user.display_name,
            "monthly_income_sen": user.monthly_income.sen,
            "next_payday": user.next_payday.isoformat(),
            "cycle_start": user.cycle_start.isoformat(),
            "cycle_days": user.cycle_days,
        }
    )


def _goal_create_summary(args: CreateGoalArgs) -> str:
    return f"Create goal “{args.name}” with target RM{Money(args.target_sen).ringgit_str()}."


def _goal_update_summary(args: UpdateGoalArgs) -> str:
    changes = args.model_dump(exclude={"goal_id"}, exclude_none=True)
    return (
        f"Update goal {args.goal_id}: "
        + ", ".join(f"{key}={value}" for key, value in changes.items())
        + "."
    )


def _contribution_summary(args: GoalContributionArgs) -> str:
    return (
        f"Record RM{Money(args.amount_sen).ringgit_str()} toward goal "
        f"{args.goal_id} on {args.contributed_on}."
    )


def _transaction_update_summary(args: UpdateTransactionArgs) -> str:
    changes = args.model_dump(exclude={"transaction_id"}, exclude_none=True)
    return (
        f"Correct transaction {args.transaction_id}: "
        + ", ".join(f"{key}={value}" for key, value in changes.items())
        + "."
    )


def _create_account_summary(args: CreateAccountArgs) -> str:
    return f"Create zero-balance {args.kind} account “{args.name}”."


def _update_account_summary(args: UpdateAccountArgs) -> str:
    changes = args.model_dump(exclude={"account_id"}, exclude_none=True)
    return (
        f"Update account {args.account_id}: "
        + ", ".join(f"{key}={value}" for key, value in changes.items())
        + "."
    )


def _update_profile_summary(args: UpdateProfileArgs) -> str:
    return (
        "Update profile: "
        + ", ".join(f"{key}={value}" for key, value in args.model_dump(exclude_none=True).items())
        + "."
    )


def generated_specs() -> tuple[ToolSpec, ...]:
    """Emit service-bound write specs from the resource declarations."""
    return (
        _write_spec(
            "goals",
            "create",
            "Create a goal as data without running the planning workflow.",
            CreateGoalArgs,
            _create_goal,
            _goal_create_summary,
            "Creating a goal",
        ),
        _write_spec(
            "goals",
            "update",
            "Rename, reschedule, pause, resume, achieve or retire an existing goal.",
            UpdateGoalArgs,
            _update_goal,
            _goal_update_summary,
            "Updating a goal",
        ),
        ToolSpec(
            "record_goal_contribution",
            MODULE,
            "write",
            "Record money the user says they contributed to a goal.",
            GoalContributionArgs,
            _contribute,
            _contribution_summary,
            "Recording a contribution",
        ),
        ToolSpec(
            "update_transaction",
            MODULE,
            "write",
            "Correct a draft or confirmed transaction in one approved change.",
            UpdateTransactionArgs,
            _update_transaction,
            _transaction_update_summary,
            "Correcting a transaction",
        ),
        _write_spec(
            "accounts",
            "create",
            "Create a zero-balance account; this never creates or moves money.",
            CreateAccountArgs,
            _create_account,
            _create_account_summary,
            "Creating an account",
        ),
        _write_spec(
            "accounts",
            "update",
            "Rename or reclassify an account without changing its balance.",
            UpdateAccountArgs,
            _update_account,
            _update_account_summary,
            "Updating an account",
        ),
        _write_spec(
            "profile",
            "update",
            "Update the display name, income forecast or payday cycle settings.",
            UpdateProfileArgs,
            _update_profile,
            _update_profile_summary,
            "Updating your profile",
        ),
    )


def _write_spec(
    resource_name: str,
    operation: Literal["create", "update"],
    description: str,
    args_model: type[BaseModel],
    handler,
    summarise,
    label: str,
) -> ToolSpec:
    """Create a write spec only where the declaration allows every payload field."""
    resource = RESOURCES[resource_name]
    identifier = f"{resource_name.removesuffix('s')}_id"
    supplied = set(args_model.model_fields) - {identifier}
    undeclared = supplied - set(resource.writable)
    if undeclared:
        raise ValueError(
            f"{operation}_{resource_name} exposes undeclared writes: {sorted(undeclared)}"
        )
    return ToolSpec(
        f"{operation}_{resource_name.removesuffix('s')}",
        MODULE,
        "write",
        description,
        args_model,
        handler,
        summarise,
        label,
    )


SPECS = (
    ToolSpec(
        name="search_records",
        module=MODULE,
        kind="read",
        label="Searching your records",
        description=(
            "Search transactions, goals, bills, accounts, profile or briefing records. "
            "Supports merchant/name text matching, exact values, dates and amount ranges, "
            "status filters, ordering and limits. Use this instead of a narrow list tool when "
            "the question names a merchant, period, range, status or single record."
        ),
        args_model=SearchRecordsArgs,
        handler=_search,
    ),
    *generated_specs(),
)
