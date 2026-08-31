"""Adversarial checks written independently of the feature's own tests.

Runs against the SHIPPED KL set (189 places, 24 kinds, 46 of the places
carrying more than one) rather than the seven place fixture, because the
fixture is the world the feature was written to pass in and the shipped file is
the world it will run in.
"""

from __future__ import annotations

import pytest

from kira.adapters.fakes import KL_PLACES, FakeMaps
from kira.services.day_plan import (
    NEAR_MISSES,
    find_places,
    kind_key,
    known_kinds,
    price_landscape,
    resolve_kind,
)

# Bukit Bintang, dense enough that a 5 km radius holds most of the set.
BB = {"lat": 3.1466, "lng": 101.7113}
# Sri Petaling, far enough south that the radius holds a different slice.
SP = {"lat": 3.0680, "lng": 101.6890}

MODES = ("walk", "transit", "ride")


class TestTheVocabularyCannotBeEmpty:
    def test_the_derivation_actually_produced_something(self):
        assert len(known_kinds()) >= 10, known_kinds()
        assert all(k.strip() for k in known_kinds())

    def test_the_tool_description_is_the_derivation_and_not_a_copy(self):
        from kira.agent.tools.day_plan import PlanArgs

        described = PlanArgs.model_fields["kind"].description or ""
        for kind in known_kinds():
            assert kind in described, kind
        # Nothing in the description that is not a real kind, spelled as a
        # capitalised word in the comma list.
        listed = described.split("carry: ")[1].split(". Anything")[0]
        assert [w.strip() for w in listed.split(",")] == list(known_kinds())


class TestTheFilterNeverWidens:
    @pytest.mark.parametrize("bad", ["hawker", "healthy", "street food", "zzzz", "noodle soup"])
    async def test_a_nonsense_kind_returns_nothing(self, bad):
        found = await find_places(
            **BB, mode="walk", halal_only=False, cap_sen=1_000_000, room_sen=1_000_000, kind=bad
        )
        assert found.places == (), (bad, len(found.places))
        assert found.kind_count == 0
        # And the cause is readable: there IS food here.
        assert found.nearby_count > 0
        assert found.matching_count > 0
        # The landscape still says what is there.
        assert found.landscape

    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    async def test_a_blank_kind_is_no_filter_not_an_empty_one(self, blank):
        wide = await find_places(
            **BB, mode="walk", halal_only=False, cap_sen=1_000_000, room_sen=1_000_000
        )
        found = await find_places(
            **BB, mode="walk", halal_only=False, cap_sen=1_000_000, room_sen=1_000_000, kind=blank
        )
        assert [p.id for p in found.places] == [p.id for p in wide.places]
        assert found.kind_count == wide.kind_count == wide.matching_count

    async def test_a_kind_in_the_data_but_not_in_the_radius_returns_nothing(self):
        """The case the feature's own tests skip.

        Find a kind the shipped set carries that has no place inside the radius
        of one origin but does inside another, and assert the near-empty side
        comes back empty rather than widening to everything.
        """
        wide = await find_places(
            **SP, mode="walk", halal_only=False, cap_sen=1_000_000, room_sen=1_000_000
        )
        # Every kind the places in range carry, not just the ones they are
        # labelled with: a kind is absent from here only if nothing around
        # serves it, and a search matches on any kind a place has.
        in_range = {kind_key(k) for p in wide.places for k in p.kinds}
        absent = [k for k in known_kinds() if kind_key(k) not in in_range]
        assert absent, "pick a sparser origin; every kind is in range here"
        assert wide.places, "origin must have SOME food or the test proves nothing"
        for kind in absent:
            found = await find_places(
                **SP,
                mode="walk",
                halal_only=False,
                cap_sen=1_000_000,
                room_sen=1_000_000,
                kind=kind,
            )
            assert found.places == (), (kind, len(found.places))
            assert found.kind_count == 0
            assert found.matching_count == wide.matching_count

    async def test_a_kind_that_exists_only_outside_the_halal_set_is_not_widened(self):
        found = await find_places(
            **BB, mode="walk", halal_only=True, cap_sen=1_000_000, room_sen=1_000_000, kind="Pizza"
        )
        assert all(p.halal and kind_key(p.kind) == "pizza" for p in found.places)

    async def test_the_ceiling_and_the_kind_compose_rather_than_cancel(self):
        found = await find_places(
            **BB, mode="ride", halal_only=False, cap_sen=1500, room_sen=5000, kind="Japanese"
        )
        assert all(kind_key(p.kind) == "japanese" and p.total_sen <= 1500 for p in found.places)


class TestTheLandscapeAgreesWithTheList:
    """Recomputed here from the places themselves, not read back off the API.

    A place counts under every kind it carries, which is the choice the service
    makes and states: the filter matches any of them, so a row that left out
    the places whose second kind it is would promise fewer than a search for it
    returns. The counts therefore do not sum to the length of the list.
    """

    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("halal", [True, False])
    @pytest.mark.parametrize("origin", [BB, SP])
    async def test_every_row_matches_an_independent_computation(self, mode, halal, origin):
        # Cap wide open so `places` IS the evaluated set and the landscape can
        # be checked against it row for row.
        found = await find_places(
            **origin, mode=mode, halal_only=halal, cap_sen=10_000_000, room_sen=100_000
        )
        expected: dict[str, tuple[int, int]] = {}
        for place in found.places:
            for kind in place.kinds:
                key = kind_key(kind)
                count, cheapest = expected.get(key, (0, place.total_sen))
                expected[key] = (count + 1, min(cheapest, place.total_sen))

        actual = {
            kind_key(row.kind): (row.count, row.cheapest_total_sen) for row in found.landscape
        }
        assert actual == expected, (mode, halal, origin)
        # Ordered cheapest first, and the tie-break is stable.
        prices = [row.cheapest_total_sen for row in found.landscape]
        assert prices == sorted(prices)
        # And the row's own spelling is one a place in that group actually has.
        for row in found.landscape:
            group = [
                kind
                for place in found.places
                for kind in place.kinds
                if kind_key(kind) == kind_key(row.kind)
            ]
            assert row.kind in group

    @pytest.mark.parametrize("origin", [BB, SP])
    async def test_each_row_is_the_search_for_that_row(self, origin):
        """What a row promises: filter by this kind, get this many, from this.

        The one invariant that keeps counting a place under several kinds
        honest. A row saying "Seafood, 4, from RM24" against a search for
        seafood returning six places, or three, would be the landscape and the
        list disagreeing about the same city block.
        """
        wide = await find_places(
            **origin, mode="ride", halal_only=False, cap_sen=10_000_000, room_sen=100_000
        )
        assert wide.landscape
        for row in wide.landscape:
            narrow = await find_places(
                **origin,
                mode="ride",
                halal_only=False,
                cap_sen=10_000_000,
                room_sen=100_000,
                kind=row.kind,
            )
            assert narrow.kind_count == row.count, row.kind
            assert len(narrow.places) == row.count, row.kind
            assert min(p.total_sen for p in narrow.places) == row.cheapest_total_sen, row.kind

    async def test_the_landscape_is_unchanged_by_the_kind_asked_for(self):
        wide = await find_places(
            **BB, mode="ride", halal_only=False, cap_sen=1_000_000, room_sen=100_000
        )
        narrow = await find_places(
            **BB,
            mode="ride",
            halal_only=False,
            cap_sen=1_000_000,
            room_sen=100_000,
            kind="Japanese",
        )
        assert wide.landscape == narrow.landscape

    async def test_the_landscape_is_unchanged_by_the_ceiling(self):
        wide = await find_places(
            **BB, mode="ride", halal_only=False, cap_sen=1_000_000, room_sen=100_000
        )
        tiny = await find_places(**BB, mode="ride", halal_only=False, cap_sen=1, room_sen=100_000)
        assert tiny.places == ()
        assert wide.landscape == tiny.landscape

    async def test_the_landscape_does_change_with_the_halal_filter(self):
        wide = await find_places(
            **BB, mode="walk", halal_only=False, cap_sen=1_000_000, room_sen=100_000
        )
        halal = await find_places(
            **BB, mode="walk", halal_only=True, cap_sen=1_000_000, room_sen=100_000
        )
        assert {r.kind for r in halal.landscape} <= {r.kind for r in wide.landscape}
        for row in halal.landscape:
            twin = next(r for r in wide.landscape if r.kind == row.kind)
            assert row.count <= twin.count
            assert row.cheapest_total_sen >= twin.cheapest_total_sen

    def test_the_landscape_of_nothing_is_empty(self):
        assert price_landscape([]) == ()


class TestWhatTheFilterTurnedAway:
    """``near_misses`` across every kind the shipped set actually carries.

    Deliberately brand-free. The interesting behaviour is that a chicken search
    from Bukit Bintang hands over the McDonald's forty metres away, but naming
    it here would be pinning a data file that is regenerated from
    OpenStreetMap: the next refresh moves a shop and the test goes red with
    nothing about the planner having changed. So what is checked is what has to
    hold whatever the file says.
    """

    CAP = 3000

    async def _narrow(self, origin: dict, kind: str):
        return await find_places(
            **origin, mode="walk", halal_only=False, cap_sen=self.CAP, room_sen=100_000, kind=kind
        )

    @pytest.mark.parametrize("origin", [BB, SP])
    async def test_every_kind_in_range_turns_the_others_away_cleanly(self, origin):
        wide = await find_places(
            **origin, mode="walk", halal_only=False, cap_sen=self.CAP, room_sen=100_000
        )
        assert wide.landscape
        for row in wide.landscape:
            narrow = await self._narrow(origin, row.kind)
            near = narrow.near_misses
            assert len(near) <= NEAR_MISSES, row.kind

            # Never a match wearing a second hat. A place carrying the kind that
            # was asked for among three others is a result, not a near miss.
            matched = {place.id for place in narrow.places}
            assert not matched & {place.id for place in near}, row.kind
            for place in near:
                assert all(kind_key(k) != kind_key(row.kind) for k in place.kinds), place.name
                # The ceiling the list was held to holds here too: somewhere
                # unaffordable is not an alternative to anything.
                assert place.total_sen <= self.CAP, place.name
                # And the kind on the row is the one the data gives it, which
                # is the whole guard on anything a caller says about the menu.
                assert place.kind == place.kinds[0]

            # One per kind, nearest first.
            labels = [kind_key(place.kind) for place in near]
            assert len(set(labels)) == len(labels), (row.kind, labels)
            assert [p.km for p in near] == sorted(p.km for p in near), row.kind

    @pytest.mark.parametrize("origin", [BB, SP])
    async def test_no_kind_asked_for_turns_nothing_away(self, origin):
        wide = await find_places(
            **origin, mode="walk", halal_only=False, cap_sen=self.CAP, room_sen=100_000
        )
        assert wide.places
        assert wide.near_misses == ()

    @pytest.mark.parametrize("bad", ["hawker", "healthy", "street food"])
    async def test_a_kind_the_data_has_no_word_for_still_hands_over_what_is_there(self, bad):
        # The list is empty and stays empty -- the filter never widens. What
        # comes back instead is a handful of real places at real prices, which
        # is what a caller needs to answer with something better than an
        # apology.
        found = await self._narrow(BB, bad)
        assert found.places == ()
        assert found.kind_count == 0
        assert len(found.near_misses) == NEAR_MISSES
        assert len({kind_key(p.kind) for p in found.near_misses}) == NEAR_MISSES

    async def test_it_never_reaches_past_the_halal_filter(self):
        found = await find_places(
            **BB, mode="walk", halal_only=True, cap_sen=self.CAP, room_sen=100_000, kind="Pizza"
        )
        assert found.near_misses
        assert all(place.halal for place in found.near_misses)


class TestMoneyStaysInteger:
    @pytest.mark.parametrize("mode", MODES)
    async def test_no_float_reaches_a_money_field(self, mode):
        found = await find_places(
            **BB, mode=mode, halal_only=False, cap_sen=1_000_000, room_sen=7777
        )
        source = {p.id: p for p in KL_PLACES}
        for place in found.places:
            for field in ("travel_sen", "total_sen", "minutes"):
                value = getattr(place, field)
                assert type(value) is int, (field, type(value))
            estimate = source[place.id].estimate.sen
            assert type(estimate) is int
            assert place.total_sen == estimate + place.travel_sen
        for row in found.landscape:
            assert type(row.cheapest_total_sen) is int
            assert type(row.count) is int

    @pytest.mark.parametrize("mode", MODES)
    async def test_a_near_miss_is_priced_the_same_way_a_match_is(self, mode):
        # It comes out of the same evaluation, so it had better: a second
        # arithmetic for the places that did not match would be a second answer
        # to what an outing there costs.
        found = await find_places(
            **BB, mode=mode, halal_only=False, cap_sen=1_000_000, room_sen=7777, kind="Chicken"
        )
        source = {p.id: p for p in KL_PLACES}
        assert found.near_misses
        for place in found.near_misses:
            assert type(place.travel_sen) is int
            assert type(place.total_sen) is int
            assert place.total_sen == source[place.id].estimate.sen + place.travel_sen


class TestResolveKind:
    def test_it_never_falls_back_to_a_neighbour(self):
        for bad in ("chi", "jap", "tea", "noo", "food", "eat", "nice", "hawker", "s"):
            assert resolve_kind(bad) is None, bad

    def test_every_shipped_kind_round_trips(self):
        for kind in known_kinds():
            assert resolve_kind(kind) == kind
            assert resolve_kind(kind.upper()) == kind
            assert resolve_kind(f"  {kind.lower()}  ") == kind

    def test_it_does_not_collapse_two_real_kinds_onto_one_key(self):
        keys = [kind_key(k) for k in known_kinds()]
        assert len(set(keys)) == len(keys), sorted(keys)


class TestTheShippedDataItself:
    def test_every_place_carries_a_kind_the_vocabulary_has(self):
        for place in KL_PLACES:
            assert resolve_kind(place.kind) == place.kind, place
            for kind in place.kinds:
                assert resolve_kind(kind) == kind, (place.name, kind)

    def test_the_label_is_the_first_of_the_kinds_and_the_list_is_never_empty(self):
        # The label is what the row shows and what the estimate was banded
        # from, so it has to be the primary one -- a place whose list started
        # with something else would be priced as one thing and shown as
        # another.
        for place in KL_PLACES:
            assert place.kinds, place.name
            assert place.kinds[0] == place.kind, place.name
            assert len(set(place.kinds)) == len(place.kinds), place.name

    def test_places_carrying_several_kinds_are_actually_in_the_set(self):
        # The whole point of the field. OSM tags a fifth of KL's places with
        # more than one cuisine, and a refresh that came back with none of them
        # would mean the generator had gone back to keeping only the first.
        several = [place for place in KL_PLACES if len(place.kinds) > 1]
        assert len(several) > 20, len(several)


class TestWhatAModelBelievesAboutTheMenu:
    """``also_serves`` is model output, so this asserts its shape and no more.

    Not that any one shop carries any one belief. Those are regenerated by
    asking a model, they will differ between runs, and a test naming one would
    go red for a data refresh having happened rather than for anything being
    wrong. What has to hold whatever the model said is that every word in it is
    a word the filter has, that none of them restates a tag, and that no place
    carries so many that the model has plainly stopped recognising the shop and
    started listing food.

    Nothing here requires the field to be populated at all: a generator run on a
    machine with no API key writes the file without it, and that is a supported
    state rather than a broken one.
    """

    def test_every_belief_is_a_word_the_filter_actually_has(self):
        # "hawker" and "street food" are what an unconstrained model answers,
        # and either would sit in the file looking like data while matching
        # nothing at all.
        for place in KL_PLACES:
            for kind in place.also_serves:
                assert resolve_kind(kind) == kind, (place.name, kind)

    def test_a_belief_never_restates_a_tag(self):
        for place in KL_PLACES:
            keys = [kind_key(kind) for kind in place.also_serves]
            assert len(set(keys)) == len(keys), (place.name, place.also_serves)
            for key in keys:
                assert all(kind_key(k) != key for k in place.kinds), (place.name, key)

    def test_no_place_believes_an_absurd_number_of_things(self):
        # A model answering with eight kinds for one coffee shop has stopped
        # recognising the place. The generator trims well below this; the bound
        # here is the point past which the field has stopped being a belief
        # about a shop and become a list of food.
        for place in KL_PLACES:
            assert len(place.also_serves) <= 6, (place.name, place.also_serves)

    def test_the_vocabulary_a_search_offers_is_still_only_what_osm_states(self):
        # ``known_kinds`` is what the Butler is told it may filter by, and it is
        # derived from the tags. A belief promoted into it would offer the user
        # a filter that the data behind it does not support.
        tagged = {kind for place in KL_PLACES for kind in place.kinds}
        assert set(known_kinds()) == tagged

    async def test_a_search_matches_tags_and_never_beliefs(self):
        """The separation, asserted where it would actually be lost.

        ``kinds`` is what OpenStreetMap states and ``also_serves`` is what a
        model guessed, and the filter is on the first of them alone. A place
        believed to serve chicken and not tagged it is a near miss, not a
        match, and the day it silently becomes a match is the day the app can
        no longer say which of the two it was standing on.
        """
        in_range = FakeMaps().places_near(BB["lat"], BB["lng"], 5.0)
        believed = {
            kind_key(kind)
            for place in in_range
            for kind in place.also_serves
            if all(kind_key(k) != kind_key(kind) for k in place.kinds)
        }
        for key in sorted(believed):
            kind = next(k for k in known_kinds() if kind_key(k) == key)
            found = await find_places(
                **BB,
                mode="walk",
                halal_only=False,
                cap_sen=1_000_000,
                room_sen=1_000_000,
                kind=kind,
            )
            for place in found.places:
                source = next(p for p in in_range if p.id == place.id)
                assert any(kind_key(k) == key for k in source.kinds), (place.name, kind)


class TestAKindWordInsideAPhrase:
    """People name food the way they eat it, not the way a column is headed.

    "fried chicken" is the dish; ``Chicken`` is the heading. Reading only the
    whole phrase sent "i want eat fried chicken" to the balance instead of the
    planner, which is the one sentence this feature exists for.
    """

    def test_an_adjective_in_front_does_not_hide_the_kind(self):
        assert resolve_kind("fried chicken") == "Chicken"
        assert resolve_kind("japanese food") == "Japanese"

    def test_a_two_word_kind_survives_a_trailing_word(self):
        assert resolve_kind("middle eastern food") == "Middle Eastern"

    def test_a_phrase_carrying_no_kind_still_resolves_to_nothing(self):
        # The rule this must not break: a word the data has no column for is
        # not a filter, because emptying a list for an unactionable reason is
        # worse than ignoring the word.
        for phrase in ("hawker", "something nice", "anywhere cheap", "a treat"):
            assert resolve_kind(phrase) is None, phrase

    def test_it_still_refuses_a_fragment_or_a_near_miss(self):
        # "chi" reaching both Chicken and Chinese, or "tea" reaching Steakhouse,
        # answers a question nobody asked.
        for fragment in ("chi", "tea", "steak", "noodl"):
            assert resolve_kind(fragment) is None, fragment
