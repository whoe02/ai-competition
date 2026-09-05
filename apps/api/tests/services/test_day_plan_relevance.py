"""find_places() with a model reading the request instead of matching a word.

The deterministic filter matches against the cuisines OpenStreetMap recorded,
which is two dozen words for the whole city: "beef", "satay" and "nasi lemak"
are none of them and every one of those searches comes back empty. A ranker is
handed in to answer the request itself.

Every ranker here is a stub. Nothing in this file reaches a network, and the
places are the ``place_world`` fixture rather than the shipped 189, so a data
refresh cannot change what any of it means.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest

from kira.services.day_plan import (
    CANDIDATE_PLACES,
    RANKED_PLACES,
    EvaluatedPlace,
    Judgement,
    find_places,
    price_landscape,
)
from tests.conftest import PLACE_WORLD, serving

# The four places a belief was recorded about: a burger shop believed to do
# chicken, a tagged chicken shop, one that is both, and a noodle shop that is
# neither. See ``conftest``.
BELIEVED = PLACE_WORLD.believed

BURGER = PLACE_WORLD.believed_chicken.id  # b1, tagged Burger, believed Chicken
TAGGED = PLACE_WORLD.tagged_chicken.id  # b2, tagged Chicken
BOTH = PLACE_WORLD.both_ways.id  # b3, tagged and believed Chicken
NOODLES = PLACE_WORLD.no_chicken.id  # b4, neither


def ranker(*judgements: Judgement):
    """A stub ``PlaceRanker`` that always answers with the same verdict."""

    async def rank(request: str, places: Sequence[EvaluatedPlace]):
        rank.asked.append((request, tuple(place.id for place in places)))
        return judgements

    rank.asked = []
    return rank


async def unreachable(request: str, places: Sequence[EvaluatedPlace]):
    """A ranker that has no answer — a timeout, a refusal, a missing key."""
    return None


def strong(place_id: str, serves: str = "") -> Judgement:
    return Judgement(place_id=place_id, strength="strong", serves=serves)


def weak(place_id: str, serves: str = "") -> Judgement:
    return Judgement(place_id=place_id, strength="weak", serves=serves)


async def search(*, request: str = "", rank=None, kind: str | None = None, cap_sen: int = 100_000):
    """The four believed-about places, searched from the fixture's origin."""
    with serving(places=BELIEVED):
        return await find_places(
            **PLACE_WORLD.origin,
            mode="walk",
            halal_only=False,
            cap_sen=cap_sen,
            room_sen=100_000,
            kind=kind,
            request=request,
            rank=rank,
        )


def by_id(found) -> dict[str, EvaluatedPlace]:
    return {place.id: place for place in found.places}


def judged(found) -> dict[str, EvaluatedPlace]:
    """Every place the model kept, wherever it was filed.

    A weak match leaves ``places`` for its own group, so a test about what the
    model *said* has to look in both — otherwise it is asserting about the
    grouping it did not mean to test.
    """
    return {place.id: place for place in (*found.places, *found.loose_matches)}


class TestNothingHandedIn:
    """The whole product while the feature is off, which is its default.

    A teammate on this checkout must see the search they had yesterday: the
    kind filter, no model, no wait. These are the same assertions the rest of
    the day-plan suite makes; they are here to say outright that handing in
    nothing is the untouched path rather than a new one that happens to agree.
    """

    async def test_no_ranker_leaves_the_kind_filter_in_charge(self):
        found = await search(kind="Chicken")

        assert set(by_id(found)) == {BURGER, TAGGED, BOTH}
        assert found.kind_count == 3

    async def test_no_ranker_says_the_ranking_was_the_deterministic_one(self):
        found = await search(kind="Chicken")

        assert found.ranking == "deterministic"

    async def test_a_request_with_no_ranker_narrows_nothing(self):
        """The sentence is inert on its own. Nothing reads it, so nothing acts
        on it: this is the search the user gets today, empty box or not."""
        found = await search(request="I want beef rendang")

        assert set(by_id(found)) == {BURGER, TAGGED, BOTH, NOODLES}
        assert found.ranking == "deterministic"
        assert found.near_misses == ()

    async def test_the_deterministic_path_still_says_why_it_kept_each_place(self):
        found = await search(kind="Chicken")
        places = by_id(found)

        # The two claims the old filter always made, now in words a row can
        # print. Neither needs a model and neither is new information.
        assert places[TAGGED].match_reason == "Tagged chicken"
        assert places[BURGER].match_reason == "Also serves chicken"
        # And no strength, because a word either matched or it did not.
        assert all(place.match_strength is None for place in found.places)

    async def test_a_search_that_asked_for_nothing_states_no_reason(self):
        found = await search()

        assert all(place.match_reason == "" for place in found.places)
        assert all(place.match_basis is None for place in found.places)


class TestAModelRanksTheList:
    async def test_the_places_it_named_are_the_list(self):
        found = await search(
            request="somewhere for beef", rank=ranker(strong(NOODLES), weak(BURGER))
        )

        # Both are the model's, and nothing else is. Which group each landed in
        # is the next test's business; this one is that the search is its answer
        # and not the word filter's.
        assert set(judged(found)) == {NOODLES, BURGER}
        assert set(by_id(found)) == {NOODLES}
        assert found.ranking == "model"

    async def test_it_is_given_the_request_and_every_place_in_range(self):
        rank = ranker(strong(NOODLES))

        await search(request="I feel like beef", rank=rank)

        request, offered = rank.asked[0]
        assert request == "I feel like beef"
        # Everything the halal filter left standing, priced — not a subset
        # chosen by a word first, which is the thing this replaces.
        assert set(offered) == {BURGER, TAGGED, BOTH, NOODLES}

    async def test_it_answers_a_request_the_word_filter_cannot(self):
        """"beef" is not one of the cuisines OpenStreetMap records, so the
        deterministic filter hands back nothing at all for it."""
        word_filter = await search(kind="beef")
        assert word_filter.places == ()

        ranked = await search(request="beef", rank=ranker(strong(NOODLES, "beef noodles")))
        assert set(by_id(ranked)) == {NOODLES}

    async def test_it_takes_the_place_of_the_kind_filter_rather_than_joining_it(self):
        """The two are not run one over the other. The word filter is the thing
        the model is there to replace, so a kind alongside a ranked request
        narrows nothing further -- otherwise the model's answer would arrive
        already cut down by the two dozen words it exists to get past."""
        found = await search(
            request="beef", kind="Chicken", rank=ranker(strong(NOODLES, "beef noodles"))
        )

        assert set(by_id(found)) == {NOODLES}

    async def test_a_model_that_finds_nothing_relevant_is_an_answer_not_a_failure(self):
        found = await search(request="sushi", rank=ranker())

        assert found.places == ()
        assert found.kind_count == 0
        # Not a fallback. It read the request, looked at the places and says
        # none of them answer it, and the screen may say so.
        assert found.ranking == "model"


class TestItMayOnlyChooseFromWhatItWasGiven:
    """The guardrail that separates this from the fabrication this project has
    already produced, which was a plausible-looking restaurant that does not
    exist. A model that can only return identifiers can only return places that
    were measured; an identifier nothing in range carries is not a place."""

    async def test_an_id_that_was_not_in_the_input_is_dropped(self):
        found = await search(
            request="sushi",
            rank=ranker(strong("sushi-tei-mid-valley", "sushi"), strong(NOODLES)),
        )

        assert set(by_id(found)) == {NOODLES}

    async def test_a_reply_made_entirely_of_invented_ids_returns_nothing(self):
        found = await search(
            request="sushi", rank=ranker(strong("not-a-place"), strong("nor-this-one"))
        )

        assert found.places == ()
        assert found.kind_count == 0

    async def test_the_same_id_twice_is_one_place(self):
        found = await search(request="chicken", rank=ranker(strong(TAGGED), weak(TAGGED)))

        assert [place.id for place in found.places] == [TAGGED]
        assert found.kind_count == 1

    async def test_the_first_verdict_on_an_id_is_the_one_that_stands(self):
        found = await search(request="chicken", rank=ranker(weak(TAGGED), strong(TAGGED)))

        assert judged(found)[TAGGED].match_strength == "weak"


class TestWhatARowCanSayForItself:
    """A place labelled Dessert answering a search for chicken is either a good
    answer or a bug, and the category alone does not say which."""

    async def test_a_kind_the_request_names_and_the_map_records_is_tagged(self):
        found = await search(request="chicken rice", rank=ranker(strong(TAGGED, "chicken")))

        place = by_id(found)[TAGGED]
        assert place.match_basis == "tagged"
        assert place.match_reason == "Tagged chicken"

    async def test_a_kind_the_request_names_and_a_belief_carries_is_inferred(self):
        found = await search(request="chicken", rank=ranker(strong(BURGER, "fried chicken")))

        place = by_id(found)[BURGER]
        assert place.match_basis == "inferred"
        # The build-time belief is what can be pointed at, so it is what the row
        # says -- the model's own account is only reached where nothing can be.
        assert place.match_reason == "Also serves chicken"

    async def test_a_match_nothing_in_the_data_supports_is_the_models_own(self):
        found = await search(request="beef", rank=ranker(strong(NOODLES, "beef noodles")))

        place = by_id(found)[NOODLES]
        assert place.match_basis == "judged"
        # Said as a belief, out loud. Drawn like a tagged row it would arrive
        # wearing the map's authority.
        assert place.match_reason == "The model thinks this serves beef noodles"

    async def test_a_model_that_says_nothing_about_the_food_quotes_the_request(self):
        found = await search(request="something warm", rank=ranker(strong(NOODLES)))

        expected = "The model thinks this answers “something warm”"
        assert by_id(found)[NOODLES].match_reason == expected

    async def test_every_row_says_how_strongly_it_was_judged(self):
        found = await search(request="chicken", rank=ranker(strong(TAGGED), weak(NOODLES)))

        places = judged(found)
        assert places[TAGGED].match_strength == "strong"
        assert places[NOODLES].match_strength == "weak"

    async def test_the_words_are_the_data_s_spelling_not_the_user_s(self):
        found = await search(request="any noodle", rank=ranker(strong(NOODLES)))

        assert by_id(found)[NOODLES].match_reason == "Tagged noodles"


class TestItRanksRelevanceAndNothingElse:
    """Money, distance and the bands are computed and provable, and the evidence
    panel depends on them staying that way."""

    async def test_no_figure_on_any_place_moves(self):
        untouched = by_id(await search())
        ranked = by_id(
            await search(
                request="beef",
                rank=ranker(strong(NOODLES, "beef"), strong(BURGER), strong(TAGGED), strong(BOTH)),
            )
        )

        assert set(ranked) == set(untouched)
        for place_id, place in ranked.items():
            before = untouched[place_id]
            # Compared as whole places with only the match stamp discounted, so
            # a figure this test never thought to name is still covered.
            assert replace(place, match_basis=None, match_strength=None, match_reason="") == before

    async def test_a_place_it_calls_strong_is_still_over_todays_room(self):
        with serving(places=BELIEVED):
            found = await find_places(
                **PLACE_WORLD.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=1000,
                request="beef",
                rank=ranker(strong(NOODLES, "beef")),
            )

        place = by_id(found)[NOODLES]
        # 1200 sen against 1000 of room. Relevance is not affordability, and the
        # band is not the model's to soften.
        assert place.total_sen == 1200
        assert place.band == "over"
        assert place.match_strength == "strong"

    async def test_the_ceiling_still_runs_after_it(self):
        found = await search(
            request="chicken",
            cap_sen=1600,
            rank=ranker(strong(BOTH, "chicken"), strong(TAGGED, "chicken")),
        )

        # Ayam Dua Kali is 1900 and does not fit, however strongly it matches.
        assert set(by_id(found)) == {TAGGED}
        # It was relevant, though, so the count above the ceiling says two.
        assert found.kind_count == 2

    async def test_money_still_orders_the_list_inside_one_verdict(self):
        found = await search(
            request="chicken",
            rank=ranker(strong(BOTH, "chicken"), strong(BURGER), strong(TAGGED)),
        )

        # 1600, 1600, 1900 — the order the model gave them in is not the order
        # they come back in, and the tag goes ahead of the belief on the tie.
        assert [place.id for place in found.places] == [TAGGED, BURGER, BOTH]

    async def test_a_weak_match_stands_behind_a_strong_one_however_cheap(self):
        found = await search(
            request="chicken", rank=ranker(weak(NOODLES), strong(BOTH, "chicken"))
        )

        # Mee Percaya is 1200 against Ayam Dua Kali's 1900, and still does not
        # lead: a weak match is not a cheaper version of the answer, so it
        # leaves the list entirely rather than sitting under it where a reader
        # skimming prices would meet it first.
        assert [place.id for place in found.places] == [BOTH]
        assert [place.id for place in found.loose_matches] == [NOODLES]


class TestFallingBack:
    async def test_a_ranker_with_no_answer_hands_the_search_to_the_kind_filter(self):
        found = await search(request="chicken", kind="Chicken", rank=unreachable)

        assert set(by_id(found)) == {BURGER, TAGGED, BOTH}
        assert found.ranking == "deterministic"

    async def test_the_fallback_is_the_untouched_filter_and_not_a_thinner_one(self):
        fallen_back = await search(request="chicken", kind="Chicken", rank=unreachable)
        never_asked = await search(kind="Chicken")

        assert fallen_back.places == never_asked.places
        assert fallen_back.kind_count == never_asked.kind_count
        assert fallen_back.near_misses == never_asked.near_misses

    async def test_a_ranker_with_no_answer_and_no_kind_narrows_nothing(self):
        found = await search(request="beef", rank=unreachable)

        assert set(by_id(found)) == {BURGER, TAGGED, BOTH, NOODLES}
        assert found.ranking == "deterministic"

    async def test_a_blank_request_never_reaches_the_ranker_at_all(self):
        rank = ranker(strong(NOODLES))

        found = await search(request="   ", kind="Chicken", rank=rank)

        assert rank.asked == []
        assert found.ranking == "deterministic"
        assert set(by_id(found)) == {BURGER, TAGGED, BOTH}


class TestTheCountsAndTheLandscapeStillAgree:
    async def test_kind_count_is_the_length_of_what_the_model_kept(self):
        found = await search(request="chicken", rank=ranker(strong(TAGGED), weak(BURGER)))

        assert found.kind_count == 2

    async def test_the_counts_still_nest(self):
        found = await search(request="chicken", rank=ranker(strong(TAGGED)))

        assert found.nearby_count >= found.matching_count >= found.kind_count
        assert found.kind_count >= len(found.places)

    async def test_the_landscape_is_the_same_whoever_ranked(self):
        """It is built before any of this and ignores the narrowing on purpose:
        when the answer to "I want noodles" is that there are none, the useful
        reply is what is there instead."""
        ranked = await search(request="beef", rank=ranker(strong(NOODLES, "beef")))
        unranked = await search()

        assert ranked.landscape == unranked.landscape

    async def test_every_landscape_row_still_counts_what_a_search_for_it_returns(self):
        ranked = await search(request="beef", rank=ranker(strong(NOODLES, "beef")))

        for row in ranked.landscape:
            of_that_kind = await search(kind=row.kind)
            assert of_that_kind.kind_count == row.count

    async def test_the_landscape_is_still_computed_off_the_priced_places(self):
        found = await search(request="beef", rank=ranker(strong(NOODLES, "beef")))

        with serving(places=BELIEVED):
            everything = await find_places(
                **PLACE_WORLD.origin,
                mode="walk",
                halal_only=False,
                cap_sen=100_000,
                room_sen=100_000,
            )
        assert found.landscape == price_landscape(everything.places)


class TestWhatTheModelTurnedAway:
    async def test_the_places_it_left_out_come_back_as_near_misses(self):
        found = await search(request="beef", rank=ranker(strong(NOODLES, "beef")))

        # Real places, really nearby, at prices this search measured — and not
        # matches. Nearest first, one per kind.
        assert [place.id for place in found.near_misses] == [BURGER, TAGGED]
        assert all(place.match_basis is None for place in found.near_misses)

    async def test_nothing_is_in_both_lists(self):
        found = await search(request="chicken", rank=ranker(strong(TAGGED), weak(BURGER)))

        kept = {place.id for place in found.places}
        assert kept.isdisjoint({place.id for place in found.near_misses})

    async def test_a_model_that_kept_everything_turns_nothing_away(self):
        found = await search(
            request="food",
            rank=ranker(strong(BURGER), strong(TAGGED), strong(BOTH), strong(NOODLES)),
        )

        assert found.near_misses == ()


class TestTheNearestAboveTheCeiling:
    async def test_it_is_offered_out_of_what_the_model_judged_relevant(self):
        found = await search(
            request="chicken",
            cap_sen=1000,
            rank=ranker(strong(TAGGED, "chicken"), strong(BOTH, "chicken")),
        )

        assert found.places == ()
        # Never relaxed back out to the places the model turned away: a widened
        # relevance nobody asked for is the same lie as a dropped "halal".
        assert [place.id for place in found.nearest_over_cap] == [TAGGED, BOTH]
        assert all(place.band == "over" for place in found.nearest_over_cap)

    async def test_it_keeps_the_reason_the_row_would_have_shown(self):
        found = await search(
            request="beef", cap_sen=1000, rank=ranker(strong(NOODLES, "beef noodles"))
        )

        offered = found.nearest_over_cap[0]
        assert offered.match_reason == "The model thinks this serves beef noodles"
        assert offered.match_strength == "strong"


def keeps(*ids: str):
    """A ranker that keeps whichever of the places in front of it are named.

    Keyed on what it is shown rather than answering with one fixed verdict,
    because the widened search asks twice — once about what is in range, and
    once about what is just outside it — and a stub that answered the second
    call with the first call's ids would be dropped whole by ``find_places``.
    """

    async def rank(request: str, places: Sequence[EvaluatedPlace]):
        rank.asked.append(tuple(place.id for place in places))
        return tuple(strong(place.id) for place in places if place.id in ids)

    rank.asked = []
    return rank


async def spread_search(*, request: str = "", rank=None, kind: str | None = None):
    """The ``spread`` world, which has places on both sides of the radius.

    The radius is pinned at the five kilometres that world was laid out around,
    which an explicit radius is still entitled to do. On foot, because that is
    the one mode with any room left to reach past its own radius --
    ``_reaches_past_radius``, and ``TestTheModeDecidesTheRadius`` in
    ``test_day_plan.py`` for why.
    """
    with serving(places=PLACE_WORLD.spread):
        return await find_places(
            **PLACE_WORLD.origin,
            mode="walk",
            halal_only=False,
            cap_sen=100_000,
            room_sen=100_000,
            radius_km=5.0,
            kind=kind,
            request=request,
            rank=rank,
        )


class TestHowManyPlacesTheModelIsShown:
    """A wide radius is not a licence to put a couple of hundred rows in a prompt.

    The ``throng`` world is 320 places packed into the twelve kilometres a Grab
    reaches, which is what a dense maps adapter looks like from the middle of
    town. Two separate bounds apply and they are different sizes on purpose: the
    search measures the nearest ``CANDIDATE_PLACES``, because that is what one
    routing call can carry, and the model is shown the nearest ``RANKED_PLACES``
    of those, because that is what a prompt should hold.
    """

    async def test_the_model_is_shown_the_nearest_few_and_not_the_whole_radius(self):
        rank = ranker()
        with serving(places=PLACE_WORLD.throng):
            found = await find_places(
                **PLACE_WORLD.origin,
                mode="ride",
                halal_only=False,
                cap_sen=1_000_000,
                room_sen=1_000_000,
                request="somewhere for beef",
                rank=rank,
            )

        assert len(rank.asked) == 1
        _, ids = rank.asked[0]
        assert len(ids) == RANKED_PLACES
        # Nearest first, so the prompt is the places the user is most likely to
        # be choosing between rather than an arbitrary slice.
        assert ids == tuple(f"t{index:03d}" for index in range(1, RANKED_PLACES + 1))
        # And the search itself is not bounded by that. It measured every place
        # one routing call can carry, and the counts still describe them.
        assert found.nearby_count == CANDIDATE_PLACES == found.matching_count
        # One kind across the whole throng, so the landscape is one row and it
        # counts every place the search measured rather than the sixty it asked
        # about.
        assert [row.count for row in found.landscape] == [CANDIDATE_PLACES]


class TestTheNearestBeyondTheRadius:
    """A model-narrowed search that came back thin reaches past the radius too.

    Narrowed by the same thing the list beside it was: a group chosen by the
    word filter sitting under a list chosen by a model would be two answers
    where ``ranking`` can only describe one.
    """

    async def test_a_thin_list_is_widened_by_asking_the_same_model_again(self):
        rank = keeps("s1", "s6", "s9")
        found = await spread_search(request="somewhere for a steak", rank=rank)

        assert found.ranking == "model"
        assert [place.id for place in found.places] == ["s1"]
        assert [place.id for place in found.nearest_beyond_radius] == ["s6", "s9"]
        # Twice: once about the places in range, once about the nearest few
        # outside it, and both shortlists are in distance order -- the four
        # noodle shops from 200 m out, then the western place at 2 km.
        assert rank.asked == [
            ("s2", "s3", "s4", "s5", "s1"),
            ("s6", "s7", "s8", "s12", "s9", "s10", "s11"),
        ]

    async def test_a_list_with_plenty_in_it_asks_nothing_further(self):
        rank = keeps("s2", "s3", "s4", "s5")
        found = await spread_search(request="noodles", rank=rank)

        assert len(found.places) == 4
        assert found.nearest_beyond_radius == ()
        # Not merely an empty group: the second call was never made, so a thick
        # list costs nothing extra.
        assert len(rank.asked) == 1

    async def test_a_model_that_cannot_answer_out_there_hands_back_nothing(self):
        # Falling through to the word filter for the group alone would put a
        # list narrowed by a model above a group narrowed by a word, with
        # ``ranking`` saying "model" over both of them.
        async def rank(request: str, places: Sequence[EvaluatedPlace]):
            rank.asked.append(tuple(place.id for place in places))
            return None if len(rank.asked) > 1 else (strong("s1"),)

        rank.asked = []
        found = await spread_search(request="somewhere for a steak", rank=rank)

        assert [place.id for place in found.places] == ["s1"]
        assert found.nearest_beyond_radius == ()
        assert len(rank.asked) == 2

    async def test_the_kind_narrows_nothing_out_there_either(self):
        # ``kind`` narrows nothing on the model path, and it may not quietly
        # start narrowing again a kilometre past the radius: the noodle shop out
        # there is in the group because the model kept it.
        rank = keeps("s1", "s12")
        found = await spread_search(request="somewhere for a steak", rank=rank, kind="Western")

        assert found.ranking == "model"
        assert [place.id for place in found.nearest_beyond_radius] == ["s12"]

    async def test_each_of_them_says_the_model_is_what_put_it_there(self):
        found = await spread_search(
            request="somewhere for a steak", rank=keeps("s1", "s6")
        )

        offered = found.nearest_beyond_radius[0]
        assert offered.match_basis == "judged"
        assert offered.match_reason == (
            "The model thinks this answers \u201csomewhere for a steak\u201d"
        )
        assert offered.match_strength == "strong"


@pytest.mark.parametrize("place", BELIEVED, ids=lambda place: place.id)
async def test_no_place_in_the_fixture_is_tagged_beef(place):
    """The premise of half this file: "beef" matches nothing in the data, which
    is exactly why a search for it needs somebody to read it."""
    assert not any("beef" in word.casefold() for word in (*place.kinds, *place.also_serves))
