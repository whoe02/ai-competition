"""Persistent state: financial rows, and the Butler's threads, memory and approvals."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kira.db.base import Base
from kira.db.types import MoneyType
from kira.money import Money

TXN_DRAFT = "draft"
TXN_CONFIRMED = "confirmed"
TXN_DISCARDED = "discarded"
TXN_STATUSES = (TXN_DRAFT, TXN_CONFIRMED, TXN_DISCARDED)

SOURCE_MANUAL = "manual"
SOURCE_RECEIPT = "receipt"
SOURCE_VOICE = "voice"
SOURCE_IMPORT = "import"
# The odd one out, and deliberately so: the four above are all a record of money
# that has already left, read by a machine or typed by hand. A plan is money the
# user intends to spend. It is a draft for the same reason the others are — it
# is a proposal, not a fact — but the proposal is about the future, so the copy
# that carries it must never suggest the money is already gone or set aside.
SOURCE_PLAN = "plan"

HORIZON_SHORT = "short"
HORIZON_LONG = "long"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(tz=UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(80))
    currency: Mapped[str] = mapped_column(String(3), default="MYR")
    buffer: Mapped[Money] = mapped_column(MoneyType(), default=lambda: Money(0))
    # What lands on payday. Zero until a user says otherwise: safe_to_spend never
    # needed it, because it never looks past the next payday. A projection does.
    monthly_income: Mapped[Money] = mapped_column(MoneyType(), default=lambda: Money(0))
    next_payday: Mapped[date] = mapped_column(Date)
    cycle_start: Mapped[date] = mapped_column(Date)
    cycle_days: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    accounts: Mapped[list[Account]] = relationship(back_populates="user", lazy="selectin")
    commitments: Mapped[list[Commitment]] = relationship(back_populates="user", lazy="selectin")
    goals: Mapped[list[Goal]] = relationship(back_populates="user", lazy="selectin")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(24))  # bank | ewallet | cash
    opening_balance: Mapped[Money] = mapped_column(MoneyType())

    user: Mapped[User] = relationship(back_populates="accounts")


class Commitment(Base):
    __tablename__ = "commitments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    amount: Mapped[Money] = mapped_column(MoneyType())
    due_date: Mapped[date] = mapped_column(Date, index=True)
    protected: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="commitments")


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    horizon: Mapped[str] = mapped_column(String(8))  # short | long
    target: Mapped[Money] = mapped_column(MoneyType())
    saved: Mapped[Money] = mapped_column(MoneyType())
    monthly: Mapped[Money] = mapped_column(MoneyType())
    # A goal without a date is projected but carries no probability: "will I make
    # it" is not a question until there is a "by when".
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    # The legacy horizon/monthly fields above remain the dashboard projection.
    # Planning uses the actual target date and a versioned GoalPlanRecord.
    goal_type: Mapped[str] = mapped_column(String(40), default="custom_goal", index=True)
    currency: Mapped[str] = mapped_column(String(3), default="MYR")
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    priority: Mapped[str] = mapped_column(String(12), default="flexible", index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    funding_account_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    user: Mapped[User] = relationship(back_populates="goals")
    plans: Mapped[list[GoalPlanRecord]] = relationship(
        back_populates="goal", cascade="all, delete-orphan", lazy="selectin"
    )


class GoalPlanRecord(Base):
    """An immutable calculation result; a new version is inserted, never updated."""

    __tablename__ = "goal_plans"
    __table_args__ = (UniqueConstraint("goal_id", "version", name="uq_goal_plans_goal_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    goal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("goals.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    approval_status: Mapped[str] = mapped_column(String(12), default="draft", index=True)
    feasible: Mapped[bool] = mapped_column(Boolean)
    target_amount: Mapped[Money] = mapped_column(MoneyType())
    current_saved: Mapped[Money] = mapped_column(MoneyType())
    remaining_amount: Mapped[Money] = mapped_column(MoneyType())
    required_contribution_per_payday: Mapped[Money] = mapped_column(MoneyType())
    next_required_reserve: Mapped[Money] = mapped_column(MoneyType())
    target_date: Mapped[date] = mapped_column(Date)
    projected_completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    risk_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    assumptions: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    calculation_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    goal: Mapped[Goal] = relationship(back_populates="plans")
    scenarios: Mapped[list[GoalScenarioRecord]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin"
    )
    milestones: Mapped[list[GoalMilestoneRecord]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin"
    )


class GoalScenarioRecord(Base):
    __tablename__ = "goal_scenarios"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("goal_plans.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(60))
    feasible: Mapped[bool] = mapped_column(Boolean)
    contribution_per_payday: Mapped[Money] = mapped_column(MoneyType())
    target_date: Mapped[date] = mapped_column(Date)
    goal_delay_days: Mapped[int] = mapped_column(Integer)
    flexible_spending_delta: Mapped[Money] = mapped_column(MoneyType())
    tradeoffs: Mapped[list[str]] = mapped_column(JSON, default=list)
    risk_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    calculation_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    plan: Mapped[GoalPlanRecord] = relationship(back_populates="scenarios")


class GoalMilestoneRecord(Base):
    __tablename__ = "goal_milestones"
    __table_args__ = (
        UniqueConstraint("plan_id", "percentage", name="uq_goal_milestones_plan_percentage"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("goal_plans.id", ondelete="CASCADE"), index=True
    )
    percentage: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Money] = mapped_column(MoneyType())
    projected_date: Mapped[date] = mapped_column(Date)

    plan: Mapped[GoalPlanRecord] = relationship(back_populates="milestones")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    merchant: Mapped[str] = mapped_column(String(120))
    amount: Mapped[Money] = mapped_column(MoneyType())
    category: Mapped[str] = mapped_column(String(40), default="Uncategorised")
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(12), default=TXN_DRAFT, index=True)
    source: Mapped[str] = mapped_column(String(12), default=SOURCE_MANUAL)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    # Client-side default: server now() is transaction time, so rows written in one
    # commit would tie and the ledger's within-day order would be undefined.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )


# ── Butler ────────────────────────────────────────────────────────────────────
# The agent's own durable state. Nothing here holds money; the Butler reaches
# financial rows only through services, and only after an approval.

MEMORY_ACTIVE = "active"
MEMORY_SUPERSEDED = "superseded"
MEMORY_DELETED = "deleted"

MEMORY_KINDS = ("preference", "constraint", "context", "person", "pattern")

APPROVAL_PENDING = "pending"
APPROVAL_APPLIED = "applied"
APPROVAL_REJECTED = "rejected"
APPROVAL_EXPIRED = "expired"

ROLE_USER = "user"
ROLE_KIRA = "kira"


class ButlerThread(Base):
    """One conversation. One per user by default, but the model allows more."""

    __tablename__ = "butler_threads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(120), default="Butler")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ButlerMessage(Base):
    """A turn. Evidence is stored as it was produced, not re-derived on read."""

    __tablename__ = "butler_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("butler_threads.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(8))  # user | kira
    content: Mapped[str] = mapped_column(Text, default="")
    # [[label, value], …] exactly as the executed tools returned them.
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    tool_calls: Mapped[list] = mapped_column(JSON, default=list)
    # Receipt or voice capture that produced this turn, when there was one.
    attachment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ButlerMemory(Base):
    """A durable fact about the user, superseded rather than overwritten."""

    __tablename__ = "butler_memories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), index=True)
    subject: Mapped[str] = mapped_column(String(80))
    fact: Mapped[str] = mapped_column(Text)
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    confidence: Mapped[int] = mapped_column(Integer, default=70)
    status: Mapped[str] = mapped_column(String(12), default=MEMORY_ACTIVE, index=True)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ButlerApproval(Base):
    """A projection of a LangGraph interrupt: what was proposed, and what became of it."""

    __tablename__ = "butler_approvals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("butler_threads.id", ondelete="CASCADE"), index=True
    )
    tool: Mapped[str] = mapped_column(String(60))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(12), default=APPROVAL_PENDING, index=True)
    # The checkpointer's key for the paused run, so a decision resumes the graph.
    graph_thread_id: Mapped[str] = mapped_column(String(80))
    tool_call_id: Mapped[str] = mapped_column(String(80), default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    audit_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditEvent(Base):
    """Who did what, and to which row. Append-only by convention."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    actor: Mapped[str] = mapped_column(String(16))  # user | butler
    action: Mapped[str] = mapped_column(String(60), index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


ADVICE_SOURCE_WORKER = "worker"
ADVICE_SOURCE_SEED = "seed"


class DailyAdvice(Base):
    """What Kira advised on a day, and the exact snapshot she advised it from.

    ``safe_today`` is computed on read and stored nowhere else, so without this
    row a past day's advice could only be reconstructed — and a reconstruction
    would silently use today's goals and commitments instead of that day's.
    """

    __tablename__ = "daily_advice"
    __table_args__ = (UniqueConstraint("user_id", "on_date", name="uq_daily_advice_user_date"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    on_date: Mapped[date] = mapped_column(Date, index=True)
    safe_today: Mapped[Money] = mapped_column(MoneyType())
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(8), default=ADVICE_SOURCE_WORKER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Briefing(Base):
    """One idempotent overnight briefing per user and local calendar day."""

    __tablename__ = "briefings"
    __table_args__ = (UniqueConstraint("user_id", "on_date", name="uq_briefings_user_date"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    on_date: Mapped[date] = mapped_column(Date, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    proposal_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
