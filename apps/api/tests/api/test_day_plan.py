"""The endpoint runs against the ``place_world`` fixture rather than the shipped
KL set, so a refresh of that data file cannot change what these tests mean."""

from sqlalchemy import select

from kira.db.models import TXN_CONFIRMED, Transaction, User
from kira.money import Money
from kira.seed.demo import DEMO_EMAIL, DEMO_PASSWORD, seed_demo_user
from kira.services.clock import today_for
from tests.conftest import StubRouting, serving


async def demo_token(client, session) -> str:
    await seed_demo_user(session)
    await session.commit()
    response = await client.post(
        "/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


class TestDayPlanAuth:
    async def test_requires_a_token(self, client, place_world):
        response = await client.get("/v1/day-plan/places", params=place_world.origin)
        assert response.status_code == 401


class TestHowFarTheSearchReaches:
    """The client sends a mode and no distance, and the mode decides.

    A flat five kilometres over the wire was an hour's walk and a nine-minute
    Grab at once. The ``ladder`` world is six places at 1.8, 2.1, 8.2, 8.7,
    12.3 and 13.0 km, each just inside or just outside one of the three radii
    the travel budgets work out to.
    """

    async def _ids(self, client, session, place_world, **params) -> list[str]:
        token = await demo_token(client, session)
        with serving(places=place_world.ladder):
            response = await client.get(
                "/v1/day-plan/places",
                params={**place_world.origin, "cap_sen": 100_000, **params},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200, response.text
        return [place["id"] for place in response.json()["places"]]

    async def test_the_mode_alone_changes_how_far_the_answer_reaches(
        self, client, session, place_world
    ):
        assert await self._ids(client, session, place_world, mode="walk") == ["g1"]
        assert await self._ids(client, session, place_world, mode="transit") == [
            "g1",
            "g2",
            "g3",
        ]
        assert await self._ids(client, session, place_world, mode="ride") == [
            "g1",
            "g2",
            "g3",
            "g4",
            "g5",
        ]

    async def test_walking_is_the_default_and_reaches_a_walk(
        self, client, session, place_world
    ):
        # No mode and no radius, which is the barest call a client can make.
        assert await self._ids(client, session, place_world) == ["g1"]

    async def test_a_radius_in_the_query_still_wins(self, client, session, place_world):
        assert await self._ids(
            client, session, place_world, mode="ride", radius_km=3.0
        ) == ["g1", "g2"]
        assert await self._ids(
            client, session, place_world, mode="walk", radius_km=9.0
        ) == ["g1", "g2", "g3", "g4"]

    async def test_a_radius_of_nothing_is_still_refused(self, client, session, place_world):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "radius_km": 0},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422


class TestDayPlanPlaces:
    async def test_returns_places_sorted_by_total_cost(self, client, session, place_world):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params=place_world.origin,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        places = body["places"]
        assert len(places) > 0
        totals = [p["total_sen"] for p in places]
        assert totals == sorted(totals)
        for place in places:
            assert place["band"] in ("ok", "tight", "over")
            assert place["total_sen"] >= place["travel_sen"] >= 0

    async def test_states_the_room_it_judged_against(self, client, session, place_world):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        dashboard = await client.get("/v1/dashboard/today", headers=headers)
        safe_today_sen = dashboard.json()["safe_today_sen"]

        response = await client.get(
            "/v1/day-plan/places",
            params=place_world.origin,
            headers=headers,
        )
        body = response.json()
        # Stated, not inferable: the client must never have to divide its way
        # back to this figure.
        assert body["room_sen"] == safe_today_sen

    async def test_omitting_cap_sen_defaults_to_todays_safe_to_spend(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        dashboard = await client.get("/v1/dashboard/today", headers=headers)
        assert dashboard.status_code == 200, dashboard.text
        safe_today_sen = dashboard.json()["safe_today_sen"]

        response = await client.get(
            "/v1/day-plan/places",
            params=place_world.origin,
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # With no cap_sen given, the endpoint must fall back to room_sen as the
        # cap, so nothing shown can cost more than today's safe-to-spend.
        assert body["cap_sen"] == safe_today_sen
        assert all(p["total_sen"] <= safe_today_sen for p in body["places"])

    async def test_reports_the_cap_it_actually_applied(self, client, session, place_world):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.json()["cap_sen"] == 100_000

    async def test_a_cap_sen_above_room_still_reports_bands_from_room(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        dashboard = await client.get("/v1/dashboard/today", headers=headers)
        safe_today_sen = dashboard.json()["safe_today_sen"]

        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 100_000},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # A generous cap_sen must not change what band a place lands in: band
        # is always computed from today's real safe-to-spend, not the cap.
        assert body["room_sen"] == safe_today_sen
        for place in body["places"]:
            share = place["total_sen"] / safe_today_sen if safe_today_sen > 0 else 2.0
            expected = "ok" if share <= 0.6 else "tight" if share <= 1.0 else "over"
            assert place["band"] == expected

    async def test_halal_only_excludes_non_halal_places(self, client, session, place_world):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "halal_only": True, "cap_sen": 100_000},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        places = response.json()["places"]
        assert places
        assert all(p["halal"] for p in places)

    async def test_never_leaks_a_float_for_money_fields(self, client, session, place_world):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params=place_world.origin,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert isinstance(body["room_sen"], int)
        assert isinstance(body["cap_sen"], int)
        for place in body["places"]:
            assert isinstance(place["total_sen"], int)
            assert isinstance(place["travel_sen"], int)
            assert isinstance(place["minutes"], int)


class TestFilteringByKindOfFood:
    """The screen's ask box can say "noodles" now, so the wire has to carry it
    — and has to echo back which kind the list it is answering with was
    actually built from, exactly as it echoes the ceiling."""

    async def test_it_returns_only_that_kind_and_says_which(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 100_000, "kind": "Cafe"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert [p["name"] for p in body["places"]] == [
            place_world.cheap.name,
            place_world.second_cafe.name,
        ]
        assert body["kind"] == "Cafe"
        assert body["kind_count"] == 2

    async def test_a_lowercase_or_plural_spelling_still_finds_it(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 100_000, "kind": "noodle"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert [p["name"] for p in response.json()["places"]] == [place_world.noodles.name]

    async def test_asking_for_nothing_in_particular_leaves_the_list_whole(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        body = response.json()
        assert body["kind"] is None
        assert body["kind_count"] == body["matching_count"] == len(body["places"])

    async def test_a_kind_that_is_not_here_is_told_apart_from_a_ceiling(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}
        # Pinned to the five kilometres the fixed world was laid out around, so
        # that all seven places are what these counts are counting.
        params = {**place_world.origin, "cap_sen": 100_000, "radius_km": 5.0}

        no_such_food = await client.get(
            "/v1/day-plan/places", params={**params, "kind": "Korean"}, headers=headers
        )
        by_ceiling = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 1, "radius_km": 5.0},
            headers=headers,
        )

        assert no_such_food.json()["places"] == by_ceiling.json()["places"] == []
        # Two identical empty lists, and the counts are the only thing that
        # tells a slider the user can drag from a kind of food that is not in
        # this part of town.
        assert no_such_food.json()["kind_count"] == 0
        assert no_such_food.json()["matching_count"] == 7
        assert by_ceiling.json()["kind_count"] == by_ceiling.json()["matching_count"] == 7


class TestWhyEachPlaceMatchedTheKind:
    """A wider list is only worth having if the client can still read it.

    The filter reaches what OpenStreetMap states about a place and what a model
    believes it also serves, so a chicken search comes back with the burger shop
    that fries chicken. Those are not the same kind of truth, and the wire has to
    carry which is which -- a screen left to guess would draw them alike.
    """

    async def _places(self, client, session, place_world, **params) -> list[dict]:
        token = await demo_token(client, session)
        with serving(places=place_world.believed):
            response = await client.get(
                "/v1/day-plan/places",
                params={**place_world.origin, "cap_sen": 100_000, **params},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200, response.text
        return response.json()["places"]

    async def test_every_row_says_which_kind_of_match_it_is(
        self, client, session, place_world
    ):
        places = await self._places(client, session, place_world, kind="Chicken")
        assert [(p["name"], p["match_basis"]) for p in places] == [
            (place_world.tagged_chicken.name, "tagged"),
            (place_world.believed_chicken.name, "inferred"),
            (place_world.both_ways.name, "tagged"),
        ]

    async def test_a_list_nobody_narrowed_carries_the_field_and_leaves_it_null(
        self, client, session, place_world
    ):
        # Present rather than omitted: a field a client may find missing is a
        # field a client will forget to read. Null because nothing was matched.
        places = await self._places(client, session, place_world)
        assert len(places) == 4
        assert all(p["match_basis"] is None for p in places)

    async def test_a_believed_row_is_still_shown_under_its_own_kind(
        self, client, session, place_world
    ):
        # The one guard on everything the screen says about it: matching wider
        # does not relabel a shop. The burger place is still a burger place.
        places = await self._places(client, session, place_world, kind="Chicken")
        believed = next(p for p in places if p["match_basis"] == "inferred")
        assert believed["kind"] == place_world.believed_chicken.kind == "Burger"


class TestWhatTheDistanceWasMeasuredOn:
    """The screen has to be able to say whether a fare is a road fare.

    A ride quoted on the great circle can be half the real one in KL, so the
    wire carries the basis for every place and the road figure beside it. The
    client is never left to infer either.
    """

    async def test_every_place_states_its_basis_and_a_road_figure_or_null(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "mode": "ride", "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        places = response.json()["places"]
        assert places
        for place in places:
            assert place["distance_basis"] in ("road", "straight_line")
            if place["distance_basis"] == "road":
                assert place["road_km"] == place["km"]
            else:
                # Nothing to show beside the straight line, and null rather
                # than the straight-line figure repeated under a road label.
                assert place["road_km"] is None

    async def test_with_no_router_it_says_straight_line_rather_than_going_quiet(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "mode": "ride", "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        places = response.json()["places"]
        assert places
        assert {p["distance_basis"] for p in places} == {"straight_line"}

    async def test_a_routed_search_prices_on_the_road_and_says_so(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}
        params = {**place_world.origin, "mode": "ride", "cap_sen": 100_000}

        # Mamak Dua is 500 m in a straight line and 1.2 km of road: RM5.95 of
        # fare against RM7.28.
        with serving(StubRouting({"w2": 1200.0})):
            response = await client.get("/v1/day-plan/places", params=params, headers=headers)
        assert response.status_code == 200, response.text
        routed = next(
            p for p in response.json()["places"] if p["name"] == place_world.mid.name
        )
        assert routed["distance_basis"] == "road"
        assert routed["road_km"] == 1.2
        assert routed["travel_sen"] == 728

        unrouted = await client.get("/v1/day-plan/places", params=params, headers=headers)
        same = next(
            p for p in unrouted.json()["places"] if p["name"] == place_world.mid.name
        )
        assert same["distance_basis"] == "straight_line"
        assert same["travel_sen"] == 595

    async def test_every_place_carries_an_address(self, client, session, place_world):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        places = response.json()["places"]
        assert places
        assert all(p["address"] for p in places)

    async def test_every_place_carries_the_point_it_stands_on(
        self, client, session, place_world
    ):
        """An address is not always enough to find the shop again.

        A quarter of the shipped addresses name a locality rather than a
        doorstep, and several names in that set belong to two branches, so a
        client sending the user to a map has to be able to send them to this
        one. The coordinates are the adapter's own, echoed untouched -- the
        distance work above must not have moved them.
        """
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        by_name = {p["name"]: p for p in response.json()["places"]}
        assert by_name
        for known in place_world.places:
            if known.name in by_name:
                assert by_name[known.name]["lat"] == known.lat
                assert by_name[known.name]["lng"] == known.lng


class TestWhyTheListIsEmpty:
    """An empty list has three causes and the client must not have to guess:
    a ceiling too low is the user's to move, a halal toggle is theirs to switch
    off, and distance is neither."""

    async def test_it_reports_how_many_places_were_in_range(self, client, session, place_world):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        body = response.json()
        assert body["nearby_count"] == len(body["places"])
        assert body["matching_count"] == len(body["places"])

    async def test_out_of_range_reports_nil_in_range_and_no_places(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.out_of_range, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["nearby_count"] == 0
        assert body["matching_count"] == 0
        assert body["places"] == []

    async def test_a_halal_filter_that_admits_nothing_is_told_apart_from_a_ceiling(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}
        # Chophouse Lima is 4.9 km from here, which is a walk nobody takes: the
        # radius is pinned so that the halal filter is the only thing left that
        # can empty this list.
        params = {**place_world.lone_non_halal, "cap_sen": 100_000, "radius_km": 5.0}

        response = await client.get(
            "/v1/day-plan/places", params={**params, "halal_only": True}, headers=headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # A place is in range and the ceiling is RM1,000. Neither is the cause,
        # and a client told only "nearby_count > 0" would blame the ceiling and
        # send the user at a slider that cannot reach it.
        assert body["places"] == []
        assert body["nearby_count"] == 1
        assert body["matching_count"] == 0

        relaxed = await client.get(
            "/v1/day-plan/places", params={**params, "halal_only": False}, headers=headers
        )
        shown = relaxed.json()
        assert [p["name"] for p in shown["places"]] == [place_world.far_non_halal.name]
        assert shown["matching_count"] == 1

    async def test_the_counts_nest_so_the_first_nil_one_is_the_cause(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "halal_only": True, "cap_sen": 1000},
            headers={"Authorization": f"Bearer {token}"},
        )
        body = response.json()
        assert body["nearby_count"] > body["matching_count"] > len(body["places"])

    async def test_a_ceiling_too_low_reports_places_in_range_and_none_shown(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # Same empty list as the out-of-range case above, and the only thing
        # that tells the two apart is this count -- which is the whole point.
        assert body["places"] == []
        assert body["nearby_count"] > 0
        # Nothing was filtered out for not being halal, so the ceiling is the
        # cause and is the one thing the copy may point the user at.
        assert body["matching_count"] == body["nearby_count"]


class TestTheNearestPlacesAboveTheCeiling:
    """A ceiling below everything comes back with somewhere to eat anyway.

    In its own field, never in ``places``: a client must not be able to render
    these as though they had fitted, and the wire shape is the first thing that
    has to make that impossible.
    """

    async def test_a_ceiling_below_everything_returns_the_nearest_group(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 500},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["places"] == []
        assert [p["name"] for p in body["nearest_over_cap"]] == [
            place_world.cheap.name,
            place_world.mid.name,
            place_world.near_non_halal.name,
        ]
        # Named as over on the row itself, not only by the field they arrived
        # in, so a client that draws them has the distinction in its hand.
        assert all(p["band"] == "over" for p in body["nearest_over_cap"])
        assert all(p["total_sen"] > body["cap_sen"] for p in body["nearest_over_cap"])

    async def test_a_ceiling_that_admits_some_places_carries_no_group(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 1000},
            headers={"Authorization": f"Bearer {token}"},
        )
        body = response.json()
        assert [p["name"] for p in body["places"]] == [place_world.cheap.name]
        assert body["nearest_over_cap"] == []

    async def test_the_field_is_always_there_even_when_it_is_empty(
        self, client, session, place_world
    ):
        # A field a client may find missing is a field a client will forget to
        # read, and this is the one list it must never quietly omit.
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        body = response.json()
        assert body["places"] != []
        assert body["nearest_over_cap"] == []

    async def test_an_empty_list_no_ceiling_caused_offers_nothing(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}
        out_of_range = await client.get(
            "/v1/day-plan/places",
            params={**place_world.out_of_range, "cap_sen": 100_000},
            headers=headers,
        )
        no_halal = await client.get(
            "/v1/day-plan/places",
            params={**place_world.lone_non_halal, "cap_sen": 100_000, "halal_only": True},
            headers=headers,
        )
        for response in (out_of_range, no_halal):
            body = response.json()
            assert body["places"] == []
            assert body["nearest_over_cap"] == []

    async def test_the_group_still_honours_halal(self, client, session, place_world):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 500, "halal_only": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        body = response.json()
        assert body["places"] == []
        assert all(p["halal"] for p in body["nearest_over_cap"])



class TestTheNearestPlacesBeyondTheRadius:
    """A narrowed search that came back thin carries what is just outside it.

    In its own field, exactly as the over-the-ceiling group is: every one of
    these is further away than the client asked for, and the wire shape is the
    first thing that has to make it impossible to draw them as though they were
    not.
    """

    async def _body(self, client, session, place_world, **params):
        token = await demo_token(client, session)
        with serving(places=place_world.spread):
            response = await client.get(
                "/v1/day-plan/places",
                # On foot, and pinned to the five kilometres this world was laid
                # out around. Walking is the one mode that reaches past its own
                # radius at all -- the other two spend the longest journey this
                # app suggests getting to what is already in ``places``.
                params={
                    **place_world.origin,
                    "cap_sen": 100_000,
                    "mode": "walk",
                    "radius_km": 5.0,
                    **params,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200, response.text
        return response.json()

    async def test_a_thin_narrowed_search_carries_the_group(
        self, client, session, place_world
    ):
        body = await self._body(client, session, place_world, kind="Western")

        assert [p["name"] for p in body["places"]] == [place_world.near_western.name]
        assert [p["name"] for p in body["nearest_beyond_radius"]] == [
            place_world.just_past_the_line.name,
            place_world.dear_and_far.name,
            place_world.non_halal_and_far.name,
            "Barat Jauh Dua",
        ]
        # The real distance for the longer journey is on every row, which is the
        # figure a client needs in order to say what this group is.
        assert all(p["km"] > 5.0 for p in body["nearest_beyond_radius"])

    async def test_a_search_with_plenty_nearby_carries_none(
        self, client, session, place_world
    ):
        body = await self._body(client, session, place_world, kind="Noodles")

        assert len(body["places"]) == 4
        assert body["nearest_beyond_radius"] == []

    async def test_an_unfiltered_browse_carries_none(self, client, session, place_world):
        body = await self._body(client, session, place_world)

        assert body["places"] != []
        assert body["nearest_beyond_radius"] == []

    async def test_the_field_is_always_there_even_when_it_is_empty(
        self, client, session, place_world
    ):
        # A field a client may find missing is a field a client will forget to
        # read, and this one carries places the user did not ask to be shown.
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 100_000},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.json()["nearest_beyond_radius"] == []

    async def test_nothing_is_in_two_groups_at_once(self, client, session, place_world):
        body = await self._body(client, session, place_world, kind="Western")

        beyond = {p["id"] for p in body["nearest_beyond_radius"]}
        assert beyond
        assert not beyond & {p["id"] for p in body["places"]}
        assert not beyond & {p["id"] for p in body["nearest_over_cap"]}

    async def test_the_counts_still_describe_what_is_in_range(
        self, client, session, place_world
    ):
        # The counts are how a client tells five empty lists apart. A group from
        # outside the radius must not be able to move one of them.
        body = await self._body(client, session, place_world, kind="Western")

        assert body["nearby_count"] == 5
        assert body["matching_count"] == 5
        assert body["kind_count"] == 1
        assert body["kind_count"] == len(body["places"])
        assert len(body["nearest_beyond_radius"]) == 4

    async def test_the_group_still_honours_halal_and_the_ceiling(
        self, client, session, place_world
    ):
        body = await self._body(
            client, session, place_world, kind="Western", halal_only=True, cap_sen=3000
        )

        assert all(p["halal"] for p in body["nearest_beyond_radius"])
        assert all(p["total_sen"] <= body["cap_sen"] for p in body["nearest_beyond_radius"])
        names = {p["name"] for p in body["nearest_beyond_radius"]}
        assert place_world.non_halal_and_far.name not in names
        assert place_world.dear_and_far.name not in names

    async def test_the_journey_on_the_wire_is_the_longer_one(
        self, client, session, place_world
    ):
        # The road the router reported, not the great circle the radius was
        # drawn with. On foot that shows up on the clock rather than in the
        # fare, because walking costs nothing but time -- and this group only
        # ever appears on foot.
        token = await demo_token(client, session)
        with serving(
            StubRouting({"s6": 6000.0}, places=place_world.spread), places=place_world.spread
        ):
            response = await client.get(
                "/v1/day-plan/places",
                params={
                    **place_world.origin,
                    "cap_sen": 100_000,
                    "kind": "Western",
                    "mode": "walk",
                    "radius_km": 5.0,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        routed = next(
            p
            for p in response.json()["nearest_beyond_radius"]
            if p["name"] == place_world.just_past_the_line.name
        )
        assert routed["distance_basis"] == "road"
        assert routed["road_km"] == 6.0
        # 13 min/km over 6 km of road plus the six-minute buffer, where the
        # 5.1 km straight line would have said 72.
        assert routed["minutes"] == 84

class TestDayOnWhichNothingIsLeft:
    """A day already spent out is the state the whole product exists for."""

    async def test_room_is_reported_as_zero_not_left_to_be_inferred(
        self, client, session, place_world
    ):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        # Spend today's whole allowance, so safe-to-spend floors at zero.
        user = (
            await session.execute(select(User).where(User.email == DEMO_EMAIL))
        ).scalar_one()
        today = today_for()
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

        dashboard = await client.get("/v1/dashboard/today", headers=headers)
        assert dashboard.json()["safe_today_sen"] == 0

        # The cap is what the user dragged the ceiling to; the room is still nil.
        response = await client.get(
            "/v1/day-plan/places",
            params={**place_world.origin, "cap_sen": 5000},
            headers=headers,
        )
        body = response.json()
        assert body["room_sen"] == 0
        assert body["cap_sen"] == 5000
        assert body["places"], "a raised ceiling should still surface places"
        # No share at all, rather than a stand-in a client could turn into a
        # percentage or divide by to recover a room that is not there.
        for place in body["places"]:
            assert place["band"] == "over"
            assert place["share"] is None

    async def test_with_no_ceiling_given_nothing_is_offered(self, client, session, place_world):
        token = await demo_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}

        user = (
            await session.execute(select(User).where(User.email == DEMO_EMAIL))
        ).scalar_one()
        session.add(
            Transaction(
                user_id=user.id,
                merchant="Blowout",
                amount=Money(500_000, user.currency),
                occurred_on=today_for(),
                category="food",
                status=TXN_CONFIRMED,
                source="manual",
                note="",
            )
        )
        await session.commit()

        response = await client.get(
            "/v1/day-plan/places",
            params=place_world.origin,
            headers=headers,
        )
        body = response.json()
        # The cap defaults to the room, and the room is nil: the honest answer
        # is an empty list under a stated ceiling of zero, not a stocked one.
        assert body["cap_sen"] == 0
        assert body["places"] == []


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestAddingAPlanToToday:
    """POST /v1/day-plan/drafts. A plan is an intention, and an intention that
    moved today's figure would be spending the user's money on a tap."""

    async def test_requires_a_token(self, client):
        response = await client.post(
            "/v1/day-plan/drafts",
            json={"name": "Kopi Kaki", "total_sen": 1750, "confidence": "high"},
        )
        assert response.status_code == 401

    async def test_creates_one_draft_at_the_whole_outing_price(self, client, session):
        token = await demo_token(client, session)
        before = (await client.get("/v1/transactions", headers=auth(token))).json()

        response = await client.post(
            "/v1/day-plan/drafts",
            json={"name": "Kopi Kaki", "total_sen": 1750, "confidence": "high"},
            headers=auth(token),
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["merchant"] == "Kopi Kaki"
        assert body["amount_sen"] == 1750
        assert body["status"] == "draft"
        assert body["source"] == "plan"
        assert body["category"] == "food"
        assert body["confidence"] == 70
        # The server's clock, not the client's: the demo day is pinned, and a
        # browser in another timezone must not date a draft to its own today.
        assert body["occurred_on"] == today_for().isoformat()

        after = (await client.get("/v1/transactions", headers=auth(token))).json()
        assert len(after["drafts"]) == len(before["drafts"]) + 1
        assert after["draft_total_sen"] == before["draft_total_sen"] + 1750

    async def test_it_is_waiting_in_activity_with_the_other_drafts(self, client, session):
        token = await demo_token(client, session)
        created = (
            await client.post(
                "/v1/day-plan/drafts",
                json={"name": "Kopi Kaki", "total_sen": 1750, "confidence": "high"},
                headers=auth(token),
            )
        ).json()

        listed = (await client.get("/v1/transactions", headers=auth(token))).json()

        # Nothing new was built for this: the ledger already surfaces drafts,
        # and a plan is one.
        waiting = next(draft for draft in listed["drafts"] if draft["id"] == created["id"])
        assert waiting["source"] == "plan"
        assert waiting["category_label"] == "Food & drink"
        assert "estimate" in waiting["note"]
        assert "Nothing counts against today until you confirm it." in waiting["note"]
        # Not on the ledger: that is confirmed spending, and this is an intention.
        on_ledger = {txn["id"] for day in listed["days"] for txn in day["transactions"]}
        assert created["id"] not in on_ledger

    async def test_todays_figure_does_not_move_until_it_is_confirmed(self, client, session):
        token = await demo_token(client, session)
        before = (await client.get("/v1/dashboard/today", headers=auth(token))).json()

        created = (
            await client.post(
                "/v1/day-plan/drafts",
                json={"name": "Omakase Empat", "total_sen": 5000, "confidence": "low"},
                headers=auth(token),
            )
        ).json()
        during = (await client.get("/v1/dashboard/today", headers=auth(token))).json()

        await client.post(f"/v1/transactions/{created['id']}/confirm", headers=auth(token))
        after = (await client.get("/v1/dashboard/today", headers=auth(token))).json()

        # RM50.00 of intention costs nothing at all. The row exists — the count
        # of drafts waiting proves it — and still the day is untouched.
        assert during["safe_today_sen"] == before["safe_today_sen"] == 5297
        assert during["spent_today_sen"] == before["spent_today_sen"]
        assert during["drafts_waiting"] == before["drafts_waiting"] + 1
        # Confirmed, and only now, the money leaves.
        assert after["safe_today_sen"] == 70
        assert after["drafts_waiting"] == before["drafts_waiting"]

    async def test_maps_each_confidence_band(self, client, session):
        token = await demo_token(client, session)

        read = {}
        for band in ("high", "medium", "low"):
            response = await client.post(
                "/v1/day-plan/drafts",
                json={"name": f"Place {band}", "total_sen": 1000, "confidence": band},
                headers=auth(token),
            )
            read[band] = response.json()["confidence"]

        # The band is the client's; the percentage is the server's, so two
        # clients cannot come to different answers about what "high" is worth.
        assert read == {"high": 70, "medium": 50, "low": 30}

    async def test_an_unfamiliar_band_is_taken_as_the_least_certain(self, client, session):
        token = await demo_token(client, session)

        response = await client.post(
            "/v1/day-plan/drafts",
            json={"name": "Kopi Kaki", "total_sen": 1750, "confidence": "astonishing"},
            headers=auth(token),
        )

        # The place data is regenerated, so an unknown word costs the user their
        # tap rather than being promoted into certainty nothing supports.
        assert response.status_code == 201, response.text
        assert response.json()["confidence"] == 30

    async def test_refuses_an_outing_that_costs_nothing(self, client, session):
        token = await demo_token(client, session)
        response = await client.post(
            "/v1/day-plan/drafts",
            json={"name": "Kopi Kaki", "total_sen": 0, "confidence": "high"},
            headers=auth(token),
        )
        assert response.status_code == 422

    async def test_refuses_a_place_with_no_name(self, client, session):
        token = await demo_token(client, session)
        response = await client.post(
            "/v1/day-plan/drafts",
            json={"name": "", "total_sen": 1750, "confidence": "high"},
            headers=auth(token),
        )
        assert response.status_code == 422

    async def test_a_plan_is_correctable_like_any_other_draft(self, client, session):
        token = await demo_token(client, session)
        created = (
            await client.post(
                "/v1/day-plan/drafts",
                json={"name": "Kopi Kaki", "total_sen": 1750, "confidence": "high"},
                headers=auth(token),
            )
        ).json()

        # The bill came to more than the estimate, which is the ordinary case
        # this whole path exists to survive.
        corrected = await client.patch(
            f"/v1/transactions/{created['id']}",
            json={"amount_sen": 2010},
            headers=auth(token),
        )

        assert corrected.status_code == 200, corrected.text
        assert corrected.json()["amount_sen"] == 2010
        assert corrected.json()["source"] == "plan"
        # An estimate the user has overwritten is no longer an estimate.
        assert corrected.json()["confidence"] is None
