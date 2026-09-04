"""Nearby places, ranked by what they would cost against today's room.

Reads through the same `kira.services.day_plan` the day-planner screen uses,
so the Butler's idea of what an outing costs cannot drift from the app's.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from kira.agent.agents.day_plan import run_day_plan_agent
from kira.agent.tools.spec import EvidenceRow, ToolContext, ToolResult, ToolSpec, money_str
from kira.money import Money
from kira.services import day_plan as day_plan_service

MODULE = "day_plan"

# Suria KLCC — the prototype's own fallback for a user who has not shared their
# location. The maps adapter covers the whole city, so this is a starting point
# rather than the one spot its places cluster around.
_KLCC_LAT = 3.1577
_KLCC_LNG = 101.7120

# Twelve rather than five. Five cheapest was a list the model could not choose
# from: it saw the bottom of the price order and nothing else, so "the cheapest
# one" was the only recommendation available to it. Twelve is enough of the
# range to pick from and still short enough to read.
PLACES_SHOWN = 12

# Written into the argument description at import, from the data rather than
# from memory. A model reads this list to decide what to pass, and a word that
# is not in it matches nothing — so the list has to be the one the places
# actually carry, not a second copy of it that drifts when the file is
# regenerated.
_KINDS = ", ".join(day_plan_service.known_kinds())


class PlanArgs(BaseModel):
    lat: float = Field(
        default=_KLCC_LAT, description="Latitude to search from. Defaults to KLCC."
    )
    lng: float = Field(
        default=_KLCC_LNG, description="Longitude to search from. Defaults to KLCC."
    )
    mode: Literal["walk", "transit", "ride"] = Field(
        default="walk", description="How the user would travel there."
    )
    halal_only: bool = Field(default=False, description="Only show halal places.")
    cap_sen: int | None = Field(
        default=None,
        gt=0,
        description=(
            "A display ceiling on total outing cost, in sen. Leave unset to use "
            "today's safe-to-spend."
        ),
    )
    kind: str | None = Field(
        default=None,
        max_length=40,
        description=(
            "One kind of food, when the user asked for one — 'I want noodles', "
            "'somewhere Japanese'. Leave unset for everything.\n"
            f"It must be one of the words the places themselves carry: {_KINDS}. "
            "Anything else matches nothing and the search comes back empty: it "
            "is not free text, and the list is never widened back out to cover "
            "a word that missed. So do not invent a category — 'hawker', "
            "'healthy' and 'street food' are not in that list. When the user "
            "wants something the list has no word for, leave this unset rather "
            "than guessing at the nearest category."
        ),
    )


class DayPlanIntent(PlanArgs):
    """What the Butler hands the planner: the filters, and the sentence.

    Subclassed rather than restated so there is one description of what a
    ceiling in sen is. `request` is the part the Butler cannot turn into a
    filter — "somewhere I can sit for a while", "I'm meeting someone" — and it
    reaches the turn that chooses between the places, which is the only turn
    that could act on it.
    """

    request: str = Field(
        default="",
        max_length=200,
        description=(
            "What the user asked for, in their own words. Copy the sentence; do "
            "not summarise it and do not add to it."
        ),
    )


class AddPlaceArgs(BaseModel):
    place_id: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "The id of one of the places the planner reported. The id, not the "
            "name and not its position in the list."
        ),
    )
    name: str = Field(
        min_length=1,
        max_length=120,
        description="That place's name, exactly as the plan gave it.",
    )
    total_sen: int = Field(
        gt=0,
        description=(
            "The whole outing in sen, meal and travel together — the place's "
            "total_sen from the plan, not the meal on its own."
        ),
    )
    lat: float = Field(
        default=_KLCC_LAT, description="The latitude the plan was built from."
    )
    lng: float = Field(
        default=_KLCC_LNG, description="The longitude the plan was built from."
    )


async def run_search(
    ctx: ToolContext,
    args: PlanArgs,
    *,
    request: str = "",
    rank: day_plan_service.PlaceRanker | None = None,
) -> ToolResult:
    """The deterministic half of the planner: measured, ranked, no model.

    Public because the Planner agent calls it. It is the same call the Plan
    screen makes through `kira.services.day_plan`, so the Butler's idea of what
    an outing costs cannot drift from the app's.
    """
    room_sen = ctx.dashboard.safe_today_sen
    cap_sen = args.cap_sen if args.cap_sen is not None else room_sen
    found = await day_plan_service.find_places(
        lat=args.lat,
        lng=args.lng,
        mode=args.mode,
        halal_only=args.halal_only,
        cap_sen=cap_sen,
        room_sen=room_sen,
        kind=args.kind,
        request=request,
        rank=rank,
    )
    # Sorted by total cost by the service, and handed over in that order: these
    # are the cheapest twelve, cheapest first, and the model is told as much
    # below so it does not read the top of the list as a recommendation.
    top = found.places[:PLACES_SHOWN]
    currency = ctx.currency

    def money(sen: int) -> str:
        return money_str(Money(sen, currency))

    def row(place: day_plan_service.EvaluatedPlace) -> dict:
        return {
            "id": place.id,
            "name": place.name,
            "kind": place.kind,
            "address": place.address,
            "km": place.km,
            # The model is told which distance produced the fare so it
            # cannot narrate a straight-line estimate as a quoted price.
            "road_km": place.road_km,
            "distance_basis": place.distance_basis,
            "travel_sen": place.travel_sen,
            "minutes": place.minutes,
            "total_sen": place.total_sen,
            "share": place.share,
            "band": place.band,
            "confidence": place.confidence,
            "halal": place.halal,
            "note": place.note,
            "match_basis": place.match_basis,
            "match_strength": place.match_strength,
            "match_reason": place.match_reason,
        }

    # The room is stated rather than left in the shares: on a day already spent
    # out every share is null, and a model given only those would have nothing
    # to quote but a figure it made up. The three counts are stated for the same
    # reason: an empty list otherwise reads as a ceiling problem even when the
    # user is nowhere near anything the adapter knows, is standing beside a
    # place their own halal filter took out, or asked for a kind of food that
    # is not around here.
    value = {
        "room_sen": room_sen,
        "cap_sen": cap_sen,
        "kind": args.kind,
        "nearby_count": found.nearby_count,
        "matching_count": found.matching_count,
        "kind_count": found.kind_count,
        # How many came back against how many there were, so a list that was cut
        # at twelve is not read as the whole of what the search found.
        "shown_count": len(top),
        "total_under_cap": len(found.places),
        # Every kind in range with the cheapest whole outing of each, ceiling
        # and kind filter both ignored. This is what lets an empty list be
        # answered with what the ceiling excluded rather than with an apology:
        # "RM15 reaches the mamak and the food courts; the Japanese places
        # start at RM42." Nothing here may be quoted as a place — a row is a
        # price, and the names are all in ``places``.
        "price_landscape": [
            {
                "kind": row.kind,
                "count": row.count,
                "cheapest_total_sen": row.cheapest_total_sen,
            }
            for row in found.landscape
        ],
        "places": [row(place) for place in top],
        # Only ever populated where ``places`` came back empty, and kept out of
        # ``places`` so that the model cannot read one list where there are two.
        # Every one of these costs more than ``cap_sen``; they are here because
        # "nothing under RM10" leaves the user with nowhere to eat and the
        # search already knows what the nearest thing costs.
        "nearest_over_cap": [row(place) for place in found.nearest_over_cap],
        # Only ever populated where a narrowed search came back with few places
        # inside the radius, and kept out of ``places`` for the same reason: a
        # model reading one list where there are two would recommend a place
        # twice as far away as the user asked for and never mention it. Every
        # figure on them is measured for that longer journey.
        "nearest_beyond_radius": [row(place) for place in found.nearest_beyond_radius],
        # Only ever populated where a kind was asked for, and every one of
        # these is a place that kind did not match. Nearest first rather than
        # cheapest -- being right here is what a near miss has going for it.
        # They carry their real kind like any other row, because that is the
        # word the panel will show whatever the answer says about the menu.
        "near_misses": [row(place) for place in found.near_misses],
    }

    # Labelled as the dashboard tool labels it, so the two collapse into one row
    # rather than reading as two figures that happen to agree.
    room_row = EvidenceRow("Safe to spend today", money(room_sen))
    if top:
        best = top[0]
        evidence = (
            room_row,
            EvidenceRow("Cheapest nearby", best.name),
            EvidenceRow("Total cost", money(best.total_sen)),
            # Named beside the cost it produced. A fare measured in a straight
            # line understates a real KL journey, and the row is what stops the
            # figure above it reading as a quote.
            EvidenceRow(
                "Distance measured",
                (
                    f"{best.km:.1f} km by road"
                    if best.distance_basis == "road"
                    else f"{best.km:.1f} km in a straight line"
                ),
            ),
            EvidenceRow("Fits today's room", best.band),
        )
        if best.match_basis is not None:
            matched_on = {
                "tagged": f"{args.kind} — tagged",
                "inferred": f"{args.kind} — believed, not tagged",
                "judged": best.match_reason,
            }[best.match_basis]
            evidence += (EvidenceRow("Matched on", matched_on),)
    elif found.nearby_count == 0:
        evidence = (room_row, EvidenceRow("Nearby places", "none within range"))
    elif found.matching_count == 0:
        # Only reachable with halal_only on, so naming it is a statement of what
        # the filter did, not a guess at why the list came back empty.
        evidence = (
            room_row,
            EvidenceRow(
                "Nearby places",
                f"{found.nearby_count} within range, none of them halal",
            ),
        )
    elif found.kind_count == 0:
        # Only reachable with a kind asked for, and the ceiling is not what did
        # this: there is other food in range at prices nobody has looked at yet.
        evidence = (
            room_row,
            EvidenceRow(
                "Nearby places",
                f"{found.matching_count} within range, none of them {args.kind}",
            ),
        )
    else:
        # Counted over the kind that was asked for, not over everything in
        # range. "7 within range, none under the ceiling" is false where six of
        # the seven are cheap and simply not Japanese.
        within = (
            f"{found.matching_count} within range"
            if args.kind is None
            else f"{found.kind_count} {args.kind} within range"
        )
        evidence = (
            room_row,
            EvidenceRow("Nearby places", f"{within}, none under the ceiling"),
        )
        # The panel's job is to back what the answer says, and what the answer
        # says here is a name and a price. Labelled as the closest above the
        # ceiling rather than as the cheapest nearby, so a reader skimming the
        # panel alone cannot take it for something that fitted.
        if found.nearest_over_cap:
            closest = found.nearest_over_cap[0]
            evidence += (
                EvidenceRow(
                    "Closest above the ceiling",
                    f"{closest.name} at {money(closest.total_sen)}",
                ),
                EvidenceRow("Over the ceiling by", money(closest.total_sen - cap_sen)),
            )

    # Every near miss gets a row, and the row states the kind the data gives
    # it. That is the whole guard on the one thing the model is allowed to know
    # better than the tags: it may suggest that the burger place also does
    # chicken, and the panel underneath will go on saying "McDonald's ·
    # Burgers · RM18.00" -- the claim stays the model's, the category stays the
    # data's, and the price is the one this search measured rather than one
    # remembered off a menu. Rows for all of them, not just the one that gets
    # named, because which one that is cannot be known until after the answer
    # is written.
    evidence += tuple(
        EvidenceRow("Also nearby", f"{place.name} · {place.kind} · {money(place.total_sen)}")
        for place in found.near_misses
    )

    # One row each, and the distance on every one of them. These are the places
    # the radius excluded, so how far out they are is the figure that makes the
    # row honest: a name and a price alone would read exactly like a row from
    # the list above, which is the one thing this group must never do. The
    # distance is the real one for the journey, measured like every other.
    evidence += tuple(
        EvidenceRow(
            "Further out",
            f"{place.name} · {place.kind} · {place.km:.1f} km · {money(place.total_sen)}",
        )
        for place in found.nearest_beyond_radius
    )

    return ToolResult(value, evidence)


async def _add_place(ctx: ToolContext, args: AddPlaceArgs) -> ToolResult:
    place = day_plan_service.find_place(args.place_id, lat=args.lat, lng=args.lng)
    if place is None:
        # The guard refuses an unknown id before a card is ever raised, and the
        # approval refuses it again on resume, so getting here means the curated
        # set moved underneath a card already on screen. Failing is the only
        # honest answer left: the alternative is a draft for a place that is no
        # longer anywhere I can point at.
        raise day_plan_service.UnknownPlace(args.place_id)

    # Straight through the service the screen's own "Add to today" calls, so the
    # date, the plan labelling, the note and the draft invariant are the same
    # ones rather than a second set that agrees today. The band is the curated
    # place's, never the model's -- a percentage is not something it may assert.
    #
    # The name and the total are the approved ones and not the place's, because
    # the card is this path's equivalent of the row that was tapped: what the
    # user read is what lands, and an edited card is the user correcting it.
    view = await day_plan_service.add_to_today(
        ctx.session,
        ctx.user,
        name=args.name,
        total_sen=args.total_sen,
        confidence=place.confidence,
        today=ctx.today,
    )
    currency = ctx.currency
    return ToolResult(
        {
            "id": str(view.id),
            "merchant": view.merchant,
            "amount_sen": view.amount_sen,
            "status": view.status,
            "source": view.source,
            "confidence": view.confidence,
        },
        (
            EvidenceRow(view.merchant, money_str(Money(view.amount_sen, currency))),
            EvidenceRow("Waiting as", "a draft in Activity"),
            # Stated after the write, and unchanged by it. A draft is outside
            # every engine calculation, so the figure here is the same one the
            # card was read against.
            EvidenceRow(
                "Safe to spend today",
                money_str(Money(ctx.dashboard.safe_today_sen, currency)),
            ),
        ),
    )


def _summarise_add_place(args: AddPlaceArgs) -> str:
    return (
        f"Add {args.name} for RM{Money(args.total_sen).ringgit_str()} to today as a "
        "draft. Nothing counts against today until you confirm it."
    )


async def _never_execute(_: ToolContext, __: DayPlanIntent) -> ToolResult:
    """Workflow calls are consumed by the graph guard, never by the tool runner."""
    raise RuntimeError("start_day_planning must be routed as a workflow")


SPECS = (
    ToolSpec(
        name="start_day_planning",
        module=MODULE,
        kind="workflow",
        label="Finding places nearby",
        # Short on purpose, and the point of the whole change. What used to
        # stand here was 4,792 characters — about how to choose a place, what
        # `near_misses` means, when world knowledge about a menu may be
        # offered — bound to every reasoning turn the Butler took, about
        # anything. All of it is now the planner's own prompt, read by the turn
        # it applies to. What the Butler needs to know is when to hand over.
        description=(
            "Hand a question about where to eat or go to the planner. It searches "
            "the curated places near a location, prices the whole outing against "
            "today's safe-to-spend, chooses one and reports back with the figures. "
            "Call it for 'where can I eat', 'what can I afford for lunch nearby', "
            "'I feel like noodles', or any question about going somewhere near a "
            "given location. Pass the user's own sentence as `request`, and set a "
            "filter only where they asked for one. Do not pick a place yourself and "
            "do not quote a price — that is what it comes back with."
        ),
        args_model=DayPlanIntent,
        handler=_never_execute,
        agent=run_day_plan_agent,
    ),
    ToolSpec(
        name="add_place_to_today",
        module=MODULE,
        kind="write",
        label="Adding a place to today",
        description=(
            "Put one of the planner's places on today as a draft. Call this for "
            "'add the second one', 'put that down for lunch', 'yes, that one', or "
            "any agreement to a place you just recommended. Pass its id and the same "
            "lat/lng the plan was built from. It waits in Activity and moves nothing "
            "until the user confirms it.\n"
            "Offer it in the same breath as the recommendation rather than waiting to "
            "be asked, and call it the moment they agree."
        ),
        args_model=AddPlaceArgs,
        handler=_add_place,
        summarise=_summarise_add_place,
    ),
)
