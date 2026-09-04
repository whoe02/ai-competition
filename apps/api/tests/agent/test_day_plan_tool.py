"""What start_day_planning hands the model, which is the only thing it can quote.

The places come from the ``place_world`` fixture, not the shipped KL set: the
screen and the Butler have to tell the same story about an empty list, and that
agreement is what these tests are for -- not which places OpenStreetMap had.
"""

from __future__ import annotations

import pytest

from kira.agent.agents.day_plan import SELECTION, PlaceChoice, _by_id, _named
from kira.agent.tools import ToolContext
from kira.agent.tools.day_plan import SPECS, PlanArgs, run_search
from kira.db.models import TXN_CONFIRMED, Transaction
from kira.money import Money
from kira.services import day_plan as day_plan_service
from kira.services.dashboard import today_dashboard
from kira.services.snapshot import load_snapshot
from tests.conftest import StubRouting, serving


async def context_for(session, user, today) -> ToolContext:
    return ToolContext(
        session=session,
        user=user,
        today=today,
        snapshot=await load_snapshot(session, user, today),
        dashboard=await today_dashboard(session, user, today),
    )


async def spend_out(session, user, today) -> None:
    session.add(
        Transaction(
            user_id=user.id,
            merchant="Blowout",
            amount=Money(500_000, user.currency),
            occurred_on=today,
            category="food",
            status=TXN_CONFIRMED,
            source="manual",
            note="",
        )
    )
    await session.commit()


@pytest.fixture
async def user(butler):
    return butler[0]


class TestFiguresGivenToTheModel:
    async def test_the_room_and_the_cap_are_stated_outright(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await run_search(context, PlanArgs(**place_world.origin))

        assert result.value["room_sen"] == context.dashboard.safe_today_sen
        assert result.value["cap_sen"] == context.dashboard.safe_today_sen
        assert result.value["places"]

    async def test_a_spent_out_day_carries_no_share_to_read_as_a_percentage(
        self, session, user, today, place_world
    ):
        await spend_out(session, user, today)
        context = await context_for(session, user, today)
        result = await run_search(context, PlanArgs(cap_sen=5000, **place_world.origin))

        # The model is told the room is nil and given nothing that could be
        # narrated as "200% of your room" or divided back into a room.
        assert result.value["room_sen"] == 0
        assert result.value["places"]
        for place in result.value["places"]:
            assert place["share"] is None
            assert place["band"] == "over"

    async def test_the_evidence_names_the_room_the_bands_were_judged_on(
        self, session, user, today, place_world
    ):
        await spend_out(session, user, today)
        context = await context_for(session, user, today)
        result = await run_search(context, PlanArgs(cap_sen=5000, **place_world.origin))

        assert dict(row.as_pair() for row in result.evidence)["Safe to spend today"] == "RM0.00"

    async def test_a_ceiling_that_matches_nothing_still_states_the_room(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await run_search(context, PlanArgs(cap_sen=1, **place_world.origin))

        assert result.value["places"] == []
        assert dict(row.as_pair() for row in result.evidence)["Safe to spend today"] == "RM52.97"


class TestWhatTheModelIsToldAboutDistance:
    """The Butler quotes these figures out loud, so it has to know which of the
    two distances produced them. A model handed only a fare will read it as a
    price, and a straight-line fare in KL is not one."""

    async def test_each_place_carries_its_basis_and_its_address(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await run_search(
            context, PlanArgs(mode="ride", cap_sen=100_000, **place_world.origin)
        )

        assert result.value["places"]
        for place in result.value["places"]:
            assert place["distance_basis"] in ("road", "straight_line")
            assert place["address"]

    async def test_a_straight_line_search_is_labelled_as_one_in_the_evidence(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await run_search(
            context, PlanArgs(mode="ride", cap_sen=100_000, **place_world.origin)
        )

        evidence = dict(row.as_pair() for row in result.evidence)
        # Beside "Total cost", so the figure above it cannot read as a quote.
        assert "straight line" in evidence["Distance measured"]

    async def test_a_routed_search_says_by_road_and_prices_on_it(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        # Kopi Kaki is 50 m away and free either way, so it is the cheapest and
        # the row is about it: 900 m of road, which is a fare rather than
        # "already there".
        with serving(StubRouting({"w1": 900.0})):
            result = await run_search(
                context, PlanArgs(mode="ride", cap_sen=100_000, **place_world.origin)
            )

        best = result.value["places"][0]
        assert best["name"] == place_world.cheap.name
        assert best["distance_basis"] == "road"
        assert best["road_km"] == 0.9
        assert best["travel_sen"] == 671  # RM5.00 + 0.9 km at RM1.90
        evidence = dict(row.as_pair() for row in result.evidence)
        assert evidence["Distance measured"] == "0.9 km by road"


class TestAskingForOneKindOfFood:
    """The planner could not be asked what sort of food, so it was a price
    filter wearing a recommendation's clothes. Nothing in the arguments carried
    "noodles", so no prompt could ever have honoured it."""

    async def test_the_kind_reaches_the_search(self, session, user, today, place_world):
        context = await context_for(session, user, today)
        result = await run_search(
            context, PlanArgs(cap_sen=100_000, kind="Cafe", **place_world.origin)
        )

        assert [p["name"] for p in result.value["places"]] == [
            place_world.cheap.name,
            place_world.second_cafe.name,
        ]
        assert result.value["kind"] == "Cafe"

    async def test_a_kind_that_matches_nothing_comes_back_empty(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await run_search(
            context, PlanArgs(cap_sen=100_000, kind="Hawker", **place_world.origin)
        )

        # Never the whole list back. A model handed seven places after asking
        # for one kind would read them as the answer and name one of them.
        assert result.value["places"] == []
        assert result.value["kind_count"] == 0
        assert result.value["matching_count"] == 7
        evidence = dict(row.as_pair() for row in result.evidence)
        assert evidence["Nearby places"] == "7 within range, none of them Hawker"
        assert "ceiling" not in evidence["Nearby places"]

    async def test_the_argument_names_the_kinds_the_data_actually_carries(self):
        # The description is the whole mechanism: the model reads it to decide
        # what to pass, and a word that is not in the set matches nothing. So it
        # has to be the set, derived, rather than a list typed out beside it.
        described = PlanArgs.model_fields["kind"].description or ""
        for kind in day_plan_service.known_kinds():
            assert kind in described
        assert "Mamak" in described and "Noodles" in described
        # And it has to say what happens to a word that is not one of them,
        # or the model will invent a category and read the empty list as a
        # verdict on the neighbourhood.
        assert "matches nothing" in described


class TestWhyEachPlaceMatchedTheKind:
    """Two different claims arrive in one list, so the rows have to keep them apart.

    A kind filter matches what OpenStreetMap states about a place and what a
    model believed about it at build time. The second is what makes a chicken
    search reach the burger shop, and it is also the one a model must not read
    back as though the map had said it -- so every row carries the reason it is
    there, and the panel says it too for the one that gets named.
    """

    async def _build_it(self, session, user, today, world, **kwargs):
        context = await context_for(session, user, today)
        with serving(places=world.believed):
            return await run_search(
                context, PlanArgs(**{"cap_sen": 100_000, **world.origin, **kwargs})
            )

    async def test_every_row_carries_the_basis_it_matched_on(
        self, session, user, today, place_world
    ):
        result = await self._build_it(session, user, today, place_world, kind="Chicken")
        assert [(p["name"], p["match_basis"]) for p in result.value["places"]] == [
            (place_world.tagged_chicken.name, "tagged"),
            (place_world.believed_chicken.name, "inferred"),
            (place_world.both_ways.name, "tagged"),
        ]

    async def test_a_row_nobody_narrowed_carries_no_basis(
        self, session, user, today, place_world
    ):
        result = await self._build_it(session, user, today, place_world)
        assert all(p["match_basis"] is None for p in result.value["places"])

    async def test_the_panel_says_the_leading_place_was_believed_rather_than_tagged(
        self, session, user, today, place_world
    ):
        # The panel is what the user reads against the answer. A place on the
        # list because something guessed at its menu must not sit in it looking
        # like one the map records.
        result = await self._build_it(
            session, user, today, place_world, kind="Chicken", cap_sen=1700
        )
        # The tagged pair cost RM19; the ceiling leaves the believed one alone
        # at the top of the list.
        assert [p["name"] for p in result.value["places"]] == [
            place_world.tagged_chicken.name,
            place_world.believed_chicken.name,
        ]
        evidence = dict(row.as_pair() for row in result.evidence)
        assert evidence["Matched on"] == "Chicken — tagged"

    async def test_the_panel_names_the_belief_when_a_belief_is_what_leads(
        self, session, user, today, place_world
    ):
        with serving(places=(place_world.believed_chicken, place_world.no_chicken)):
            context = await context_for(session, user, today)
            result = await run_search(
                context, PlanArgs(cap_sen=100_000, kind="Chicken", **place_world.origin)
            )
        assert [p["name"] for p in result.value["places"]] == [
            place_world.believed_chicken.name
        ]
        evidence = dict(row.as_pair() for row in result.evidence)
        assert evidence["Matched on"] == "Chicken — believed, not tagged"

    async def test_no_kind_asked_for_leaves_the_panel_without_the_row(
        self, session, user, today, place_world
    ):
        # Nothing matched anything, so there is no basis to state and a row
        # saying so would be answering a question nobody asked.
        result = await self._build_it(session, user, today, place_world)
        assert "Matched on" not in dict(row.as_pair() for row in result.evidence)

    def test_the_description_tells_the_model_a_belief_is_not_a_menu(self):
        assert "Tagged" in SELECTION
        assert "build-time model belief" in SELECTION
        # The line that matters: a wider list is not a licence to assert what a
        # place serves.
        assert "not as a menu fact" in SELECTION


class TestWhatTheToolAsksTheModelToDoWithIt:
    """Handed twelve places and no instruction, a model summarises them -- "all
    five halal options, from RM13 to RM14, fit comfortably" -- which names
    nobody and answers nothing.

    These rules used to be the tool's description, 4,792 characters of it,
    bound to every reasoning turn the Butler took about anything at all. They
    are the planner's own selection prompt now, read by the one turn that acts
    on them. What the Butler's copy has to carry is when to hand over."""

    def test_the_selection_turn_is_asked_for_one_place_chosen_and_justified(self):
        assert "Recommend one place" in SELECTION
        # Against what: the day, a goal, and anything remembered about them.
        assert "today's room" in SELECTION and "remember" in SELECTION

    def test_the_butlers_own_copy_is_short_and_says_only_when_to_hand_over(self):
        described = {spec.name: spec.description for spec in SPECS}["start_day_planning"]
        assert len(described) < 800
        assert "where can I eat" in described
        # It chooses nothing and quotes nothing; that is what it delegates for.
        assert "Do not pick a place yourself" in described

    def test_the_offer_to_add_it_lives_with_the_tool_that_does_it(self):
        # The Butler holds this one, not the planner, because it is a write and
        # writes are the Butler's boundary to keep.
        described = {spec.name: spec.description for spec in SPECS}["add_place_to_today"]
        assert "same breath as the recommendation" in described


class TestHowMuchTheModelIsGiven:
    """Five cheapest was a list nothing could be chosen from: the model saw the
    bottom of the price order and nothing else, so "the cheapest one" was the
    only recommendation available to it."""

    async def test_it_hands_back_twelve_at_most_in_the_order_they_were_sorted(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        with serving(places=place_world.crowd):
            result = await run_search(context, PlanArgs(cap_sen=100_000, **place_world.origin))

        places = result.value["places"]
        assert len(places) == 12
        totals = [p["total_sen"] for p in places]
        assert totals == sorted(totals)
        # The thirteenth is the dearest, and it is the one left out.
        assert totals == [1100 + step * 100 for step in range(12)]
        # Said outright, so the model knows the list was cut rather than ended.
        assert result.value["shown_count"] == 12
        assert result.value["total_under_cap"] == 13

    async def test_a_shorter_list_is_not_padded_and_says_its_own_length(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await run_search(context, PlanArgs(cap_sen=100_000, **place_world.origin))

        assert result.value["shown_count"] == len(result.value["places"]) == 7
        assert result.value["total_under_cap"] == 7


class TestThePriceLandscape:
    """The change that turns "nothing under RM15" into "RM15 reaches the mamak
    and the food courts; the Japanese places start at RM42, which is past
    today's room anyway"."""

    async def test_it_states_every_kind_in_range_with_the_cheapest_of_each(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await run_search(context, PlanArgs(cap_sen=100_000, **place_world.origin))

        rows = {row["kind"]: row for row in result.value["price_landscape"]}
        assert set(rows) == {"Cafe", "Mamak", "Chinese", "Japanese", "Western", "Noodles"}
        assert rows["Cafe"] == {"kind": "Cafe", "count": 2, "cheapest_total_sen": 900}
        assert rows["Japanese"]["cheapest_total_sen"] == 5000

    async def test_it_cannot_disagree_with_the_places_beside_it(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await run_search(context, PlanArgs(cap_sen=100_000, **place_world.origin))

        rows = {row["kind"]: row for row in result.value["price_landscape"]}
        for place in result.value["places"]:
            assert rows[place["kind"]]["cheapest_total_sen"] <= place["total_sen"]
        for kind, row in rows.items():
            listed = [p["total_sen"] for p in result.value["places"] if p["kind"] == kind]
            assert min(listed) == row["cheapest_total_sen"]

    async def test_a_ceiling_that_admits_nothing_still_states_what_is_there(
        self, session, user, today, place_world
    ):
        # The single reason for the whole thing. With the list empty, this is
        # all the model has to answer with, and without it the only honest reply
        # left is an apology.
        context = await context_for(session, user, today)
        result = await run_search(context, PlanArgs(cap_sen=500, **place_world.origin))

        assert result.value["places"] == []
        cheapest = result.value["price_landscape"][0]
        assert cheapest == {"kind": "Cafe", "count": 2, "cheapest_total_sen": 900}
        assert len(result.value["price_landscape"]) == 6

    async def test_it_is_all_money_in_whole_sen(self, session, user, today, place_world):
        context = await context_for(session, user, today)
        result = await run_search(context, PlanArgs(cap_sen=100_000, **place_world.origin))

        for row in result.value["price_landscape"]:
            assert isinstance(row["cheapest_total_sen"], int)


class TestWhyTheListIsEmpty:
    """All three empty lists look the same to the model, so the two counts are
    what keep it from telling the user to raise a ceiling that is not the
    problem. The screen and the Butler have to agree about which cause it was:
    a fix that reached only one of them would just move the wrong story."""

    async def test_a_ceiling_too_low_leaves_places_in_range(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await run_search(context, PlanArgs(cap_sen=1, **place_world.origin))

        assert result.value["places"] == []
        assert result.value["nearby_count"] > 0
        assert result.value["matching_count"] > 0
        evidence = dict(row.as_pair() for row in result.evidence)
        assert "none under the ceiling" in evidence["Nearby places"]

    async def test_out_of_range_leaves_nothing_in_range(self, session, user, today, place_world):
        context = await context_for(session, user, today)
        result = await run_search(context, PlanArgs(cap_sen=100_000, **place_world.out_of_range))

        assert result.value["places"] == []
        assert result.value["nearby_count"] == 0
        assert result.value["matching_count"] == 0
        evidence = dict(row.as_pair() for row in result.evidence)
        assert evidence["Nearby places"] == "none within range"

    async def test_a_halal_filter_that_admits_nothing_is_not_narrated_as_a_ceiling(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await run_search(
            context,
            PlanArgs(cap_sen=100_000, halal_only=True, **place_world.lone_non_halal),
        )

        assert result.value["places"] == []
        assert result.value["nearby_count"] == 1
        assert result.value["matching_count"] == 0
        evidence = dict(row.as_pair() for row in result.evidence)
        # The ceiling here is RM1,000 and the place costs RM20. A model handed
        # only "1 within range" would reach for the ceiling, which is the one
        # thing the user cannot fix from here.
        assert evidence["Nearby places"] == "1 within range, none of them halal"
        assert "ceiling" not in evidence["Nearby places"]


class TestTheNearestPlacesAboveTheCeiling:
    """What the model is handed when the ceiling admitted nothing at all.

    A model given an empty list can only apologise. Given the cheapest few
    places just above the ceiling, and told plainly that is what they are, it
    can say the useful thing instead -- without either of them being counted
    among the places that fitted.
    """

    async def test_a_ceiling_below_everything_hands_over_the_nearest(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await run_search(context, PlanArgs(cap_sen=500, **place_world.origin))

        assert result.value["places"] == []
        assert [p["name"] for p in result.value["nearest_over_cap"]] == [
            place_world.cheap.name,
            place_world.mid.name,
            place_world.near_non_halal.name,
        ]
        # Every one of them over the ceiling, and banded so on the row, so no
        # reading of this payload has them fitting.
        assert all(p["band"] == "over" for p in result.value["nearest_over_cap"])
        assert all(p["total_sen"] > 500 for p in result.value["nearest_over_cap"])
        # And they are not folded into any count of what did fit.
        assert result.value["shown_count"] == 0
        assert result.value["total_under_cap"] == 0

    async def test_the_evidence_names_the_closest_and_how_far_over_it_is(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await run_search(context, PlanArgs(cap_sen=500, **place_world.origin))

        evidence = dict(row.as_pair() for row in result.evidence)
        assert "none under the ceiling" in evidence["Nearby places"]
        # Labelled as above the ceiling rather than as the cheapest nearby: a
        # reader skimming the panel alone must not take it for one that fitted.
        assert evidence["Closest above the ceiling"] == f"{place_world.cheap.name} at RM9.00"
        assert evidence["Over the ceiling by"] == "RM4.00"

    async def test_a_ceiling_that_admits_some_places_hands_over_none(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await run_search(context, PlanArgs(cap_sen=1000, **place_world.origin))

        assert [p["name"] for p in result.value["places"]] == [place_world.cheap.name]
        assert result.value["nearest_over_cap"] == []
        evidence = dict(row.as_pair() for row in result.evidence)
        assert "Closest above the ceiling" not in evidence

    async def test_an_empty_list_no_ceiling_caused_hands_over_none(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        out_of_range = await run_search(
            context, PlanArgs(cap_sen=100_000, **place_world.out_of_range)
        )
        no_halal = await run_search(
            context,
            PlanArgs(cap_sen=100_000, halal_only=True, **place_world.lone_non_halal),
        )
        for result in (out_of_range, no_halal):
            assert result.value["places"] == []
            assert result.value["nearest_over_cap"] == []

    def test_the_selection_turn_is_told_never_to_present_one_as_fitting(self):
        assert "nearest_over_cap" in SELECTION
        assert "Never present one as fitting" in SELECTION
        # And what to reach for before apologising for an empty list.
        assert "price_landscape" in SELECTION


class TestTheNearestPlacesBeyondTheRadius:
    """What the model is handed when a filtered search came back thin.

    Three western places within 5 km of Bukit Bintang and sixteen outside it, so
    a model given only what is in range would say "there are three" and be
    right and useless. Given the nearest few outside it, and told outright that
    is what they are, it can offer them without either of them being counted
    among the places in range.
    """

    async def _searched(self, session, user, today, place_world, **kwargs):
        context = await context_for(session, user, today)
        with serving(places=place_world.spread):
            return await run_search(
                context, PlanArgs(cap_sen=100_000, **place_world.origin, **kwargs)
            )

    async def test_a_thin_narrowed_search_hands_over_what_is_outside(
        self, session, user, today, place_world
    ):
        result = await self._searched(session, user, today, place_world, kind="Western")

        assert [p["name"] for p in result.value["places"]] == [
            place_world.near_western.name
        ]
        assert [p["name"] for p in result.value["nearest_beyond_radius"]] == [
            place_world.just_past_the_line.name,
            place_world.dear_and_far.name,
            place_world.non_halal_and_far.name,
            "Barat Jauh Dua",
        ]
        # And none of them counted among the places that were in range.
        assert result.value["shown_count"] == 1
        assert result.value["total_under_cap"] == 1
        assert result.value["kind_count"] == 1

    async def test_a_search_with_plenty_nearby_hands_over_none(
        self, session, user, today, place_world
    ):
        result = await self._searched(session, user, today, place_world, kind="Noodles")

        assert len(result.value["places"]) == 4
        assert result.value["nearest_beyond_radius"] == []

    async def test_an_unfiltered_browse_hands_over_none(
        self, session, user, today, place_world
    ):
        result = await self._searched(session, user, today, place_world)

        assert result.value["places"] != []
        assert result.value["nearest_beyond_radius"] == []

    async def test_the_evidence_names_each_one_with_how_far_out_it_is(
        self, session, user, today, place_world
    ):
        result = await self._searched(session, user, today, place_world, kind="Western")

        rows = [row.as_pair() for row in result.evidence]
        further = [value for label, value in rows if label == "Further out"]
        assert further[0] == f"{place_world.just_past_the_line.name} · Western · 5.1 km · RM19.00"
        assert len(further) == 4
        # The distance is on every one of them: a name and a price alone would
        # read exactly like a row from the list above.
        assert all(" km · " in value for value in further)

    async def test_the_selection_turn_is_told_never_to_present_one_as_nearby(self):
        assert "nearest_beyond_radius" in SELECTION
        assert "Never present one as nearby" in SELECTION

    async def test_the_model_can_resolve_one_by_id(
        self, session, user, today, place_world
    ):
        # The planner reads every name and price back out of an id, so a group
        # the lookup did not know about would be one the model could not choose
        # from however plainly it was described.
        result = await self._searched(session, user, today, place_world, kind="Western")

        found = _by_id(result.value)
        assert found[place_world.just_past_the_line.id]["name"] == (
            place_world.just_past_the_line.name
        )


class TestThePlacesTheKindFilterTurnedAway:
    """The one place in this planner where the model knows more than the data.

    OpenStreetMap records one cuisine word per place. It calls McDonald's
    burgers, which is true and incomplete: a search for chicken finds KFC and
    says nothing about the McDonald's across the road, and no refresh of the
    file changes that because there is no tag for a menu. So a few of the
    turned-away places are handed over at their real kinds and real prices, and
    the model may point at one when it knows better -- while the panel goes on
    saying what the data said.
    """

    async def test_they_come_back_only_when_a_kind_was_asked_for(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        wide = await run_search(context, PlanArgs(cap_sen=100_000, **place_world.origin))
        narrow = await run_search(
            context, PlanArgs(cap_sen=100_000, kind="Noodles", **place_world.origin)
        )

        # Nothing was filtered, so nothing missed.
        assert wide.value["near_misses"] == []
        assert narrow.value["near_misses"]

    async def test_each_one_carries_its_real_kind_and_the_price_that_was_measured(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await run_search(
            context, PlanArgs(cap_sen=100_000, kind="Noodles", **place_world.origin)
        )

        assert [p["name"] for p in result.value["places"]] == [place_world.noodles.name]
        # The nearest of each other kind, nearest first. Nothing here says
        # "noodles" anywhere: they are a cafe, a mamak, a Chinese place and a
        # Japanese one, and that is exactly what they are labelled.
        assert [(p["name"], p["kind"], p["total_sen"]) for p in result.value["near_misses"]] == [
            (place_world.cheap.name, "Cafe", 900),
            (place_world.mid.name, "Mamak", 1250),
            (place_world.near_non_halal.name, "Chinese", 1600),
            (place_world.pricey.name, "Japanese", 5000),
        ]

    async def test_they_are_never_folded_into_the_places_that_matched(
        self, session, user, today, place_world
    ):
        context = await context_for(session, user, today)
        result = await run_search(
            context, PlanArgs(cap_sen=100_000, kind="Cafe", **place_world.origin)
        )

        matched = {p["id"] for p in result.value["places"]}
        assert matched & {p["id"] for p in result.value["near_misses"]} == set()
        # And no count of what the search found includes them: a near miss is
        # not a result, and a model reading shown_count must not find them in it.
        assert result.value["shown_count"] == result.value["kind_count"] == 2
        assert result.value["total_under_cap"] == 2

    async def test_the_list_is_short(self, session, user, today, place_world):
        # Five other kinds are in range. A long second list stops reading as an
        # aside and starts reading as the answer, beside twelve matches and a
        # whole price landscape already going over.
        context = await context_for(session, user, today)
        result = await run_search(
            context, PlanArgs(cap_sen=100_000, kind="Cafe", **place_world.origin)
        )

        assert len(result.value["near_misses"]) == 4
        assert len({p["kind"] for p in result.value["near_misses"]}) == 4

    async def test_the_evidence_states_the_kind_the_data_gave_each_of_them(
        self, session, user, today, place_world
    ):
        """The guardrail, and the reason the rows are emitted for all of them.

        Which near miss the answer names cannot be known until after the answer
        is written, so every one of them gets a row. If the model says the
        mamak does noodles too, the panel underneath still reads Mamak.
        """
        context = await context_for(session, user, today)
        result = await run_search(
            context, PlanArgs(cap_sen=100_000, kind="Noodles", **place_world.origin)
        )

        rows = [row.as_pair() for row in result.evidence]
        assert ["Also nearby", f"{place_world.mid.name} · Mamak · RM12.50"] in rows
        assert ["Also nearby", f"{place_world.cheap.name} · Cafe · RM9.00"] in rows
        # One row per near miss and not one more.
        also = [value for label, value in rows if label == "Also nearby"]
        assert len(also) == len(result.value["near_misses"]) == 4
        # Nothing in the panel calls any of them noodles.
        assert not any("Noodles" in value for value in also)
        # The recommendation is still the place that actually matched.
        assert dict(rows)["Cheapest nearby"] == place_world.noodles.name

    async def test_a_kind_nothing_matched_still_hands_over_what_is_there(
        self, session, user, today, place_world
    ):
        # The most useful case: no Korean food here at all, and the model is
        # handed the places that are, rather than only an apology and a count.
        context = await context_for(session, user, today)
        result = await run_search(
            context, PlanArgs(cap_sen=100_000, kind="Korean", **place_world.origin)
        )

        assert result.value["places"] == []
        assert len(result.value["near_misses"]) == 4
        evidence = [row.as_pair() for row in result.evidence]
        assert ["Nearby places", "7 within range, none of them Korean"] in evidence
        assert ["Also nearby", f"{place_world.cheap.name} · Cafe · RM9.00"] in evidence

    def test_the_selection_turn_may_suggest_a_menu_but_never_state_one(self):
        assert "near_misses" in SELECTION
        # Where that knowledge is worth anything. A chain it can be sure of; a
        # shop it has only ever seen the name of it cannot.
        assert "global chain" in SELECTION
        assert "Restoran MK Corner" in SELECTION

    def test_the_suggestion_is_carried_as_an_id_and_a_reason_never_a_menu(self):
        # The distinction the whole feature turns on: the price is the search's
        # and the claim about the food is the model's. Splitting them across two
        # fields is what stops the second borrowing the authority of the first.
        fields = PlaceChoice.model_fields
        assert "also_consider_id" in fields and "also_consider_reason" in fields
        assert "no figure" in (fields["reason"].description or "")

    def test_a_place_that_was_not_returned_cannot_be_named(self):
        """This used to be an instruction. It is now a type.

        The project has already produced "Sushi Tei (Mid Valley Megamall),
        RM42" -- a restaurant that was in no tool result and, for all anyone
        knows, in no shopping mall. Reasoning over real rows and inventing a
        shop look identical in the finished sentence, and the difference used to
        be one line of prose that three separate rewrites failed to enforce.

        The planner now returns an id and Python looks the name up in the set
        the search returned. An id that is not in that set resolves to nothing
        and the cheapest place stands instead, so the failure is not discouraged
        here, it is unsayable.
        """
        assert PlaceChoice.model_fields["place_id"].annotation is str
        found = {"a-1": {"name": "Kopi Kaki", "total_sen": 1150, "id": "a-1"}}
        assert _named(found, "sushi-tei-mid-valley") is None
        assert _named(found, "a-1")["name"] == "Kopi Kaki"

    def test_every_list_the_search_returned_is_one_it_may_choose_from(self):
        # Including the ones that did not fit: naming the closest place above
        # the ceiling is a real answer to "nothing under RM10", and it would be
        # unreachable if only `places` were in the lookup.
        found = _by_id(
            {
                "places": [{"id": "p", "name": "A"}],
                "nearest_over_cap": [{"id": "o", "name": "B"}],
                "near_misses": [{"id": "n", "name": "C"}],
            }
        )
        assert sorted(found) == ["n", "o", "p"]
