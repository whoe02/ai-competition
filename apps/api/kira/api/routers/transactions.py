"""The ledger: what is waiting, what is settled, and the ways to settle it."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from kira.api.deps import CurrentUser, SessionDep
from kira.api.schemas import (
    ActivityResponse,
    AppliedGoalContributionResponse,
    AppliedGoalIncomeAllocationResponse,
    CorrectTransactionRequest,
    CreateTransactionRequest,
    GoalIncomeAllocationItemResponse,
    GoalIncomeAllocationResponse,
    TransactionResponse,
)
from kira.engine import IncomeAllocationPlan
from kira.services.clock import today_for
from kira.services.goal_allocations import (
    AppliedIncomeAllocation,
    IncomeAlreadyAllocated,
    IncomeNotConfirmed,
    IncomeNotFound,
    apply_income_allocation,
    recommend_income_allocation,
)
from kira.services.transactions import (
    Activity,
    AlreadySettled,
    IncomeAllocationExists,
    InvalidTransaction,
    NotConfirmed,
    TransactionNotFound,
    TransactionView,
    confirm_draft,
    correct_draft,
    create_transaction,
    discard_draft,
    list_activity,
    unconfirm,
)

router = APIRouter(prefix="/v1/transactions", tags=["transactions"])

NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such transaction")
SETTLED = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="That transaction has already been settled"
)
NOT_CONFIRMED = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="That transaction is not on the ledger"
)
# Deliberately not the SETTLED wording: a caller trying to fix a figure needs to
# be told the way back to a row it may fix, not just that this one is shut.
NOT_A_DRAFT = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="Only a draft can be corrected. Unconfirm it first, then correct it.",
)


def _as_of_utc() -> datetime:
    return datetime.combine(today_for(), time.min, tzinfo=UTC)


def _allocation_response(plan: IncomeAllocationPlan) -> GoalIncomeAllocationResponse:
    return GoalIncomeAllocationResponse(
        income_transaction_id=uuid.UUID(plan.income_transaction_id),
        income_amount_sen=plan.income_amount_sen,
        available_for_goals_sen=plan.available_for_goals_sen,
        protected_commitments_sen=plan.protected_commitments_sen,
        emergency_buffer_sen=plan.emergency_buffer_sen,
        allocated_sen=plan.allocated_sen,
        unallocated_income_sen=plan.unallocated_income_sen,
        allocations=[
            GoalIncomeAllocationItemResponse(
                goal_id=uuid.UUID(item.goal_id),
                name=item.name,
                priority=item.priority,
                amount_sen=item.amount_sen,
                income_share_bp=item.income_share_bp,
                remaining_after_sen=item.remaining_after_sen,
            )
            for item in plan.allocations
        ],
        risk_flags=list(plan.risk_flags),
        assumptions=list(plan.assumptions),
        calculation_version=plan.calculation_version,
        evidence_refs=list(plan.evidence_refs),
    )


def _income_error(exc: Exception) -> HTTPException:
    if isinstance(exc, IncomeNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Confirmed income not found")
    if isinstance(exc, IncomeNotConfirmed):
        return HTTPException(status.HTTP_409_CONFLICT, "Confirm this income first")
    return HTTPException(status.HTTP_409_CONFLICT, "This income has already been allocated")


@router.get("", response_model=ActivityResponse)
async def get_activity(
    user: CurrentUser,
    session: SessionDep,
    category: Annotated[str | None, Query(max_length=40)] = None,
) -> Activity:
    """The ledger, optionally narrowed to one category. Drafts and chips are never narrowed."""
    return await list_activity(session, user, category)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TransactionResponse)
async def post_transaction(
    body: CreateTransactionRequest, user: CurrentUser, session: SessionDep
) -> TransactionView:
    """Add spending. It lands as a draft whatever route it came in by."""
    try:
        view = await create_transaction(
            session,
            user,
            merchant=body.merchant,
            amount_sen=body.amount_sen,
            occurred_on=body.occurred_on,
            category=body.category,
            source=body.source,
            confidence=body.confidence,
            note=body.note,
            direction=body.direction,
            income_type=body.income_type,
        )
    except InvalidTransaction as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    return view


@router.get(
    "/{transaction_id}/goal-allocation",
    response_model=GoalIncomeAllocationResponse,
)
async def get_goal_allocation(
    transaction_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> GoalIncomeAllocationResponse:
    """Preview the server-calculated split. This endpoint never writes."""
    try:
        plan = await recommend_income_allocation(session, user, transaction_id, _as_of_utc())
    except (IncomeNotFound, IncomeNotConfirmed, IncomeAlreadyAllocated) as exc:
        raise _income_error(exc) from exc
    return _allocation_response(plan)


@router.post(
    "/{transaction_id}/goal-allocation/approve",
    response_model=AppliedGoalIncomeAllocationResponse,
)
async def post_goal_allocation_approval(
    transaction_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> AppliedGoalIncomeAllocationResponse:
    """Recalculate and atomically earmark the approved contribution split."""
    try:
        result: AppliedIncomeAllocation = await apply_income_allocation(
            session, user, transaction_id, _as_of_utc()
        )
    except (IncomeNotFound, IncomeNotConfirmed, IncomeAlreadyAllocated) as exc:
        raise _income_error(exc) from exc
    return AppliedGoalIncomeAllocationResponse(
        plan=_allocation_response(result.plan),
        contributions=[
            AppliedGoalContributionResponse.model_validate(item)
            for item in result.contributions
        ],
    )


@router.patch("/{transaction_id}", response_model=TransactionResponse)
async def patch_transaction(
    transaction_id: uuid.UUID,
    body: CorrectTransactionRequest,
    user: CurrentUser,
    session: SessionDep,
) -> TransactionView:
    """Correct a draft that was read wrong. Nothing already settled is editable.

    No audit event: neither create nor any of the settle paths below writes one,
    and a lone entry for corrections would read as a complete trail that is not.
    """
    try:
        view = await correct_draft(
            session,
            user,
            transaction_id,
            merchant=body.merchant,
            amount_sen=body.amount_sen,
            category=body.category,
            note=body.note,
        )
    except TransactionNotFound as exc:
        raise NOT_FOUND from exc
    except AlreadySettled as exc:
        raise NOT_A_DRAFT from exc
    except InvalidTransaction as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    return view


@router.post("/{transaction_id}/confirm", response_model=TransactionResponse)
async def post_confirm(
    transaction_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> TransactionView:
    try:
        view = await confirm_draft(session, user, transaction_id)
    except TransactionNotFound as exc:
        raise NOT_FOUND from exc
    except AlreadySettled as exc:
        raise SETTLED from exc
    await session.commit()
    return view


@router.post("/{transaction_id}/discard", response_model=TransactionResponse)
async def post_discard(
    transaction_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> TransactionView:
    try:
        view = await discard_draft(session, user, transaction_id)
    except TransactionNotFound as exc:
        raise NOT_FOUND from exc
    except AlreadySettled as exc:
        raise SETTLED from exc
    await session.commit()
    return view


@router.post("/{transaction_id}/unconfirm", response_model=TransactionResponse)
async def post_unconfirm(
    transaction_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> TransactionView:
    try:
        view = await unconfirm(session, user, transaction_id)
    except TransactionNotFound as exc:
        raise NOT_FOUND from exc
    except NotConfirmed as exc:
        raise NOT_CONFIRMED from exc
    except IncomeAllocationExists as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This income already funds goals; reverse those contributions first",
        ) from exc
    await session.commit()
    return view
