"""find_places() ports kira-prototype.jsx's evaluate() (line 661).

Every scenario runs against the ``place_world`` fixture, not the shipped KL set:
that file is generated from OpenStreetMap and refreshed, so a test naming a real
place would be pinning data rather than behaviour.

The fixture serves ``NoRouting``, so unless a test says otherwise every distance
here is the straight line and every place says so. The road-distance scenarios
below opt in with ``serving(StubRouting(...))``.

The world was laid out for a flat five-kilometre search, from before the radius
came from the mode. A scenario that needs a place further off than a walk pins
``radius_km=WHOLE_WORLD_KM``, which an explicit radius is still entitled to do,
so that what the mode's own radius does is one class of tests rather than a
thing every other test has to be read around. That class is
``TestTheModeDecidesTheRadius``.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from kira.adapters.protocols import Place
from kira.db.models import SOURCE_PLAN, TXN_DRAFT
from kira.engine import safe_to_spend
from kira.money import Money
from kira.seed.demo import DEMO_TODAY, seed_demo_user
from kira.services.day_plan import (
    CANDIDATE_PLACES,
    FEW_NEARBY,
    MODES,
    NEAREST_BEYOND_RADIUS,
    PLAN_CONFIDENCE,
    TRAVEL_BUDGET_MIN,
    add_to_today,
    confidence_for,
    evaluate_place,
    find_place,
    find_places,
    kind_key,
    known_kinds,
    radius_for,
    resolve_kind,
)
from kira.services.snapshot import load_snapshot
from kira.services.transactions import confirm_draft, list_activity
from tests.conftest import StubRouting, serving

# Far enough to hold every place in the fixed world, which is what the searches
# below were written against. See the module docstring.
WHOLE_WORLD_KM = 5.0


class TestBandThresholds:
    """Walk mode has base=0 and per_km=0, so total_sen == the place's estimate,
    which makes the ok/tight/over boundaries easy to reason about directly."""

    async def test_ok_tight_and_over_all_appear(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=2000,
                radius_km=WHOLE_WORLD_KM,
            )
        ).places
        by_name = {p.name: p for p in places}

        # 900 / 2000 = 0.45 <= 0.6
        assert by_name[place_world.cheap.name].share == 0.45
        assert by_name[place_world.cheap.name].band == "ok"

        # 1250 / 2000 = 0.625, in (0.6, 1.0]
        assert by_name[place_world.mid.name].band == "tight"

        # 5000 / 2000 = 2.5 > 1.0
        assert by_name[place_world.pricey.name].band == "over"

    async def test_band_boundaries_are_inclusive_of_their_upper_edge(self, place_world):
        # A place whose total is exactly 60% of room lands in "ok", not "tight".
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=1500,  # 900 / 1500 = 0.6 exactly
            )
        ).places
        cheap = next(p for p in places if p.name == place_world.cheap.name)
        assert cheap.share == 0.6
        assert cheap.band == "ok"


class TestHalalFilter:
    async def test_excludes_non_halal_places_when_requested(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=True,
                cap_sen=100_000,
                room_sen=100_000,
            )
        ).places
        assert places  # sanity: the filter did not empty the whole set
        assert all(p.halal for p in places)
        names = {p.name for p in places}
        assert place_world.near_non_halal.name not in names
        assert place_world.far_non_halal.name not in names

    async def test_includes_non_halal_places_by_default(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        ).places
        names = {p.name for p in places}
        assert place_world.near_non_halal.name in names


class TestCapFilter:
    async def test_a_place_above_the_cap_is_excluded(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=1500,  # below Omakase Empat's 5000
                room_sen=100_000,
            )
        ).places
        names = {p.name for p in places}
        assert place_world.pricey.name not in names
        assert all(p.total_sen <= 1500 for p in places)


class TestSortOrder:
    async def test_results_are_sorted_ascending_by_total_sen(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        ).places
        totals = [p.total_sen for p in places]
        assert totals == sorted(totals)


class TestRoomIsNotCap:
    """room_sen (today's real safe-to-spend) drives share/band. cap_sen only
    filters what is shown. Swapping the two is the bug this guards against."""

    async def test_a_place_can_be_shown_by_cap_but_still_be_over_room(self, place_world):
        # Mamak Dua costs 1250 sen (walk mode adds no travel cost). cap_sen=2100
        # admits it into the results; room_sen=1000 means it actually costs more
        # than the user's whole safe-to-spend for today. If the implementation
        # ever computed share against cap_sen instead of room_sen, 1250 / 2100 =
        # 0.595 would read as "ok" -- the correct answer, computed against
        # room_sen, is "over" (1250 / 1000 = 1.25).
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=2100,
                room_sen=1000,
            )
        ).places
        mid = next(p for p in places if p.name == place_world.mid.name)
        assert mid.total_sen == 1250
        assert mid.share == 1.25
        assert mid.band == "over"

    async def test_raising_cap_above_room_still_yields_tight_and_over_entries(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,  # generous cap: nothing is filtered out by price
                room_sen=1000,  # tight room: most places cost more than this
            )
        ).places
        bands = {p.band for p in places}
        assert "tight" in bands or "over" in bands
        assert any(p.total_sen > 1000 for p in places), (
            "a place costing more than room_sen must still appear when cap_sen allows it"
        )


class TestNoRoomLeft:
    """A day already spent out has no share to report, and saying so is the
    only thing that keeps a real share of 2.0 tellable from an absent one."""

    async def test_a_nil_room_yields_no_share_and_every_place_over(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=0,
            )
        ).places
        assert places
        for place in places:
            assert place.share is None
            assert place.band == "over"

    async def test_a_genuine_share_of_two_is_still_reported(self, place_world):
        # Kopi Kaki costs 900 sen against 450 sen of room: exactly the ratio the
        # old zero-room stand-in was indistinguishable from.
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=450,
            )
        ).places
        cheap = next(p for p in places if p.name == place_world.cheap.name)
        assert cheap.share == 2.0


class TestNearbyCount:
    """An empty result has three causes, and only the two counts tell them
    apart: a ceiling the user can move, a filter the user can switch off, or a
    distance neither of those will close."""

    async def test_it_counts_what_the_radius_held_before_the_filters_ran(self, place_world):
        unfiltered = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        assert unfiltered.nearby_count == len(unfiltered.places)

        filtered = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=True,
            cap_sen=1000,  # admits only Kopi Kaki's 900
            room_sen=100_000,
        )
        assert len(filtered.places) < len(unfiltered.places)
        assert filtered.nearby_count == unfiltered.nearby_count

    async def test_a_ceiling_that_admits_nothing_still_counts_the_places_in_range(
        self, place_world
    ):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=1,
            room_sen=100_000,
        )
        assert found.places == ()
        assert found.nearby_count > 0

    async def test_it_is_nil_where_the_seed_data_does_not_reach(self, place_world):
        found = await find_places(
            **place_world.out_of_range,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        assert found.places == ()
        assert found.nearby_count == 0
        assert found.matching_count == 0


class TestMatchingCount:
    """The third cause. A ceiling the user cannot see past is one thing; a
    halal toggle they set themselves is another, and dragging the ceiling for
    it is advice that cannot work."""

    async def test_it_counts_what_survived_the_halal_filter_not_the_ceiling(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=True,
            cap_sen=1,  # admits nothing at all
            room_sen=100_000,
            radius_km=WHOLE_WORLD_KM,
        )
        assert found.places == ()
        # Two of the seven places in range are not halal, and the ceiling of one
        # sen is what emptied the rest -- which is the count that says so.
        assert found.nearby_count == 7
        assert found.matching_count == 5

    async def test_the_halal_filter_alone_can_empty_a_generous_ceiling(self, place_world):
        # 4.9 km south of Chophouse Lima: it is the one place in range, and it
        # is not halal. No ceiling reaches it, because the ceiling is not what
        # is holding it back.
        found = await find_places(
            **place_world.lone_non_halal,
            mode="walk",
            halal_only=True,
            cap_sen=100_000,
            room_sen=100_000,
            radius_km=WHOLE_WORLD_KM,
        )
        assert found.places == ()
        assert found.nearby_count == 1
        assert found.matching_count == 0

        # Same spot, same ceiling, halal off: the place was there all along.
        relaxed = await find_places(
            **place_world.lone_non_halal,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
            radius_km=WHOLE_WORLD_KM,
        )
        assert [p.name for p in relaxed.places] == [place_world.far_non_halal.name]
        assert relaxed.matching_count == 1

    async def test_the_counts_nest(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=True,
            cap_sen=1000,  # admits only Kopi Kaki's 900
            room_sen=100_000,
        )
        assert found.nearby_count >= found.matching_count >= len(found.places)
        assert found.nearby_count > found.matching_count > len(found.places)


class TestTheKindFilter:
    """"I want noodles" used to be unanswerable: nothing in the search carried
    what kind of food it was for, so every reply was the same cheapest-first
    list with the request quietly dropped out of it."""

    async def test_it_returns_only_that_kind(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
            kind="Cafe",
        )
        assert [p.name for p in found.places] == [
            place_world.cheap.name,
            place_world.second_cafe.name,
        ]
        assert {p.kind for p in found.places} == {"Cafe"}

    async def test_case_and_a_plural_are_forgiven_in_both_spellings(self, place_world):
        # "Noodles" is how the data spells it and "noodle" is how a person asks
        # for it; "japanese" differs from the data only in its capital.
        for asked in ("noodle", "noodles", "NOODLES", " Noodles "):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind=asked,
                radius_km=WHOLE_WORLD_KM,
            )
            assert [p.name for p in found.places] == [place_world.noodles.name], asked

        japanese = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
            kind="japanese",
            radius_km=WHOLE_WORLD_KM,
        )
        assert [p.name for p in japanese.places] == [place_world.pricey.name]

    async def test_a_word_nothing_matches_returns_nothing_rather_than_everything(
        self, place_world
    ):
        """The failure this is written against.

        Widening back out to the whole list is the same mistake as silently
        dropping "halal": the user reads a list they never asked for as the
        answer to the request they did make.
        """
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
            kind="Hawker",
            radius_km=WHOLE_WORLD_KM,
        )
        assert found.places == ()
        assert found.kind_count == 0
        # And the two counts above it are untouched, so the cause is readable:
        # there is food here, it is simply not that food.
        assert found.nearby_count == 7
        assert found.matching_count == 7

    async def test_an_empty_kind_is_told_apart_from_an_empty_ceiling(self, place_world):
        by_kind = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
            kind="Korean",
            radius_km=WHOLE_WORLD_KM,
        )
        by_ceiling = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=1,
            room_sen=100_000,
            radius_km=WHOLE_WORLD_KM,
        )
        assert by_kind.places == by_ceiling.places == ()
        # Identical lists, and the counts are the whole difference between
        # "drag the ceiling" and "there is no Korean food around here".
        assert by_kind.kind_count == 0
        assert by_ceiling.kind_count == by_ceiling.matching_count == 7

    async def test_the_counts_still_nest_with_a_kind_asked_for(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=True,
            cap_sen=1000,  # admits only Kopi Kaki's 900
            room_sen=100_000,
            kind="Cafe",
            radius_km=WHOLE_WORLD_KM,
        )
        assert found.nearby_count == 7
        assert found.matching_count == 5  # two of the seven are not halal
        assert found.kind_count == 2  # both cafes are
        assert len(found.places) == 1  # and only one of them is under RM10

    async def test_the_kind_is_counted_after_the_halal_filter_not_before_it(self, place_world):
        # Bak Kut Teh Tiga is the only Chinese place and it is not halal, so a
        # halal search for Chinese food has nothing to offer -- and says so with
        # the kind count rather than with the halal one, which is about the two
        # places that were dropped before this filter ever ran.
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=True,
            cap_sen=100_000,
            room_sen=100_000,
            kind="Chinese",
            radius_km=WHOLE_WORLD_KM,
        )
        assert found.places == ()
        assert found.matching_count == 5
        assert found.kind_count == 0

    async def test_no_kind_asked_for_leaves_the_list_and_the_count_alone(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
            radius_km=WHOLE_WORLD_KM,
        )
        assert len(found.places) == 7
        assert found.kind_count == found.matching_count == 7


class TestAPlaceWithSeveralKinds:
    """OpenStreetMap gives a fifth of the places it knows more than one cuisine.

    Nando's is ``chicken;portuguese``, and a search for fried chicken used to
    miss it: only the first cuisine was kept and the rest were thrown away. The
    world here is the same shape -- one place carrying two kinds, one carrying
    only the first of them, one carrying neither.
    """

    async def _search(self, world, kind: str | None = None):
        """The three-place world, searched on foot so the outing is the meal."""
        with serving(places=world.multi_kind):
            return await find_places(
                **world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind=kind,
            )

    async def test_either_of_its_kinds_finds_it(self, place_world):
        by_label = await self._search(place_world, "Chicken")
        by_second = await self._search(place_world, "Portuguese")
        assert [p.name for p in by_label.places] == [
            place_world.two_kinds.name,
            place_world.one_kind.name,
        ]
        # The second kind reaches it and nothing else: matching on any kind is
        # not the same as matching on everything.
        assert [p.name for p in by_second.places] == [place_world.two_kinds.name]

    async def test_the_second_kind_is_forgiven_the_same_one_way(self, place_world):
        for asked in ("portuguese", "PORTUGUESE", " Portuguese "):
            found = await self._search(place_world, asked)
            assert [p.name for p in found.places] == [place_world.two_kinds.name], asked

    async def test_the_label_it_is_shown_under_does_not_change(self, place_world):
        """A second kind widens what finds a place. It does not rename it."""
        found = await self._search(place_world, "Portuguese")
        (only,) = found.places
        assert only.kind == place_world.two_kinds.kind == "Chicken"
        assert only.kind == (await self._search(place_world, "Chicken")).places[0].kind

    async def test_the_price_does_not_change_either(self, place_world):
        """The band came from the first cuisine and still does.

        A place must not read cheaper or dearer for having been recorded as
        serving two things -- that would move a figure on screen for a reason
        nobody could see in the data.
        """
        wide = await self._search(place_world)
        found = await self._search(place_world, "Portuguese")
        (only,) = found.places
        twin = next(p for p in wide.places if p.id == only.id)
        assert only.total_sen == twin.total_sen == place_world.two_kinds.estimate.sen
        assert only.confidence == twin.confidence == place_world.two_kinds.confidence

    async def test_the_counts_say_which_filter_did_what(self, place_world):
        found = await self._search(place_world, "Portuguese")
        # One of the three is Portuguese; the halal filter took none of them.
        assert found.nearby_count == found.matching_count == 3
        assert found.kind_count == 1

    async def test_it_is_counted_under_every_kind_it_carries(self, place_world):
        """The choice: a place belongs to as many landscape rows as it has kinds.

        The alternative -- counting it only under its label -- would leave the
        Portuguese row missing while a search for Portuguese returns a place,
        which is the landscape contradicting the list beneath it.
        """
        found = await self._search(place_world)
        rows = {row.kind: row for row in found.landscape}
        assert set(rows) == {"Chicken", "Portuguese", "Mamak"}
        # Two chicken places, priced at the cheaper; the Portuguese row is the
        # same place again, at the same price.
        assert (rows["Chicken"].count, rows["Chicken"].cheapest_total_sen) == (2, 1600)
        assert (rows["Portuguese"].count, rows["Portuguese"].cheapest_total_sen) == (1, 1600)
        assert (rows["Mamak"].count, rows["Mamak"].cheapest_total_sen) == (1, 1200)
        # So the counts no longer add up to the length of the list, and that is
        # the stated cost of the choice rather than an accident.
        assert sum(row.count for row in found.landscape) == 4
        assert len(found.places) == 3

    async def test_every_row_is_what_a_search_for_that_row_returns(self, place_world):
        """The invariant the choice above exists to keep.

        Each row promises a filter: this many places, none cheaper than this.
        """
        wide = await self._search(place_world)
        for row in wide.landscape:
            narrow = await self._search(place_world, row.kind)
            assert narrow.kind_count == row.count, row.kind
            assert len(narrow.places) == row.count, row.kind
            assert min(p.total_sen for p in narrow.places) == row.cheapest_total_sen

    async def test_a_place_with_one_kind_is_untouched_by_any_of_this(self, place_world):
        found = await self._search(place_world, "Mamak")
        (only,) = found.places
        assert only.kind == "Mamak"
        # Place fills the list in for itself, so nothing downstream has to ask
        # whether a place has one kind or several.
        assert only.kinds == ("Mamak",)


class TestAPlaceAModelBelievesSomethingAbout:
    """A kind filter reaches what the map states and what a model believes.

    OpenStreetMap's cuisine tag is one or two words and a menu is not, so a
    place is often findable by nothing it actually sells: McDonald's is tagged
    burger and stops there, though it fries chicken all day. No refresh reaches
    that, and the generator asks a model once at build time instead. A chicken
    search has to reach that burger shop -- and the user has to go on being able
    to tell it from the shop the map really does call chicken, because one is
    known and the other is believed.

    The world is four places, all a walk away so every total is the meal alone,
    and the believed chicken place is listed ahead of the tagged one at the same
    price so the ranking below has something to prove.
    """

    async def _search(self, world, kind: str | None = None, cap_sen: int = 100_000):
        with serving(places=world.believed):
            return await find_places(
                **world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=cap_sen,
                room_sen=100_000,
                kind=kind,
            )

    async def test_a_belief_is_enough_to_be_found_at_all(self, place_world):
        """The whole point: the burger shop comes back from a chicken search."""
        found = await self._search(place_world, "Chicken")
        assert place_world.believed_chicken.name in [p.name for p in found.places]
        # And it is still the burger shop. A wider search does not rename it.
        found_it = next(p for p in found.places if p.id == place_world.believed_chicken.id)
        assert found_it.kind == "Burger"

    async def test_a_believed_match_says_it_was_believed(self, place_world):
        found = await self._search(place_world, "Chicken")
        by_id = {p.id: p for p in found.places}
        assert by_id[place_world.believed_chicken.id].match_basis == "inferred"

    async def test_a_tagged_match_says_it_was_tagged(self, place_world):
        found = await self._search(place_world, "Chicken")
        by_id = {p.id: p for p in found.places}
        assert by_id[place_world.tagged_chicken.id].match_basis == "tagged"

    async def test_a_place_matching_both_ways_is_tagged_and_not_inferred(self, place_world):
        """The stronger of the two answers, where the record gives both.

        A place the map calls chicken is not made a guess by a model agreeing
        with it, and "inferred" on a row the map really does tag would be the
        screen apologising for something it knows.
        """
        found = await self._search(place_world, "Chicken")
        by_id = {p.id: p for p in found.places}
        assert by_id[place_world.both_ways.id].match_basis == "tagged"

    async def test_a_place_can_be_tagged_for_one_word_and_believed_for_another(
        self, place_world
    ):
        # The same shop, twice, under two words: the map states it is a burger
        # place and a model believes it also does chicken.
        by_tag = await self._search(place_world, "Burger")
        (only,) = by_tag.places
        assert only.id == place_world.believed_chicken.id
        assert only.match_basis == "tagged"

    async def test_a_place_believed_nothing_relevant_is_still_turned_away(self, place_world):
        """A widened filter is not a dropped one."""
        found = await self._search(place_world, "Chicken")
        assert place_world.no_chicken.id not in {p.id for p in found.places}
        # It is handed back as a near miss instead, and with no basis at all --
        # it matched nothing, so there is nothing to say about why.
        (near,) = found.near_misses
        assert near.id == place_world.no_chicken.id
        assert near.match_basis is None

    async def test_no_kind_asked_for_leaves_every_place_without_a_basis(self, place_world):
        # Nothing was matched, so nothing has a reason for having matched. A
        # basis on an unfiltered list would be a claim about a question the user
        # never asked.
        found = await self._search(place_world)
        assert len(found.places) == 4
        assert {p.match_basis for p in found.places} == {None}

    async def test_a_tag_ranks_above_a_belief_where_nothing_else_separates_them(
        self, place_world
    ):
        """Both cost RM16 and both are a walk away; one is known, one is guessed.

        The world hands them over belief-first, so a run that ranked on price
        alone would leave the belief on top.
        """
        found = await self._search(place_world, "Chicken")
        assert [p.id for p in found.places] == [
            place_world.tagged_chicken.id,
            place_world.believed_chicken.id,
            place_world.both_ways.id,
        ]
        assert [p.match_basis for p in found.places] == ["tagged", "inferred", "tagged"]

    async def test_it_does_not_otherwise_disturb_the_price_order(self, place_world):
        """A cheaper belief still beats a dearer tag. The basis breaks ties only.

        Ayam Dua Kali is tagged chicken and RM3 dearer than the burger shop that
        is merely believed to do it, and it stays below it. A basis that
        outranked money would be re-sorting the list on something the user
        cannot see beside a figure they can.
        """
        found = await self._search(place_world, "Chicken")
        assert [p.total_sen for p in found.places] == [1600, 1600, 1900]

    async def test_the_counts_say_what_the_widened_filter_did(self, place_world):
        found = await self._search(place_world, "Chicken")
        # Nothing was dropped before the kind filter ran.
        assert found.nearby_count == found.matching_count == 4
        # Three of the four are chicken on one footing or the other, and the
        # count is places rather than matches -- the one tagged and believed
        # both is one place.
        assert found.kind_count == 3
        assert len(found.places) == 3

    async def test_the_landscape_counts_a_belief_and_still_agrees_with_the_list(
        self, place_world
    ):
        """The invariant a wider filter could quietly have broken.

        A row promises a filter: this many places, none cheaper than this. Count
        only the tags and the chicken row would say two while a search for
        chicken hands back three -- the landscape contradicting the list under
        it. So a belief counts, and the row says nothing about which of its
        places rest on one; that is on the rows themselves.
        """
        wide = await self._search(place_world)
        rows = {row.kind: row for row in wide.landscape}
        assert set(rows) == {"Chicken", "Burger", "Noodles"}
        assert (rows["Chicken"].count, rows["Chicken"].cheapest_total_sen) == (3, 1600)
        assert (rows["Burger"].count, rows["Burger"].cheapest_total_sen) == (1, 1600)
        assert (rows["Noodles"].count, rows["Noodles"].cheapest_total_sen) == (1, 1200)
        for row in wide.landscape:
            narrow = await self._search(place_world, row.kind)
            assert narrow.kind_count == row.count, row.kind
            assert len(narrow.places) == row.count, row.kind
            assert min(p.total_sen for p in narrow.places) == row.cheapest_total_sen, row.kind

    async def test_a_place_saying_the_same_thing_twice_is_counted_once(self, place_world):
        # Ayam Dua Kali is tagged chicken and believed to do chicken. Counted
        # under both, the chicken row would promise four places where a search
        # returns three.
        wide = await self._search(place_world)
        chicken = next(row for row in wide.landscape if row.kind == "Chicken")
        assert chicken.count == 3

    async def test_the_basis_survives_the_ceiling_turning_everything_away(self, place_world):
        # ``nearest_over_cap`` is the same places under a ceiling they failed,
        # so the reason each is on it has to travel with them -- otherwise the
        # one list a client draws as "what the money would have to stretch to"
        # is the one list that cannot say what it is offering.
        found = await self._search(place_world, "Chicken", cap_sen=100)
        assert found.places == ()
        assert [p.match_basis for p in found.nearest_over_cap] == [
            "tagged",
            "inferred",
            "tagged",
        ]

    async def test_a_belief_moves_no_figure(self, place_world):
        """A place must not read cheaper, dearer or nearer for being believed."""
        wide = await self._search(place_world)
        narrow = await self._search(place_world, "Chicken")
        for place in narrow.places:
            twin = next(p for p in wide.places if p.id == place.id)
            assert (place.total_sen, place.travel_sen, place.minutes, place.km) == (
                twin.total_sen,
                twin.travel_sen,
                twin.minutes,
                twin.km,
            )
            assert (place.kind, place.kinds) == (twin.kind, twin.kinds)


class TestWhatTheKindFilterTurnedAway:
    """The places a filter for chicken excluded, handed back on purpose.

    OpenStreetMap records one cuisine word per place and no menu at all. It
    calls McDonald's ``burger``, which is true and incomplete: a search for
    chicken finds KFC and walks the user straight past a McDonald's that fries
    chicken all day. No refresh of the data reaches that, because there is no
    tag for it. So a few of the turned-away places come back in their own
    field, at their own kinds and their own prices, for a caller with knowledge
    the tags do not have -- and every one of them is still labelled what the
    data says it is.

    The seven sit at 0.05, 0.5, 0.8, 1.0, 1.2, 2.0 and 4.0 km, in an order the
    prices deliberately do not follow, so which of the two this list is ranked
    on is visible in every assertion below.
    """

    async def _search(self, world, kind: str | None = None, cap_sen: int = 100_000):
        """The seven the fixture already serves, on foot so the outing is the
        meal and every price below is the one written into the world, and over
        the whole five kilometres so all seven of them are in it."""
        return await find_places(
            **world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=cap_sen,
            room_sen=100_000,
            kind=kind,
            radius_km=WHOLE_WORLD_KM,
        )

    async def test_no_kind_asked_for_turns_nothing_away(self, place_world):
        # Nothing was filtered, so nothing missed. A "did not match" list under
        # no filter would be places grouped by having been left out of nothing.
        found = await self._search(place_world)
        assert len(found.places) == 7
        assert found.near_misses == ()

    async def test_a_kind_asked_for_hands_back_what_it_excluded(self, place_world):
        found = await self._search(place_world, "Noodles")
        assert [p.name for p in found.places] == [place_world.noodles.name]
        # The nearest of each other kind, nearest first. Both cafes are in
        # range and only the one 50 m away stands for them.
        assert [(p.name, p.kind, p.total_sen) for p in found.near_misses] == [
            (place_world.cheap.name, "Cafe", 900),
            (place_world.mid.name, "Mamak", 1250),
            (place_world.near_non_halal.name, "Chinese", 1600),
            (place_world.pricey.name, "Japanese", 5000),
        ]
        # Ranked on the road and not on the money: the RM50 Japanese place is
        # here at 2 km and the RM20 Western one is not, at 4 km.
        assert place_world.far_non_halal.name not in {p.name for p in found.near_misses}
        assert [p.km for p in found.near_misses] == sorted(p.km for p in found.near_misses)

    async def test_it_is_held_to_four_however_many_kinds_were_turned_away(self, place_world):
        # Five other kinds are in range and the Western place is the furthest
        # off, so it is the one that does not fit.
        found = await self._search(place_world, "Cafe")
        assert len(found.near_misses) == 4
        assert place_world.far_non_halal.name not in {p.name for p in found.near_misses}

    async def test_nothing_is_in_both_lists(self, place_world):
        found = await self._search(place_world, "Cafe")
        assert {p.id for p in found.places} & {p.id for p in found.near_misses} == set()
        # And nothing in the second list is of the kind that was asked for,
        # which is the same statement said the other way round.
        assert all(kind_key(p.kind) != "cafe" for p in found.near_misses)

    async def test_a_place_that_matched_on_its_second_kind_is_not_a_near_miss(self, place_world):
        """Disjointness has to hold on the place, not on the label it wears.

        Ayam Piri Piri is labelled Chicken and also carries Portuguese. A
        search for Portuguese matches it, so it cannot also be something that
        search turned away -- even though "Chicken" is nowhere in the filter.
        """
        with serving(places=place_world.multi_kind):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Portuguese",
            )
        assert [p.name for p in found.places] == [place_world.two_kinds.name]
        assert place_world.two_kinds.id not in {p.id for p in found.near_misses}
        assert [(p.name, p.kind) for p in found.near_misses] == [
            (place_world.one_kind.name, "Chicken"),
            (place_world.other_kind.name, "Mamak"),
        ]

    async def test_every_one_of_them_keeps_the_kind_the_data_gave_it(self, place_world):
        # The whole guard. Whatever a caller goes on to claim about what a
        # place serves, the kind on the row is the recorded one and the caller
        # has to say the rest in its own voice.
        found = await self._search(place_world, "Cafe")
        by_name = {p.name: p for p in found.near_misses}
        assert by_name[place_world.mid.name].kind == place_world.mid.kind == "Mamak"
        assert by_name[place_world.noodles.name].kind == place_world.noodles.kind == "Noodles"
        for place in found.near_misses:
            assert place.kinds[0] == place.kind

    async def test_the_price_is_the_one_this_search_measured(self, place_world):
        with serving(StubRouting({"w2": 1200.0})):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Cafe",
            )
        mamak = next(p for p in found.near_misses if p.kind == "Mamak")
        assert mamak.distance_basis == "road"
        # The road fare, the same one the list and the landscape are priced on.
        assert mamak.total_sen == 1250 + 728

    async def test_it_never_reaches_past_the_ceiling(self, place_world):
        # A place the user cannot afford is not an alternative to anything. The
        # ceiling that governs the list governs this too.
        found = await self._search(place_world, "Cafe", cap_sen=1300)
        assert [p.name for p in found.near_misses] == [place_world.mid.name]
        assert all(p.total_sen <= 1300 for p in found.near_misses)

    async def test_a_ceiling_that_admits_nothing_turns_away_nothing_either(self, place_world):
        found = await self._search(place_world, "Cafe", cap_sen=500)
        assert found.places == ()
        # ``nearest_over_cap`` is the answer to this empty list, and it stays
        # inside the kind that was asked for. Reaching over the ceiling AND
        # past the filter at once would be two liberties taken in one breath.
        assert [p.name for p in found.nearest_over_cap] == [
            place_world.cheap.name,
            place_world.second_cafe.name,
        ]
        assert found.near_misses == ()

    async def test_it_never_relaxes_the_halal_filter(self, place_world):
        # Bak Kut Teh Tiga is the only Chinese place in range and is not halal.
        # Reaching past what the user eats to offer an alternative is the one
        # thing no list here may do.
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=True,
            cap_sen=100_000,
            room_sen=100_000,
            kind="Cafe",
            radius_km=WHOLE_WORLD_KM,
        )
        assert all(p.halal for p in found.near_misses)
        assert [p.name for p in found.near_misses] == [
            place_world.mid.name,
            place_world.noodles.name,
            place_world.pricey.name,
        ]

    async def test_a_kind_that_matched_nothing_still_turns_the_rest_away(self, place_world):
        # The most useful case of all: there is no Korean food here, and the
        # places that are here are exactly what a caller with a menu in its head
        # would want to look at.
        found = await self._search(place_world, "Korean")
        assert found.places == ()
        assert found.kind_count == 0
        assert len(found.near_misses) == 4
        assert [p.name for p in found.near_misses][0] == place_world.cheap.name

    async def test_none_of_them_undercuts_the_landscape_row_for_its_own_kind(self, place_world):
        """The two halves of the payload say different things, not opposite ones.

        The landscape row is the cheapest of a kind anywhere in range; a near
        miss is the closest one, which can cost more. What must never happen is
        a near miss cheaper than the floor its own kind was given, because then
        one of the two figures is simply wrong.
        """
        found = await self._search(place_world, "Cafe")
        rows = {kind_key(row.kind): row for row in found.landscape}
        for place in found.near_misses:
            assert place.total_sen >= rows[kind_key(place.kind)].cheapest_total_sen

    async def test_a_crowd_of_one_kind_does_not_fill_it(self, place_world):
        """Breadth is the point: four of the same thing is one suggestion.

        The crowd is thirteen places over four kinds. Filter one of them out
        and the other three are what comes back -- one apiece, not the four
        nearest, which would have been three of a kind between them.
        """
        with serving(places=place_world.crowd):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Malaysian",
            )
        assert len(found.near_misses) == 3
        assert len({p.kind for p in found.near_misses}) == 3
        assert {p.kind for p in found.near_misses} == {"Noodles", "Cafe", "Indian"}


class TestTheKindVocabulary:
    """What a model is offered, and what a sentence is checked against."""

    def test_it_is_derived_from_the_loaded_places_not_written_beside_them(self):
        # A hand-kept list would go on offering a word the regenerated file no
        # longer has, which is a filter that matches nothing for a reason
        # nobody reading the code can see.
        from kira.adapters.fakes import KL_PLACES

        assert set(known_kinds()) == {kind for place in KL_PLACES for kind in place.kinds}
        assert list(known_kinds()) == sorted(known_kinds())

    def test_it_offers_the_secondary_kinds_too_and_not_only_the_labels(self):
        """A word no place is labelled with, that several places serve.

        The set has two of them: nothing is labelled Sandwiches or Vietnamese,
        but places tagged with those cuisines are in it and a search for either
        finds them. Offering only the labels would hide a real filter -- and
        the model is offered this vocabulary, so a word missing here is a
        search it will never think to run.
        """
        from kira.adapters.fakes import KL_PLACES

        labels = {place.kind for place in KL_PLACES}
        secondary = set(known_kinds()) - labels
        assert secondary, "the shipped set has no secondary kind left to prove this with"
        for kind in secondary:
            assert resolve_kind(kind) == kind
            assert any(kind in place.kinds for place in KL_PLACES)

    def test_a_word_the_set_carries_resolves_to_its_own_spelling(self):
        assert resolve_kind("japanese") == "Japanese"
        assert resolve_kind("noodle") == "Noodles"
        assert resolve_kind("  MAMAK ") == "Mamak"

    def test_a_word_it_does_not_carry_resolves_to_nothing(self):
        # Not to the nearest thing, and not to everything. "hawker" is the word
        # a model reaches for first, and there is no such kind in the data.
        assert resolve_kind("hawker") is None
        assert resolve_kind("something nice") is None
        assert resolve_kind("") is None

    def test_the_forgiveness_runs_one_way_and_no_further(self):
        # Case and a plural ending, and nothing else. A prefix rule would have
        # "chi" reaching both Chicken and Chinese; a substring rule would have
        # "tea" reaching Steakhouse.
        assert kind_key("Noodles") == kind_key("noodle") == "noodle"
        assert resolve_kind("chi") is None
        assert resolve_kind("tea") is None
        assert resolve_kind("jap") is None


class TestThePriceLandscape:
    """What the ceiling excluded, which the list alone can never say.

    A list that came back empty under RM15 looks the same as one that came back
    empty because there is nothing here. The landscape is the difference: the
    mamak from RM12.50, the Japanese from RM50, and a user who can see which of
    the two their ceiling is up against.
    """

    async def test_every_kind_in_range_gets_one_row(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
            radius_km=WHOLE_WORLD_KM,
        )
        rows = {row.kind: row for row in found.landscape}
        assert set(rows) == {"Cafe", "Mamak", "Chinese", "Japanese", "Western", "Noodles"}
        # Two cafes, counted as two, priced at the cheaper of them.
        assert rows["Cafe"].count == 2
        assert rows["Cafe"].cheapest_total_sen == 900
        assert rows["Japanese"].count == 1
        assert rows["Japanese"].cheapest_total_sen == 5000

    async def test_it_is_ordered_cheapest_kind_first(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
            radius_km=WHOLE_WORLD_KM,
        )
        prices = [row.cheapest_total_sen for row in found.landscape]
        assert prices == sorted(prices)

    async def test_it_agrees_with_the_list_it_was_computed_from(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="ride",  # travel money in every total, so the two could differ
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        rows = {row.kind: row for row in found.landscape}
        for place in found.places:
            row = rows[place.kind]
            # The cheapest of a kind is a floor under every place of that kind,
            # and the place that set it is in the list at exactly that price.
            assert row.cheapest_total_sen <= place.total_sen
        for kind, row in rows.items():
            same_kind = [p.total_sen for p in found.places if p.kind == kind]
            assert min(same_kind) == row.cheapest_total_sen
            assert len(same_kind) == row.count

    async def test_it_ignores_the_ceiling_because_that_is_what_it_is_for(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=1,  # admits nothing at all
            room_sen=100_000,
            radius_km=WHOLE_WORLD_KM,
        )
        assert found.places == ()
        # The whole point: with the list empty, this is the only thing left that
        # can say what the ceiling is up against.
        assert [row.kind for row in found.landscape][0] == "Cafe"
        assert found.landscape[0].cheapest_total_sen == 900
        assert len(found.landscape) == 6

    async def test_it_ignores_the_kind_that_was_asked_for(self, place_world):
        # Asked for Japanese, the useful answer to "there is none" is what is
        # here instead -- and a landscape narrowed to Japanese would be as empty
        # as the list beside it.
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
            kind="Korean",
            radius_km=WHOLE_WORLD_KM,
        )
        assert found.places == ()
        assert len(found.landscape) == 6

    async def test_it_honours_the_halal_filter(self, place_world):
        # Not a ceiling to argue with: the user has said what they eat, and
        # pricing the pork noodles they excluded is not information they asked
        # for.
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=True,
            cap_sen=100_000,
            room_sen=100_000,
            radius_km=WHOLE_WORLD_KM,
        )
        assert {row.kind for row in found.landscape} == {"Cafe", "Mamak", "Japanese", "Noodles"}

    async def test_nothing_in_range_is_an_empty_landscape_not_a_missing_one(self, place_world):
        found = await find_places(
            **place_world.out_of_range,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        assert found.landscape == ()

    async def test_it_is_priced_on_the_road_where_the_list_is(self, place_world):
        # The two must not come apart. A landscape built on straight lines under
        # a list built on roads would be two prices for the same outing.
        with serving(StubRouting({"w2": 1200.0})):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        mamak = next(row for row in found.landscape if row.kind == "Mamak")
        listed = next(p for p in found.places if p.kind == "Mamak")
        assert listed.distance_basis == "road"
        assert mamak.cheapest_total_sen == listed.total_sen == 1250 + 728


class TestTheNearestPlacesAboveTheCeiling:
    """A ceiling of RM5 in a world whose cheapest outing is RM9.

    "Nothing under RM5" is true and it is useless: the person still has to eat,
    and the search already knows the nearest thing is RM9. So the cheapest few
    of what the ceiling turned away come back in their own field -- never in
    ``places``, because a ceiling quietly widened is the same lie as a dropped
    "halal".
    """

    async def test_a_ceiling_below_everything_still_offers_the_nearest(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=500,  # every place in the world is dearer than this
            room_sen=100_000,
        )
        assert found.places == ()
        # The three cheapest of the seven, cheapest first: RM9, RM12.50, RM16.
        assert [p.name for p in found.nearest_over_cap] == [
            place_world.cheap.name,
            place_world.mid.name,
            place_world.near_non_halal.name,
        ]
        assert [p.total_sen for p in found.nearest_over_cap] == [900, 1250, 1600]

    async def test_they_are_told_apart_from_places_that_fitted(self, place_world):
        # The whole shape of the answer: the group is its own field, and every
        # place in it costs more than the ceiling it was measured against.
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=500,
            room_sen=100_000,
        )
        assert found.places == ()
        assert all(place.total_sen > 500 for place in found.nearest_over_cap)
        fitted = {place.id for place in found.places}
        assert not fitted & {place.id for place in found.nearest_over_cap}

    async def test_every_one_of_them_carries_the_over_band(self, place_world):
        # The room is generous, so left as evaluated these would come back "ok"
        # and could be drawn exactly like a place that fitted. The band is what
        # every client already renders as "this does not fit what you asked
        # for", and not fitting is the only reason any of them is here.
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=500,
            room_sen=100_000,
        )
        assert [place.band for place in found.nearest_over_cap] == ["over", "over", "over"]
        # The share is a real ratio against a real room and is left alone.
        assert found.nearest_over_cap[0].share == 900 / 100_000

    async def test_a_ceiling_that_admits_some_places_offers_no_group_at_all(self, place_world):
        # The trigger is a completely empty list, never a thin one. A list with
        # somewhere to eat in it does not get topped up from above the ceiling.
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=1000,  # admits Kopi Kaki at RM9 and nothing else
            room_sen=100_000,
        )
        assert [place.name for place in found.places] == [place_world.cheap.name]
        assert found.nearest_over_cap == ()

    async def test_it_never_relaxes_the_halal_filter_to_fill_itself(self, place_world):
        # Bak Kut Teh Tiga at RM16 is the third-cheapest place in the world and
        # is not halal. Reaching past the ceiling is one thing; reaching past
        # what the user eats is the failure this whole shape exists to avoid.
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=True,
            cap_sen=500,
            room_sen=100_000,
        )
        assert found.places == ()
        assert all(place.halal for place in found.nearest_over_cap)
        assert [p.name for p in found.nearest_over_cap] == [
            place_world.cheap.name,
            place_world.mid.name,
            place_world.noodles.name,
        ]

    async def test_it_never_relaxes_the_kind_filter_either(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=500,
            room_sen=100_000,
            kind="Cafe",
        )
        assert found.places == ()
        assert [p.name for p in found.nearest_over_cap] == [
            place_world.cheap.name,
            place_world.second_cafe.name,
        ]

    async def test_an_empty_list_the_ceiling_did_not_cause_offers_nothing(self, place_world):
        # Nothing in range, nothing halal in range, and nothing of that kind in
        # range are three empty lists a ceiling cannot fill and must not appear
        # to. There is nothing above the ceiling either, because there is
        # nothing at all.
        out_of_range = await find_places(
            **place_world.out_of_range,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        no_halal = await find_places(
            **place_world.lone_non_halal,
            mode="walk",
            halal_only=True,
            cap_sen=100_000,
            room_sen=100_000,
        )
        no_such_kind = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
            kind="Korean",
        )
        for found in (out_of_range, no_halal, no_such_kind):
            assert found.places == ()
            assert found.nearest_over_cap == ()

    async def test_it_is_held_to_three_however_many_the_ceiling_turned_away(self, place_world):
        # Thirteen places, all above the ceiling. A full second list would read
        # as the ceiling having been widened rather than as what it is.
        with serving(places=place_world.crowd):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=500,
                room_sen=100_000,
            )
        assert found.places == ()
        assert len(found.nearest_over_cap) == 3
        assert [p.total_sen for p in found.nearest_over_cap] == [1100, 1200, 1300]

    async def test_it_is_priced_on_the_road_where_the_list_would_have_been(self, place_world):
        # Same rule as the landscape: two prices for the same outing is the one
        # thing that must not come out of this.
        with serving(StubRouting({"w2": 1200.0})):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=500,
                room_sen=100_000,
            )
        mamak = next(p for p in found.nearest_over_cap if p.kind == "Mamak")
        assert mamak.distance_basis == "road"
        assert mamak.total_sen == 1250 + 728


class TestTheModeDecidesTheRadius:
    """How far a search reaches follows from how the user is travelling.

    A flat five kilometres was wrong for all three modes at once. On foot it is
    an hour's walk, which nobody takes for lunch; by Grab it is under ten
    minutes, and a search that mean was leaving nineteen western places out of a
    list of three. So the figure that is chosen is the time somebody will spend
    getting there, and the distance follows from the pace table.

    The ``ladder`` world is six places at 1.8, 2.1, 8.2, 8.7, 12.3 and 13.0 km,
    each one just inside or just outside one of the three radii those budgets
    work out to.
    """

    async def _rungs(self, world, mode, **kwargs) -> list[str]:
        with serving(places=world.ladder):
            found = await find_places(
                **world.origin,
                mode=mode,
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                **kwargs,
            )
        return [place.id for place in found.places]

    async def test_each_mode_reaches_its_own_distance_and_the_three_differ(self, place_world):
        walking = await self._rungs(place_world, "walk")
        training = await self._rungs(place_world, "transit")
        riding = await self._rungs(place_world, "ride")

        # A twenty-five minute walk is under two kilometres, and the rung at
        # 2.1 km is a place the old flat radius offered somebody on foot.
        assert walking == ["g1"]
        # Forty-five minutes of train, seven of them spent waiting for it.
        assert training == ["g1", "g2", "g3"]
        # Forty-five minutes of Grab, and the same rung the walk could not
        # reach is now four rungs back.
        assert riding == ["g1", "g2", "g3", "g4", "g5"]
        # Nothing reaches the last rung, so no mode is quietly unbounded.
        assert "g6" not in riding

    async def test_the_distances_are_derived_from_the_pace_table(self, place_world):
        # The figure chosen is the budget in minutes; the kilometres are worked
        # out from ``MODES``. Written down twice they would agree until the
        # first time a pace was tuned -- so halve the walking pace and the walk
        # has to reach twice as far, with nothing else edited.
        assert radius_for("walk") == TRAVEL_BUDGET_MIN["walk"] / MODES["walk"].min_per_km
        assert await self._rungs(place_world, "walk") == ["g1"]

        with pytest.MonkeyPatch.context() as patch:
            patch.setitem(
                MODES, "walk", replace(MODES["walk"], min_per_km=MODES["walk"].min_per_km / 2)
            )
            assert radius_for("walk") == pytest.approx(3.846, abs=0.001)
            assert await self._rungs(place_world, "walk") == ["g1", "g2"]

    async def test_the_wait_comes_off_the_budget_before_the_pace_is_applied(self):
        # Seven minutes on a platform is seven minutes of the forty-five, and no
        # distance whatever is covered by it.
        assert radius_for("transit") == pytest.approx(
            (TRAVEL_BUDGET_MIN["transit"] - MODES["transit"].wait_min)
            / MODES["transit"].min_per_km
        )
        assert radius_for("transit") == pytest.approx(8.44, abs=0.01)
        assert radius_for("ride") == pytest.approx(12.5, abs=0.01)
        assert radius_for("walk") == pytest.approx(1.92, abs=0.01)

    async def test_a_radius_that_was_asked_for_still_wins(self, place_world):
        # Somebody who asked for three kilometres asked for three kilometres,
        # whatever they were travelling by. It narrows a ride and widens a walk,
        # and both are the caller's to say.
        assert await self._rungs(place_world, "ride", radius_km=3.0) == ["g1", "g2"]
        assert await self._rungs(place_world, "walk", radius_km=9.0) == ["g1", "g2", "g3", "g4"]

    async def test_one_search_measures_the_nearest_candidates_and_no_more(self, place_world):
        # A wide radius over a dense adapter holds more places than one routing
        # call can carry: every candidate is a coordinate pair in that call's
        # URL, and past a few hundred the service refuses the URL outright and
        # the whole search falls back to straight lines. So there is a guard,
        # and it cuts by distance.
        assert len(place_world.throng) > CANDIDATE_PLACES, "the guard has to bite here"
        with serving(places=place_world.throng):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        assert found.nearby_count == CANDIDATE_PLACES
        assert len(found.places) == CANDIDATE_PLACES
        # The nearest of them, not the cheapest. The furthest places in this
        # world are the cheap ones, so a guard that had quietly become a price
        # cut would hand back exactly the ones that are missing here.
        nearest = {f"t{index:03d}" for index in range(1, CANDIDATE_PLACES + 1)}
        assert {place.id for place in found.places} == nearest
        cheapest = min(place_world.throng, key=lambda place: place.estimate.sen)
        assert cheapest.id not in nearest

    async def test_the_guard_does_not_bite_on_anything_the_curated_set_holds(self):
        # It is a guard against a denser adapter, not a trim of ordinary
        # searches. The widest search over the shipped set is a Grab across
        # central KL, and it has to come back whole -- otherwise the radius
        # above is decorative: the places it reached would be eligible and never
        # looked at.
        found = await find_places(
            lat=3.1466,  # Bukit Bintang, the densest corner of the set
            lng=101.7113,
            mode="ride",
            halal_only=False,
            cap_sen=1_000_000,
            room_sen=1_000_000,
            kind="Western",
        )
        assert found.nearby_count < CANDIDATE_PLACES
        # The complaint this whole change came from: nineteen western places in
        # the set and three of them inside five kilometres. A Grab reaches them.
        assert found.kind_count > 3
        assert max(place.km for place in found.places) > 5.0

    async def test_a_place_the_road_puts_over_the_budget_is_not_offered(self, place_world):
        # The straight line is the pre-filter and the road is the line. A rung
        # 1.8 km away as the crow flies is 3 km of pavement, which is over half
        # an hour of walking and not what a twenty-five-minute search promised.
        ladder = place_world.ladder
        with serving(StubRouting({"g1": 3000.0}, places=ladder), places=ladder):
            routed = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        assert routed.places == ()
        # And out of the count as well as out of the list, so nothing downstream
        # reads its absence as a ceiling or a filter.
        assert routed.nearby_count == 0
        # The same search with no router to ask keeps it, on the only distance
        # there is: the straight line, which really is inside the budget.
        assert await self._rungs(place_world, "walk") == ["g1"]

    async def test_a_plan_row_from_the_widest_search_can_still_be_resolved(self, place_world):
        # An id is a handle on a row somebody was shown, and the row a Grab
        # search shows can be twelve kilometres out. Resolving it against a
        # walk's radius would refuse a place that was really on the list.
        with serving(places=place_world.ladder):
            assert find_place("g5", **place_world.origin) is not None
            assert find_place("g6", **place_world.origin) is None


class TestTheNearestPlacesBeyondTheRadius:
    """A narrowed search that came back thin reaches past its own radius.

    The ``spread`` world is the shipped set's own shape in miniature: one
    western place inside 5 km and six outside it, the nearest of those a hundred
    metres past the line. A radius that is merely limiting for a common kind of
    food is, for a rare one, the whole answer -- so the nearest few matching
    places from outside it come back in their own field, never in ``places``,
    because they are further away than the user asked for.

    Every search here pins ``radius_km`` to the five kilometres that world was
    laid out around, and every one of them is on foot -- which is now the only
    mode this group appears in at all. See
    ``TestWhichModesReachPastTheirOwnRadius``.
    """

    async def test_a_thin_narrowed_search_reaches_past_the_radius(self, place_world):
        with serving(places=place_world.spread):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Western",
                radius_km=WHOLE_WORLD_KM,
            )
        # One western place in range, which is the complaint this answers.
        assert [p.name for p in found.places] == [place_world.near_western.name]
        # And the four nearest outside it, nearest first -- starting with the
        # one a hundred metres past the line.
        assert [p.name for p in found.nearest_beyond_radius] == [
            place_world.just_past_the_line.name,
            place_world.dear_and_far.name,
            place_world.non_halal_and_far.name,
            "Barat Jauh Dua",
        ]
        assert [round(p.km, 1) for p in found.nearest_beyond_radius] == [5.1, 5.3, 5.5, 6.5]

    async def test_a_search_with_plenty_nearby_reaches_nowhere(self, place_world):
        # Four noodle shops in range. A list with somewhere to eat in it does
        # not get topped up from two towns over, however much cheaper the noodle
        # shop out there is.
        with serving(places=place_world.spread):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Noodles",
                radius_km=WHOLE_WORLD_KM,
            )
        assert len(found.places) == 4
        assert found.nearest_beyond_radius == ()
        assert place_world.far_noodles.name not in {p.name for p in found.places}

    async def test_three_is_thin_and_four_is_not(self, place_world):
        # The threshold itself, from both sides. Three is the number the
        # complaint arrived with, and a rule that fired only on an empty list
        # would leave that search exactly as it was.
        async def noodles_under(cap_sen: int):
            with serving(places=place_world.spread):
                return await find_places(
                    **place_world.origin,
                    mode="walk",
                    halal_only=False,
                    cap_sen=cap_sen,
                    room_sen=100_000,
                    kind="Noodles",
                    radius_km=WHOLE_WORLD_KM,
                )

        three = await noodles_under(1200)
        assert len(three.places) == 3
        assert [p.name for p in three.nearest_beyond_radius] == [place_world.far_noodles.name]

        four = await noodles_under(1300)
        assert len(four.places) == 4
        assert four.nearest_beyond_radius == ()

    async def test_an_unfiltered_browse_behaves_exactly_as_it_did(self, place_world):
        # Nothing was narrowed, so nothing is being compensated for: everything
        # in range already is the answer to "what is around me". Thin or not.
        with serving(places=place_world.spread):
            whole = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                radius_km=WHOLE_WORLD_KM,
            )
            capped = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=1100,
                room_sen=100_000,
                radius_km=WHOLE_WORLD_KM,
            )
        assert len(whole.places) == 5
        assert whole.nearest_beyond_radius == ()
        # Two places is as thin as the narrowed searches above, and still not a
        # reason to search the next town.
        assert len(capped.places) == 2
        assert capped.nearest_beyond_radius == ()

    async def test_nothing_is_in_both_lists(self, place_world):
        with serving(places=place_world.spread):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Western",
                radius_km=WHOLE_WORLD_KM,
            )
        beyond = {p.id for p in found.nearest_beyond_radius}
        assert beyond
        assert not beyond & {p.id for p in found.places}
        assert not beyond & {p.id for p in found.near_misses}
        assert not beyond & {p.id for p in found.nearest_over_cap}

    async def test_every_one_of_them_is_really_outside_the_radius(self, place_world):
        with serving(places=place_world.spread):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Western",
                radius_km=WHOLE_WORLD_KM,
            )
        assert all(place.km > 5.0 for place in found.nearest_beyond_radius)
        assert all(place.km <= 5.0 for place in found.places)

    async def test_the_ceiling_still_holds_out_there(self, place_world):
        # Reaching past the radius is one thing. Reaching past what the user can
        # pay while doing it would be relaxing two filters for the price of
        # asking about one.
        with serving(places=place_world.spread):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=3000,
                room_sen=100_000,
                kind="Western",
                radius_km=WHOLE_WORLD_KM,
            )
        assert all(place.total_sen <= 3000 for place in found.nearest_beyond_radius)
        assert place_world.dear_and_far.name not in {
            p.name for p in found.nearest_beyond_radius
        }

    async def test_the_halal_filter_still_holds_out_there(self, place_world):
        # The nearest cheap western place out there is not halal, which makes it
        # exactly the one a group that quietly relaxed the wrong filter would
        # lead with.
        with serving(places=place_world.spread):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=True,
                cap_sen=3000,
                room_sen=100_000,
                kind="Western",
                radius_km=WHOLE_WORLD_KM,
            )
        assert all(place.halal for place in found.nearest_beyond_radius)
        assert place_world.non_halal_and_far.name not in {
            p.name for p in found.nearest_beyond_radius
        }

    async def test_the_kind_filter_still_holds_out_there(self, place_world):
        with serving(places=place_world.spread):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Western",
                radius_km=WHOLE_WORLD_KM,
            )
        assert all(
            kind_key(place.kind) == "western" for place in found.nearest_beyond_radius
        )

    async def test_each_of_them_says_why_it_is_on_the_list(self, place_world):
        # The same stamp the list above carries. A place offered from outside
        # the radius is still a place a filter kept, and a row that could not
        # say why it was kept would be two unexplained things at once.
        with serving(places=place_world.spread):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Western",
                radius_km=WHOLE_WORLD_KM,
            )
        assert all(p.match_basis == "tagged" for p in found.nearest_beyond_radius)
        assert all(p.match_reason == "Tagged western" for p in found.nearest_beyond_radius)

    async def test_the_reach_stops_at_twice_the_radius(self, place_world):
        # The cheapest western place in this world is 10.5 km out and is never
        # offered. Unbounded, this would be a search of the whole city handed
        # over wearing the word "nearby".
        with serving(places=place_world.spread):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=900,
                room_sen=100_000,
                kind="Western",
                radius_km=WHOLE_WORLD_KM,
            )
        # A ceiling of RM9 leaves nothing at all in range, so the group is not
        # being suppressed by a thick list: there is simply nothing within reach.
        assert found.places == ()
        assert found.nearest_beyond_radius == ()
        assert place_world.beyond_the_reach.estimate.sen <= 900

    async def test_the_reach_is_held_on_the_road_as_well(self, place_world):
        # The reach is measured the way the radius is: the straight line gets a
        # place onto the shortlist and the road is what it is offered on. A
        # place 5.1 km out as the crow flies and eleven by road is past twice a
        # five-kilometre radius, whatever the great circle says -- and the group
        # promises "a little further than you asked".
        spread = place_world.spread
        with serving(StubRouting({"s6": 11_000.0}, places=spread), places=spread):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Western",
                radius_km=WHOLE_WORLD_KM,
            )
        offered = {p.name for p in found.nearest_beyond_radius}
        assert place_world.just_past_the_line.name not in offered
        # The rest of the group is untouched, so this is the one place being
        # dropped rather than the whole group failing.
        assert offered == {
            place_world.dear_and_far.name,
            place_world.non_halal_and_far.name,
            "Barat Jauh Dua",
            "Barat Jauh Tiga",
        }

    async def test_it_is_held_to_four_however_many_are_out_there(self, place_world):
        with serving(places=place_world.spread):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Western",
                radius_km=WHOLE_WORLD_KM,
            )
        assert len(found.nearest_beyond_radius) == NEAREST_BEYOND_RADIUS == 4

    async def test_the_counts_and_the_landscape_stay_about_the_radius(self, place_world):
        # The counts are what tell an empty list apart from four other empty
        # lists, and they are about what is in range. A group from outside it
        # must not be able to move any of them, or the one thing they are for
        # stops working.
        with serving(places=place_world.spread):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Western",
                radius_km=WHOLE_WORLD_KM,
            )
        assert found.nearby_count == 5
        assert found.matching_count == 5
        assert found.kind_count == 1
        assert found.nearby_count >= found.matching_count >= found.kind_count
        assert found.kind_count >= len(found.places)
        # And the landscape still prices only what is in range: one western
        # place at RM18, not the six outside it.
        western = next(row for row in found.landscape if kind_key(row.kind) == "western")
        assert western.count == found.kind_count == 1
        assert western.cheapest_total_sen == place_world.near_western.estimate.sen

    async def test_the_figures_are_the_real_ones_for_the_longer_journey(self, place_world):
        # The whole basis on which a place from out there can be offered at all.
        # Measured on the road the router actually reported -- 6 km, not the
        # 5.1 km great circle -- by the same clock as every other row.
        #
        # The clock and not the fare, because this group only ever appears on
        # foot (see ``_reaches_past_radius``) and walking costs nothing but
        # time. Time is what the extra kilometres are spent in, and time is what
        # the row has to be honest about: twelve minutes further than the great
        # circle would have said.
        spread = place_world.spread
        with serving(StubRouting({"s6": 6000.0}, places=spread), places=spread):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Western",
                radius_km=WHOLE_WORLD_KM,
            )
        routed = next(
            p for p in found.nearest_beyond_radius if p.name == place_world.just_past_the_line.name
        )
        assert routed.distance_basis == "road"
        assert routed.km == 6.0
        assert routed.road_km == 6.0
        # 13 min/km over 6 km of road, plus the six-minute buffer.
        assert routed.minutes == 84
        # The great circle would have said 72, which is the point: this was not
        # measured on the distance the radius was drawn with.
        assert routed.minutes > round(5.1 * MODES["walk"].min_per_km) + 6

    async def test_the_band_is_the_real_one_and_is_not_stamped_over(self, place_world):
        # Where ``nearest_over_cap`` forces "over" because everything in it
        # fails the ceiling, this group honoured the ceiling: stamping "over"
        # here would state something false about the money in order to say
        # something true about the distance.
        with serving(places=place_world.spread):
            found = await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Western",
                radius_km=WHOLE_WORLD_KM,
            )
        nearest = found.nearest_beyond_radius[0]
        assert nearest.band == "ok"
        assert nearest.share == place_world.just_past_the_line.estimate.sen / 100_000

    async def test_nothing_in_range_at_all_is_still_answered_where_it_can_be(
        self, place_world
    ):
        # Out on the edge of this world, where nothing whatever is inside the
        # radius. "Nothing within range" stays true and the counts go on saying
        # so; the group is what stops that being the whole of the answer.
        with serving(places=place_world.spread):
            found = await find_places(
                **place_world.spread_outskirts,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Western",
                radius_km=WHOLE_WORLD_KM,
            )
        assert found.nearby_count == 0
        assert found.matching_count == 0
        assert found.kind_count == 0
        assert found.places == ()
        assert [p.name for p in found.nearest_beyond_radius] == [
            place_world.beyond_the_reach.name,
            "Barat Jauh Empat",
            "Barat Jauh Tiga",
            "Barat Jauh Dua",
        ]


class TestWhichModesReachPastTheirOwnRadius:
    """The group above and the mode-aware radius do the same job for two modes.

    The group was written when every mode searched a flat five kilometres, and
    a Grab needed a separate box to be offered a place eight kilometres out.
    With the radius following the mode it simply reaches that place, in
    ``places``, priced and ranked with everything else -- so keeping both would
    offer the same place twice, once as in range and once as further than the
    user asked for.

    What is left is walking, where the line is short, real, and worth stepping
    past on purpose.
    """

    async def _western(self, world, mode, **kwargs):
        with serving(places=world.spread):
            return await find_places(
                **world.origin,
                mode=mode,
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
                kind="Western",
                **kwargs,
            )

    async def test_a_ride_reaches_those_places_itself_instead_of_in_a_group(self, place_world):
        found = await self._western(place_world, "ride")

        # The place that used to arrive as "further away than you asked" is in
        # the list, because a forty-five-minute Grab really does reach it.
        assert place_world.just_past_the_line.name in {p.name for p in found.places}
        assert len(found.places) > FEW_NEARBY
        assert found.nearest_beyond_radius == ()

    async def test_a_thin_ride_still_offers_no_group(self, place_world):
        # Thin for the same reason the walk below is -- one western place inside
        # the same five kilometres -- so the only thing separating the two is
        # the mode. A mode already spending the longest journey this app
        # suggests has nothing to offer past its own radius: further out is not
        # "a little further", it is a different sort of afternoon.
        riding = await self._western(place_world, "ride", radius_km=WHOLE_WORLD_KM)
        walking = await self._western(place_world, "walk", radius_km=WHOLE_WORLD_KM)

        assert [p.name for p in riding.places] == [place_world.near_western.name]
        assert len(riding.places) <= FEW_NEARBY
        assert riding.nearest_beyond_radius == ()

        assert [p.name for p in walking.places] == [place_world.near_western.name]
        assert len(walking.nearest_beyond_radius) == 4

    async def test_transit_offers_none_either(self, place_world):
        found = await self._western(place_world, "transit", radius_km=WHOLE_WORLD_KM)

        assert len(found.places) <= FEW_NEARBY
        assert found.nearest_beyond_radius == ()

    async def test_it_follows_the_budget_table_rather_than_naming_a_mode(self, place_world):
        # Give walking the same three quarters of an hour the other two get and
        # it stops reaching past its radius, with nothing edited but the table.
        # That is the right answer to that change: a mode spending the longest
        # journey there is has no room left to reach.
        with pytest.MonkeyPatch.context() as patch:
            patch.setitem(TRAVEL_BUDGET_MIN, "walk", max(TRAVEL_BUDGET_MIN.values()))
            found = await self._western(place_world, "walk", radius_km=WHOLE_WORLD_KM)

        assert [p.name for p in found.places] == [place_world.near_western.name]
        assert found.nearest_beyond_radius == ()


class TestTravelCost:
    async def test_walk_mode_adds_no_travel_cost(self, place_world):
        # walk has base=0 and per_km=0, so travel_sen is always 0 regardless
        # of distance, and total_sen equals the place's own estimate.
        places = (
            await find_places(
                **place_world.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        ).places
        for place in places:
            assert place.travel_sen == 0

    async def test_ride_mode_adds_a_base_fare_and_per_km_cost(self, place_world):
        places = (
            await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        ).places
        # Kopi Kaki is 50 m from the search origin (km < 0.12), so even ride
        # mode charges nothing for "already there".
        doorstep = next(p for p in places if p.name == place_world.cheap.name)
        assert doorstep.km < 0.12
        assert doorstep.travel_sen == 0

        # Anything further away pays ride's base fare plus per-km cost.
        farther = next(p for p in places if p.name == place_world.mid.name)
        assert farther.km >= 0.12
        assert farther.travel_sen > 0

    async def test_every_outing_carries_the_six_minute_buffer_on_top_of_the_travel(
        self, place_world
    ):
        """Ordering, queueing and eating are in none of the mode speeds.

        So six minutes is added to every outing in every mode, including one at
        the search origin itself -- and transit's seven-minute wait sits on top
        of that buffer rather than standing in for it.
        """
        origin_lat = place_world.origin["lat"]
        origin_lng = place_world.origin["lng"]
        doorstep = Place(
            "t2", "Right here", "Test", origin_lat, origin_lng, Money(1000), "high", True, ""
        )
        walked = evaluate_place(doorstep, origin_lat, origin_lng, "walk", 100_000)
        assert walked.km < 0.001
        assert walked.minutes == 6

        ridden = evaluate_place(doorstep, origin_lat, origin_lng, "transit", 100_000)
        assert ridden.minutes == 13  # 7 minutes of waiting, then the same buffer

    async def test_the_fare_is_whole_sen_carried_up_not_a_rounded_float(self, place_world):
        """money.py forbids float arithmetic and Python's round() on money.

        150 m of a ride is exactly 28.5 sen of per-km charge on top of the
        RM5.00 base. round() takes a half to even and yields 528; the half-up
        rounding the rest of the app uses yields 529, which is the fare.
        """
        origin_lat = place_world.origin["lat"]
        origin_lng = place_world.origin["lng"]
        place = Place(
            "t1",
            "Exactly 150 m away",
            "Test",
            origin_lat + 0.150 / 111.195,
            origin_lng,
            Money(1000),
            "high",
            True,
            "",
        )
        evaluated = evaluate_place(place, origin_lat, origin_lng, "ride", 100_000)

        assert round(evaluated.km * 1000) == 150
        assert evaluated.travel_sen == 529
        assert isinstance(evaluated.travel_sen, int)
        assert evaluated.total_sen == 1529


class TestTheDistanceThatIsCharged:
    """The defect this work replaces, written as the two numbers it produced.

    Bangsar to a shop at 3.095396,101.675218 is 3.71 km of great circle and
    8.10 km of road. A ride is RM5.00 plus RM1.90 a kilometre, so the same
    journey is RM12.05 measured one way and RM20.39 measured the other -- and
    only the second is what the driver charges. The great circle is not a
    conservative estimate of a road; it is an unreachable lower bound on one.
    """

    ORIGIN_LAT = 3.1285
    ORIGIN_LNG = 101.6709

    def shop(self) -> Place:
        return Place("s1", "The shop", "Grocer", 3.095396, 101.675218, Money(0), "high", True, "")

    def test_the_straight_line_understates_a_real_kl_ride(self):
        straight = evaluate_place(self.shop(), self.ORIGIN_LAT, self.ORIGIN_LNG, "ride", 100_000)
        assert round(straight.km, 2) == 3.71
        assert straight.travel_sen == 1205  # RM12.05
        assert straight.distance_basis == "straight_line"
        assert straight.road_km is None

    def test_the_road_figure_is_the_one_the_fare_is_built_on(self):
        routed = evaluate_place(
            self.shop(),
            self.ORIGIN_LAT,
            self.ORIGIN_LNG,
            "ride",
            100_000,
            road_metres=8101.0,
        )
        assert routed.travel_sen == 2039  # RM20.39, near twice the other figure
        assert routed.distance_basis == "road"
        assert routed.road_km == 8.101
        # km is whatever the fare was computed from, so a client reading it is
        # reading the same distance the money came out of.
        assert routed.km == 8.101

    def test_the_clock_moves_with_the_fare(self):
        # Travel time is distance times a per-km speed, so a road figure that
        # doubles the distance has to move the minutes too -- otherwise the
        # screen says RM20 and fourteen minutes, which is not a journey.
        straight = evaluate_place(self.shop(), self.ORIGIN_LAT, self.ORIGIN_LNG, "ride", 100_000)
        routed = evaluate_place(
            self.shop(),
            self.ORIGIN_LAT,
            self.ORIGIN_LNG,
            "ride",
            100_000,
            road_metres=8101.0,
        )
        assert straight.minutes == 23
        assert routed.minutes == 37

    def test_the_road_fare_is_still_whole_sen_carried_up(self):
        """money.py forbids float arithmetic and Python's round() on money, and
        that does not change because the metres came off a network.

        150 m of a ride is exactly 28.5 sen of per-km charge. round() takes the
        half to even and yields 528; half-up yields 529, which is the fare.
        """
        evaluated = evaluate_place(
            self.shop(),
            self.ORIGIN_LAT,
            self.ORIGIN_LNG,
            "ride",
            100_000,
            road_metres=150.0,
        )
        assert evaluated.travel_sen == 529
        assert isinstance(evaluated.travel_sen, int)

    def test_a_place_on_the_doorstep_by_road_is_still_free(self):
        # The under-120-metre rule is about being already there, and the road
        # is the distance that decides it now.
        evaluated = evaluate_place(
            self.shop(),
            self.ORIGIN_LAT,
            self.ORIGIN_LNG,
            "ride",
            100_000,
            road_metres=110.0,
        )
        assert evaluated.km < 0.12
        assert evaluated.travel_sen == 0
        assert evaluated.distance_basis == "road"


class TestWithNoRouter:
    """The offline half. Every figure is the straight line, and says so."""

    async def test_every_place_is_labelled_straight_line(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="ride",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        assert found.places
        for place in found.places:
            assert place.distance_basis == "straight_line"
            assert place.road_km is None

    async def test_the_fares_are_the_ones_the_great_circle_gives(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="ride",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        fares = {p.name: p.travel_sen for p in found.places}
        assert fares[place_world.cheap.name] == 0  # 50 m: already there
        assert fares[place_world.mid.name] == 595  # 500 m
        assert fares[place_world.near_non_halal.name] == 690  # 1 km
        assert fares[place_world.pricey.name] == 880  # 2 km
        assert fares[place_world.far_non_halal.name] == 1260  # 4 km


class TestWithARouter:
    """The online half, against a router with fixed answers in road metres."""

    async def test_the_fare_and_the_minutes_come_from_the_road(self, place_world):
        # Mamak Dua is 500 m in a straight line and 1.2 km of road.
        with serving(StubRouting({"w2": 1200.0})):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        mid = next(p for p in found.places if p.name == place_world.mid.name)

        assert mid.distance_basis == "road"
        assert mid.road_km == 1.2
        assert mid.km == 1.2
        assert mid.travel_sen == 728  # not the 595 the straight line gives
        assert mid.minutes == 15
        assert mid.total_sen == 1250 + 728

    async def test_the_ceiling_is_applied_after_the_road_distance(self, place_world):
        """The order that makes this worth doing.

        Mamak Dua costs RM12.50 plus RM5.95 of straight-line fare -- RM18.45,
        under a RM19.00 ceiling. By road it is RM7.28 of fare and RM19.78,
        which is over it. Filtering before routing would have shown the user a
        place they cannot afford, at a price that was never available.
        """
        cap_sen = 1900
        with serving(StubRouting({"w2": 1200.0})):
            routed = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=cap_sen,
                room_sen=100_000,
            )
        assert place_world.mid.name not in {p.name for p in routed.places}
        assert all(p.total_sen <= cap_sen for p in routed.places)
        # It is the road distance that excluded it, not the ceiling being tight:
        # with no router the same search shows it.
        unrouted = await find_places(
            **place_world.origin,
            mode="ride",
            halal_only=False,
            cap_sen=cap_sen,
            room_sen=100_000,
        )
        assert place_world.mid.name in {p.name for p in unrouted.places}
        # And it stayed in matching_count either way, so the counts still say
        # the ceiling is what the user could move.
        assert routed.matching_count == unrouted.matching_count

    async def test_the_sort_follows_the_road_totals(self, place_world):
        # Omakase Empat is dearer than everything even before travel, so the
        # interesting swap is between the two mid-priced places: Bak Kut Teh
        # Tiga (RM16.00 + RM6.90 = RM22.90 straight) sits under Chophouse Lima
        # (RM20.00 + RM12.60 = RM32.60) until the road puts it the other way.
        with serving(StubRouting({"w3": 9000.0, "w5": 4200.0})):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        totals = [p.total_sen for p in found.places]
        assert totals == sorted(totals)
        order = [p.name for p in found.places]
        assert order.index(place_world.far_non_halal.name) < order.index(
            place_world.near_non_halal.name
        )

    async def test_it_asks_the_router_once_for_every_candidate_the_radius_held(
        self, place_world
    ):
        stub = StubRouting({})
        with serving(stub):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=True,
                cap_sen=100_000,
                room_sen=100_000,
            )
        assert len(stub.calls) == 1, "one search is one round trip, however many places"
        origin, destinations = stub.calls[0]
        assert origin == (place_world.origin["lat"], place_world.origin["lng"])
        # All seven, including the two the halal filter is about to remove. The
        # radius is a travel budget now, the budget is spent on the road, and
        # only the router knows a road -- so a place has to be measured before it
        # can be called out of range, whether or not the user eats there. Five
        # of the seven survive the filter, and the count says so.
        assert len(destinations) == 7
        assert found.matching_count == 5

    async def test_nothing_in_range_asks_the_router_nothing_useful(self, place_world):
        stub = StubRouting({})
        with serving(stub):
            found = await find_places(
                **place_world.out_of_range,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        assert found.places == ()
        assert stub.calls == [] or stub.calls[0][1] == []


class TestAPartlyAnsweredSearch:
    """A router can route one destination and fail on the next, so the basis is
    per place. A single flag for the whole list would have to lie about half of
    it, and the half it lied about would be the half quoting a fare it cannot
    stand behind."""

    async def test_each_place_carries_the_basis_it_was_actually_measured_on(self, place_world):
        # Two of the five answered; the rest came back null.
        with serving(StubRouting({"w2": 1200.0, "w4": 4500.0})):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        by_name = {p.name: p for p in found.places}
        bases = {name: place.distance_basis for name, place in by_name.items()}

        assert bases[place_world.mid.name] == "road"
        assert bases[place_world.pricey.name] == "road"
        assert bases[place_world.near_non_halal.name] == "straight_line"
        assert bases[place_world.far_non_halal.name] == "straight_line"
        assert len(set(bases.values())) == 2, "one list, two bases"

    async def test_the_routed_ones_are_priced_on_the_road_and_the_rest_are_not(self, place_world):
        with serving(StubRouting({"w2": 1200.0, "w4": 4500.0})):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        fares = {p.name: p.travel_sen for p in found.places}
        road_km = {p.name: p.road_km for p in found.places}

        assert fares[place_world.mid.name] == 728  # 1.2 km of road
        assert fares[place_world.pricey.name] == 1355  # 4.5 km of road
        assert road_km[place_world.mid.name] == 1.2
        assert road_km[place_world.pricey.name] == 4.5

        # Unanswered: the straight-line fares, unchanged, and no road figure to
        # show beside them.
        assert fares[place_world.near_non_halal.name] == 690
        assert fares[place_world.far_non_halal.name] == 1260
        assert road_km[place_world.near_non_halal.name] is None
        assert road_km[place_world.far_non_halal.name] is None


class TestTheAddress:
    async def test_every_place_carries_the_address_it_came_with(self, place_world):
        found = await find_places(
            **place_world.origin,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
        )
        addresses = {p.name: p.address for p in found.places}
        assert addresses[place_world.cheap.name] == place_world.cheap.address
        assert all(addresses.values()), "a place named on a screen has to be findable"


class TestARouterThatMisbehaves:
    """A wrong-shaped answer is not a distance, and must not become one."""

    async def test_an_answer_of_the_wrong_length_is_not_paired_off_anyway(self, place_world):
        class ShortRouting:
            """Asked about seven destinations, answers about one."""

            async def road_metres(self, origin, destinations):
                return [1200.0]

        with serving(ShortRouting()):
            found = await find_places(
                **place_world.origin,
                mode="ride",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )

        # Which place that single figure belongs to is unknowable. Lining it up
        # with the first destination would put one place's road on another
        # place's fare, which is a wrong number nobody could spot. The straight
        # line is wrong by a stated amount instead.
        assert len(found.places) == 7
        assert {p.distance_basis for p in found.places} == {"straight_line"}
        assert all(p.road_km is None for p in found.places)


async def demo(session):
    user = await seed_demo_user(session)
    await session.flush()
    return user


class TestAddingAPlanToToday:
    """A receipt says "I spent this". A plan says "I intend to".

    Both are proposals, so both are drafts — but a draft is excluded from every
    engine calculation, and that exclusion is what these tests are really
    about. Adding a plan must leave today's money exactly where it was.
    """

    async def test_adds_one_draft_for_the_whole_outing(self, session):
        user = await demo(session)
        before = len((await list_activity(session, user)).drafts)

        # RM12.50 of meal and RM5.00 of fare: what the row on the planner shows
        # is the sum, and the sum is what the user tapped.
        added = await add_to_today(
            session,
            user,
            name="Kopi Kaki",
            total_sen=1750,
            confidence="high",
            today=DEMO_TODAY,
        )

        drafts = (await list_activity(session, user)).drafts
        assert len(drafts) == before + 1
        assert added.amount_sen == 1750
        assert added.status == TXN_DRAFT
        assert added.merchant == "Kopi Kaki"
        assert [draft.id for draft in drafts].count(added.id) == 1

    async def test_the_draft_says_it_is_a_plan_and_that_the_price_is_a_guess(self, session):
        user = await demo(session)

        added = await add_to_today(
            session, user, name="Kopi Kaki", total_sen=1750, confidence="high", today=DEMO_TODAY
        )

        assert added.source == SOURCE_PLAN
        assert added.category == "food"
        assert added.category_label == "Food & drink"
        assert added.occurred_on == DEMO_TODAY
        assert "estimate" in added.note
        assert "day plan" in added.note
        # The invariant the whole screen rests on, said on the row itself: the
        # toast that announced this is long gone by the time Activity is read.
        assert "Nothing counts against today until you confirm it." in added.note
        # Nothing here may read as money already put aside.
        assert "pencilled" not in added.note.lower()

    async def test_safe_to_spend_does_not_move_while_it_is_a_plan(self, session):
        user = await demo(session)
        before = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))

        await add_to_today(
            session, user, name="Omakase Empat", total_sen=5000, confidence="low", today=DEMO_TODAY
        )

        after = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))
        # RM50.00 of intention, and not one sen of it counted. The user has not
        # eaten yet; a figure that dropped here would be spending their money
        # for them on the strength of a tap.
        assert before.safe_today == Money(5297)
        assert after.safe_today == Money(5297)
        assert after.spent_today == before.spent_today

    async def test_confirming_it_is_what_finally_spends_the_money(self, session):
        user = await demo(session)
        before = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))
        added = await add_to_today(
            session, user, name="Omakase Empat", total_sen=5000, confidence="low", today=DEMO_TODAY
        )

        await confirm_draft(session, user, added.id)

        after = safe_to_spend(await load_snapshot(session, user, DEMO_TODAY))
        # RM50.00 leaves today's spending and the balance both, so the day loses
        # RM52.27 rather than RM50.00 — but it loses it now, once the user has
        # said the money is gone, and not a moment before.
        assert after.safe_today == Money(70)
        assert after.spent_today == before.spent_today + Money(5000)

    async def test_it_is_waiting_in_activity_alongside_every_other_draft(self, session):
        user = await demo(session)
        before = (await list_activity(session, user)).draft_total_sen

        added = await add_to_today(
            session, user, name="Kopi Kaki", total_sen=1750, confidence="high", today=DEMO_TODAY
        )

        activity = await list_activity(session, user)
        # Nothing new had to be built for this: drafts already surface here, and
        # a plan is one, so it arrives with the receipt and the voice note.
        waiting = next(draft for draft in activity.drafts if draft.id == added.id)
        assert waiting.source == SOURCE_PLAN
        assert activity.draft_total_sen == before + 1750
        # The ledger is confirmed spending only, and an intention is not that.
        assert added.id not in {
            txn.id for day in activity.days for txn in day.transactions
        }
        assert activity.spent_this_cycle_sen == 63135

    async def test_maps_each_band_to_a_figure_below_what_a_read_claims(self, session):
        user = await demo(session)

        bands = {}
        for band in ("high", "medium", "low"):
            added = await add_to_today(
                session,
                user,
                name=f"Place {band}",
                total_sen=1000,
                confidence=band,
                today=DEMO_TODAY,
            )
            bands[band] = added.confidence

        assert bands == {"high": 70, "medium": 50, "low": 30}
        # A curated price band is a weaker thing than a total printed on a slip.
        # The receipt reader's own scans come in at 94, and nothing here may
        # dress an estimate up to look like one of those.
        assert max(bands.values()) < 94
        assert bands["high"] > bands["medium"] > bands["low"]

    async def test_a_band_this_build_does_not_know_is_read_as_the_least_certain(self, session):
        user = await demo(session)

        # The bands come from a regenerated data file. A word this build has not
        # seen should cost the user their tap the least, and must not be turned
        # into more certainty than anything behind it supports.
        added = await add_to_today(
            session, user, name="Kopi Kaki", total_sen=1750, confidence="astonishing",
            today=DEMO_TODAY,
        )

        assert added.confidence == PLAN_CONFIDENCE["low"]
        assert confidence_for("astonishing") == confidence_for("low")
