"""A manual trigger for the exact overnight briefing path used by the worker."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from kira.api.deps import CurrentUser, SessionDep
from kira.api.schemas import BriefingInboxResponse, BriefingRunResponse
from kira.services.briefings import briefing_inbox, nightly_briefing
from kira.services.clock import today_for

router = APIRouter(prefix="/v1/briefings", tags=["briefings"])


@router.get("/today", response_model=BriefingInboxResponse | None)
async def get_today_briefing(
    user: CurrentUser, session: SessionDep
) -> BriefingInboxResponse | None:
    """The prepared morning inbox, if the nightly worker has run already."""
    result = await briefing_inbox(session, user, today_for())
    if result is None:
        return None
    return BriefingInboxResponse(
        id=result.id,
        on_date=result.on_date,
        summary=result.summary,
        proposal_count=result.proposal_count,
        pending_proposal_count=result.pending_proposal_count,
    )


@router.post("/run", response_model=BriefingRunResponse, status_code=status.HTTP_201_CREATED)
async def run_briefing(
    response: Response, user: CurrentUser, session: SessionDep
) -> BriefingRunResponse:
    """Run today's worker path now. A retry returns the original briefing."""
    result = await nightly_briefing(session, user, today_for())
    await session.commit()
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return BriefingRunResponse(
        id=result.id,
        on_date=result.on_date,
        summary=result.summary,
        proposal_count=result.proposal_count,
        created=result.created,
    )
