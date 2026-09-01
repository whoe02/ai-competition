"""Day-planner endpoint: money-constrained place discovery."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status

from kira.agent import place_relevance, plan_intent
from kira.api.deps import CurrentUser, SessionDep
from kira.api.schemas import (
    DayPlanInterpretRequest,
    DayPlanInterpretResponse,
    DayPlanResponse,
    PlanDraftRequest,
    TransactionResponse,
)
from kira.config import get_settings
from kira.services.clock import today_for
from kira.services.dashboard import today_dashboard
from kira.services.day_plan import add_to_today, find_places
from kira.services.transactions import InvalidTransaction, TransactionView

router = APIRouter(prefix="/v1/day-plan", tags=["day-plan"])


@router.get("/places", response_model=DayPlanResponse)
async def get_places(
    user: CurrentUser,
    session: SessionDep,
    lat: float = Query(...),
    lng: float = Query(...),
    mode: Literal["walk", "transit", "ride"] = "walk",
    halal_only: bool = False,
    cap_sen: int | None = Query(default=None, gt=0),
    radius_km: float = Query(default=5.0, gt=0),
    kind: str | None = Query(default=None, max_length=40),
    request: str | None = Query(default=None, max_length=280),
):
    """The cap only filters the list; the room is what every band is judged on.

    ``kind`` narrows to one sort of food and is echoed back beside the counts,
    because the client cannot read its own state against a list that is still
    in flight: the answer on screen has to say which kind it was actually
    filtered by, exactly as it says which ceiling.

    ``request`` is the user's sentence as they typed it, and the two travel
    together rather than one instead of the other. Where the relevance pass is
    on and a model answers, the sentence is what narrows the list and ``kind``
    narrows nothing; where it is off, or the model cannot be reached, ``kind``
    is the whole of the filter exactly as it has always been. ``ranking`` on the
    response says which of the two the client is looking at.
    """
    dashboard = await today_dashboard(session, user, today_for())
    room_sen = dashboard.safe_today_sen
    cap = cap_sen if cap_sen is not None else room_sen
    # Nothing is handed in while the feature is off, so the search below is the
    # one that ran before any of this was written: no model, no timeout to sit
    # through, and no call on anybody's quota. ``place_relevance.rank`` checks
    # the same setting for itself, which is belt and braces on the one property
    # a teammate sharing this checkout is relying on.
    ranker = place_relevance.rank if get_settings().plan_search_llm_enabled else None
    found = await find_places(
        lat=lat,
        lng=lng,
        mode=mode,
        halal_only=halal_only,
        cap_sen=cap,
        room_sen=room_sen,
        radius_km=radius_km,
        kind=kind,
        request=request or "",
        rank=ranker,
    )
    return {
        "room_sen": room_sen,
        "cap_sen": cap,
        "kind": kind,
        "nearby_count": found.nearby_count,
        "matching_count": found.matching_count,
        "kind_count": found.kind_count,
        "ranking": found.ranking,
        "places": found.places,
        # Handed over in its own field and never appended to ``places``. It is
        # only ever non-empty when the ceiling admitted nothing at all, and a
        # client that draws it has to say what it is: these cost more than the
        # ceiling it was asked for.
        "nearest_over_cap": found.nearest_over_cap,
    }


@router.post("/interpret", response_model=DayPlanInterpretResponse)
async def interpret_filters(body: DayPlanInterpretRequest, user: CurrentUser) -> dict:
    """Read a sentence into the screen's own filters. It writes nothing.

    The controls are the answer. Nothing here composes prose about the places
    themselves, because a paragraph sitting above the chips would be a second
    account of the same list with no way to tell which one the rows came from —
    where a chip that turned itself on is a reading the user can see and undo.

    Either the whole filter set comes back or none of it does. The origin is
    echoed from the request untouched: it belongs to the device or to the KLCC
    fallback, and a model naming somewhere the user did not is the fabrication
    this refuses outright.
    """
    current = plan_intent.Filters(
        lat=body.lat,
        lng=body.lng,
        mode=body.mode,
        halal_only=body.halal_only,
        cap_sen=body.cap_sen,
        kind=body.kind,
        sort=body.sort,
    )
    read = await plan_intent.interpret(body.text, current, currency=user.currency)
    return {
        "applied": read.filters is not None,
        "filters": None if read.filters is None else asdict(read.filters),
        "understood": read.understood,
        "unread": read.unread,
        "reason": read.reason,
    }


@router.post("/drafts", status_code=status.HTTP_201_CREATED, response_model=TransactionResponse)
async def post_plan_draft(
    body: PlanDraftRequest, user: CurrentUser, session: SessionDep
) -> TransactionView:
    """Add a planned outing to today. It waits as a draft until it is confirmed.

    Deliberately not a client POST to /v1/transactions with ``source: "plan"``:
    the date is the server's clock, the confidence band's percentage is the
    server's mapping, and the note that says the money has not moved is the
    server's wording. Left to the client, three things a plan draft depends on
    would be restatable by whoever called it.

    Nothing here touches safe-to-spend, and that is the point rather than an
    omission — a draft is excluded from every engine calculation, so the figure
    on Today is the same after this call as before it.
    """
    try:
        view = await add_to_today(
            session,
            user,
            name=body.name,
            total_sen=body.total_sen,
            confidence=body.confidence,
            today=today_for(),
        )
    except InvalidTransaction as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    return view
