"""The single idempotent path used by the scheduler and manual briefing run."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kira.db.models import (
    ADVICE_SOURCE_WORKER,
    APPROVAL_PENDING,
    ROLE_KIRA,
    TXN_DRAFT,
    Briefing,
    ButlerApproval,
    DailyAdvice,
    Transaction,
    User,
)
from kira.engine import safe_to_spend
from kira.engine.detectors import (
    DetectorHit,
    buffer_breach_ahead,
    commitment_due_unfunded,
    spend_pattern_anomaly,
    unconfirmed_drafts_piling,
)
from kira.engine.projection import simulate
from kira.money import Money
from kira.services import butler_approvals, butler_thread
from kira.services.advice import snapshot_json
from kira.services.behaviour import build_profile
from kira.services.snapshot import load_snapshot


@dataclass(frozen=True, slots=True)
class BriefingRun:
    id: uuid.UUID
    on_date: date
    summary: str
    proposal_count: int
    created: bool


@dataclass(frozen=True, slots=True)
class BriefingInbox:
    id: uuid.UUID
    on_date: date
    summary: str
    proposal_count: int
    pending_proposal_count: int


def _summary(on_date: date, hits: list[DetectorHit], proposal_count: int) -> str:
    if not hits:
        return f"Your {on_date.isoformat()} money check is complete. Nothing needs attention."
    titles = "; ".join(hit.title for hit in hits)
    proposal = (
        f" I left {proposal_count} draft confirmation{'s' if proposal_count != 1 else ''} for you."
        if proposal_count
        else ""
    )
    return f"Your {on_date.isoformat()} money check: {titles}.{proposal}"


async def nightly_briefing(session: AsyncSession, user: User, on_date: date) -> BriefingRun:
    """Create a daily advice record, briefing message and safe pending proposals.

    The initial lookup is the normal retry path: a job that fires twice has no
    reason to create a second message, proposal, or financial side effect.
    This function does not commit; its caller owns the transaction boundary.
    """
    existing = (
        await session.execute(
            select(Briefing).where(Briefing.user_id == user.id, Briefing.on_date == on_date)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return BriefingRun(
            id=existing.id,
            on_date=existing.on_date,
            summary=existing.summary,
            proposal_count=existing.proposal_count,
            created=False,
        )

    snapshot = await load_snapshot(session, user, on_date)
    advice = (
        await session.execute(
            select(DailyAdvice).where(
                DailyAdvice.user_id == user.id,
                DailyAdvice.on_date == on_date,
            )
        )
    ).scalar_one_or_none()
    if advice is None:
        session.add(
            DailyAdvice(
                user_id=user.id,
                on_date=on_date,
                safe_today=safe_to_spend(snapshot).safe_today,
                snapshot=snapshot_json(snapshot),
                source=ADVICE_SOURCE_WORKER,
            )
        )

    profile = await build_profile(session, user, on_date)
    simulation = simulate(snapshot, profile, days=90, trials=400)
    hits = [
        hit
        for hit in (
            buffer_breach_ahead(simulation.bands, snapshot.buffer, on_date + timedelta(days=1)),
            spend_pattern_anomaly(
                snapshot.spent_today,
                Money(profile.median_for(on_date.weekday()), user.currency),
            ),
            commitment_due_unfunded(snapshot),
        )
        if hit is not None
    ]

    drafts = (
        await session.execute(
            select(Transaction)
            .where(Transaction.user_id == user.id, Transaction.status == TXN_DRAFT)
            .order_by(Transaction.created_at, Transaction.id)
        )
    ).scalars().all()
    draft_hit = unconfirmed_drafts_piling(len(drafts))
    if draft_hit is not None:
        hits.append(draft_hit)

    thread = await butler_thread.ensure_thread(session, user)
    proposal_count = 0
    if draft_hit is not None:
        graph_thread_id = f"briefing:{on_date.isoformat()}"
        for draft in drafts:
            await butler_approvals.propose(
                session,
                user,
                thread_id=thread.id,
                tool="confirm_draft",
                args={"transaction_id": str(draft.id)},
                summary=f"Confirm {draft.merchant} for {draft.amount}.",
                evidence=[
                    ["Draft waiting", draft.merchant],
                    ["Amount", str(draft.amount)],
                    ["Why now", "It is excluded from today’s available balance until confirmed."],
                ],
                graph_thread_id=graph_thread_id,
                tool_call_id=f"draft:{draft.id}",
            )
            proposal_count += 1

    summary = _summary(on_date, hits, proposal_count)
    briefing = Briefing(
        user_id=user.id,
        on_date=on_date,
        summary=summary,
        proposal_count=proposal_count,
    )
    session.add(briefing)
    await butler_thread.append(
        session,
        user,
        thread,
        role=ROLE_KIRA,
        content=summary,
        evidence=[[hit.title, hit.detail] for hit in hits],
    )
    await session.flush()
    return BriefingRun(
        id=briefing.id,
        on_date=briefing.on_date,
        summary=briefing.summary,
        proposal_count=briefing.proposal_count,
        created=True,
    )


async def briefing_inbox(
    session: AsyncSession, user: User, on_date: date
) -> BriefingInbox | None:
    """Return today's briefing and only the approvals created by that briefing."""
    briefing = (
        await session.execute(
            select(Briefing).where(Briefing.user_id == user.id, Briefing.on_date == on_date)
        )
    ).scalar_one_or_none()
    if briefing is None:
        return None
    pending = (
        await session.execute(
            select(func.count())
            .select_from(ButlerApproval)
            .where(
                ButlerApproval.user_id == user.id,
                ButlerApproval.status == APPROVAL_PENDING,
                ButlerApproval.graph_thread_id == f"briefing:{on_date.isoformat()}",
            )
        )
    ).scalar_one()
    return BriefingInbox(
        id=briefing.id,
        on_date=briefing.on_date,
        summary=briefing.summary,
        proposal_count=briefing.proposal_count,
        pending_proposal_count=pending,
    )
