"""Shared fixtures. Database tests run against in-memory SQLite without Docker."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

os.environ.setdefault("DEMO_TODAY", "2026-09-03")
os.environ.setdefault("JWT_SECRET", "test-secret-for-kira-auth-tests-123456")
# The suite runs against the deterministic model, always. A developer with a
# real key in their .env would otherwise send every un-stubbed turn to the
# vendor: slow, billable, and impossible to assert prose against.
os.environ.setdefault("BUTLER_OFFLINE", "true")
# Same reasoning for the router: left on, every day-plan test would put a real
# HTTP request to a volunteer-run public service on the critical path of the
# suite, and its fares would depend on what OSRM said that morning. The fixture
# below hands the planner a router that answers nothing, and the tests that
# care about road distance hand it one that answers known metres.
os.environ.setdefault("ROUTING_ENABLED", "false")

import math
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from kira.adapters import registry
from kira.adapters.fakes import FakeMaps, NoRouting
from kira.adapters.protocols import Place, RoutingAdapter
from kira.adapters.registry import get_adapters
from kira.db.base import Base
from kira.db.session import get_session
from kira.money import Money


@pytest.fixture
async def engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
async def client(session) -> AsyncGenerator[AsyncClient, None]:
    from kira.api.app import create_app

    app = create_app()

    async def override() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# --- the day planner's small fixed world ------------------------------------

# One degree of latitude on the sphere haversine_km measures against, so a place
# offset this way sits exactly the stated number of kilometres from the origin.
_KM_PER_DEGREE_LAT = 6371.0 * math.pi / 180

# Suria KLCC, which is also what the day-plan tool falls back to when the user
# has not shared a location.
_ORIGIN_LAT = 3.1577
_ORIGIN_LNG = 101.7120


def _north(km: float) -> float:
    """A latitude exactly ``km`` north of the origin on its meridian, or south
    of it for a negative ``km``."""
    return _ORIGIN_LAT + km / _KM_PER_DEGREE_LAT


@dataclass(frozen=True, slots=True)
class PlaceWorld:
    """Seven places with round prices at known distances, and the origins to
    search them from. Each origin is a dict so it can be splatted straight into
    ``find_places``, the endpoint's query params, or ``PlanArgs``.

    Seven kinds of food across them, deliberately: two cafes, so a kind filter
    can return more than one place and a price landscape can count them; one
    kind spelled as a plural (``Noodles``), so a search for "noodle" has
    something to be forgiving about; and the rest one apiece.

    ``crowd`` is a separate, larger world for the one question the seven cannot
    answer: what a caller does when there are more places than it means to hand
    back. ``multi_kind`` is a separate world for another one: a place that
    serves two kinds of food. ``believed`` is a third, for what a model thinks a
    place serves beyond its tags. ``spread`` is a fourth, for the only question
    that needs places outside the 5 km radius at all. ``ladder`` is a fifth, for
    how far each mode reaches, and ``throng`` a sixth, for how many places one
    search will look at. Nothing else uses any of them, so the seven stay small
    enough to reason about.
    """

    places: tuple[Place, ...]
    crowd: tuple[Place, ...]
    multi_kind: tuple[Place, ...]
    believed: tuple[Place, ...]
    spread: tuple[Place, ...]
    ladder: tuple[Place, ...]
    throng: tuple[Place, ...]
    origin: dict[str, float]
    out_of_range: dict[str, float]
    lone_non_halal: dict[str, float]
    spread_outskirts: dict[str, float]
    cheap: Place
    mid: Place
    near_non_halal: Place
    pricey: Place
    far_non_halal: Place
    noodles: Place
    second_cafe: Place
    two_kinds: Place
    one_kind: Place
    other_kind: Place
    tagged_chicken: Place
    believed_chicken: Place
    both_ways: Place
    no_chicken: Place
    near_western: Place
    just_past_the_line: Place
    dear_and_far: Place
    non_halal_and_far: Place
    far_noodles: Place
    beyond_the_reach: Place


_CHEAP = Place(
    "w1",
    "Kopi Kaki",
    "Cafe",
    _north(0.05),
    _ORIGIN_LNG,
    Money(900),
    "high",
    True,
    "50 m away, inside the no-fare radius.",
    address="1 Jalan Satu, Kuala Lumpur",
)
_MID = Place(
    "w2",
    "Mamak Dua",
    "Mamak",
    _north(0.5),
    _ORIGIN_LNG,
    Money(1250),
    "high",
    True,
    "500 m away.",
    address="2 Jalan Dua, Kuala Lumpur",
)
_NEAR_NON_HALAL = Place(
    "w3",
    "Bak Kut Teh Tiga",
    "Chinese",
    _north(-1.0),
    _ORIGIN_LNG,
    Money(1600),
    "medium",
    False,
    "1 km away.",
    address="3 Jalan Tiga, Kuala Lumpur",
)
_PRICEY = Place(
    "w4",
    "Omakase Empat",
    "Japanese",
    _north(2.0),
    _ORIGIN_LNG,
    Money(5000),
    "low",
    True,
    "2 km away, and the most expensive of the seven.",
    address="4 Jalan Empat, Kuala Lumpur",
)
_FAR_NON_HALAL = Place(
    "w5",
    "Chophouse Lima",
    "Western",
    _north(-4.0),
    _ORIGIN_LNG,
    Money(2000),
    "medium",
    False,
    "4 km away, and the only one a search from the south can reach.",
    address="5 Jalan Lima, Kuala Lumpur",
)

_NOODLES = Place(
    "w6",
    "Mee Enam",
    # The one plural kind in the world. A search for "noodle" has to reach it,
    # and a search for "noodles" has to reach it too.
    "Noodles",
    _north(0.8),
    _ORIGIN_LNG,
    Money(1800),
    "high",
    True,
    "800 m away.",
    address="6 Jalan Enam, Kuala Lumpur",
)
_SECOND_CAFE = Place(
    "w7",
    "Kopi Tujuh",
    # The same kind as Kopi Kaki, so a kind filter can return two places and a
    # landscape row can count more than one.
    "Cafe",
    _north(1.2),
    _ORIGIN_LNG,
    Money(1900),
    "medium",
    True,
    "1.2 km away, and the dearer of the two cafes.",
    address="7 Jalan Tujuh, Kuala Lumpur",
)

# Thirteen halal places at one price each, a ringgit apart, close enough to the
# origin that walking is free — so the whole outing is the meal and the order is
# the price order, with no arithmetic in the way. Thirteen because the tool
# hands back twelve: a world of exactly the cap could not tell a list that was
# capped from one that simply ended.
_CROWD: tuple[Place, ...] = tuple(
    Place(
        f"c{index}",
        f"Warung {index:02d}",
        # Cycled so the landscape has several rows to sort, and so the cheapest
        # of a kind is not always the first place of it.
        ("Malaysian", "Noodles", "Cafe", "Indian")[index % 4],
        _north(0.05 + index / 100),
        _ORIGIN_LNG,
        Money(1000 + index * 100),
        "high",
        True,
        f"Number {index} of the crowd.",
        address=f"{index} Jalan Ramai, Kuala Lumpur",
    )
    for index in range(1, 14)
)

# A world of three for the one thing the seven cannot show: a place
# OpenStreetMap gives more than one cuisine. Nando's is the real case --
# ``cuisine=chicken;portuguese`` -- and a fifth of the places OSM knows
# anything about are like it. Kept apart from the seven so that every count
# over there stays as easy to read as it was, and all within walking distance
# so the whole outing is the meal.
_TWO_KINDS = Place(
    "k1",
    "Ayam Piri Piri",
    # The label, and the kind the estimate was banded from. "Portuguese" is
    # only ever matched on -- and it is deliberately a word the shipped
    # vocabulary does not have, because the filter matches against the places
    # in range rather than against that vocabulary.
    "Chicken",
    _north(0.5),
    _ORIGIN_LNG,
    Money(1600),
    "high",
    True,
    "Chicken and Portuguese, tagged the way OSM tags Nando's.",
    address="1 Jalan Ayam, Kuala Lumpur",
    kinds=("Chicken", "Portuguese"),
)
_ONE_KIND = Place(
    "k2",
    "Ayam Gunting",
    # The same kind as the one above and nothing else, and dearer -- so a
    # search for chicken has two to return and the cheaper of them is the one
    # carrying the second kind.
    "Chicken",
    _north(1.0),
    _ORIGIN_LNG,
    Money(2400),
    "high",
    True,
    "Chicken and only chicken.",
    address="2 Jalan Ayam, Kuala Lumpur",
)
_OTHER_KIND = Place(
    "k3",
    "Mamak Ketiga",
    "Mamak",
    _north(1.5),
    _ORIGIN_LNG,
    Money(1200),
    "high",
    True,
    "The cheapest of the three, and nothing to do with chicken.",
    address="3 Jalan Ayam, Kuala Lumpur",
)

# A world of four for what a model believes about a menu. OpenStreetMap tags
# McDonald's ``burger`` and stops there, and that it fries chicken all day is
# world knowledge no tag carries -- so the generator asks a model once and ships
# the answer in ``also_serves``. A kind filter matches either, and every place
# it returns has to say which of the two kept it.
#
# All within walking distance, so the whole outing is the meal and every total
# below is the price written here. The order matters and is not alphabetical:
# the believed chicken place stands ahead of the tagged one at the same price,
# so a run that had forgotten to rank a tag above a belief would hand back the
# belief first.
_BELIEVED_CHICKEN = Place(
    "b1",
    "Burger Bakar Satu",
    # The McDonald's case exactly: tagged one thing, believed to also do
    # another. A search for Burger finds it on a tag and a search for Chicken
    # finds it on a belief -- the same place, and not the same claim.
    "Burger",
    _north(0.2),
    _ORIGIN_LNG,
    Money(1600),
    "high",
    True,
    "Tagged a burger shop; a model believes it also does chicken.",
    address="1 Jalan Percaya, Kuala Lumpur",
    also_serves=("Chicken",),
)
_TAGGED_CHICKEN = Place(
    "b2",
    "Ayam Bertanda",
    # Chicken because the map says so, and nothing is believed about it. The
    # same price as the one above, so the two are level on everything the
    # ranking looks at and the basis is the only thing left to separate them.
    "Chicken",
    _north(0.4),
    _ORIGIN_LNG,
    Money(1600),
    "high",
    True,
    "Tagged chicken, with nothing believed about it either way.",
    address="2 Jalan Percaya, Kuala Lumpur",
)
_BOTH_WAYS = Place(
    "b3",
    "Ayam Dua Kali",
    # Tagged chicken and believed to do chicken: a record that says the same
    # thing twice. The shipped generator drops a belief that restates a tag, but
    # a maps adapter is not the generator, and a place matching on both footings
    # has to come back as the stronger one rather than as two half-matches.
    "Chicken",
    _north(0.6),
    _ORIGIN_LNG,
    Money(1900),
    "high",
    True,
    "Tagged chicken and believed to do chicken, which is the same claim twice.",
    address="3 Jalan Percaya, Kuala Lumpur",
    also_serves=("Chicken",),
)
_NO_CHICKEN = Place(
    "b4",
    "Mee Percaya",
    # Neither tagged nor believed to do chicken, and the cheapest of the four --
    # so a chicken search that quietly widened back out would put this at the
    # top of its own list and be visible immediately.
    "Noodles",
    _north(0.9),
    _ORIGIN_LNG,
    Money(1200),
    "high",
    True,
    "Nothing to do with chicken, on either footing.",
    address="4 Jalan Percaya, Kuala Lumpur",
)

# A world spread across the 5 km radius, for the one question the others cannot
# ask: what a narrowed search does when what it is looking for is mostly outside
# the line. This is the shipped set's own shape, in miniature. Western food from
# Bukit Bintang is three places inside 5 km and sixteen outside it, the nearest
# of those a hundred metres past the cutoff -- so a radius that is merely
# limiting for a common kind of food is, for a rare one, the whole answer.
#
# Five places inside the radius: one western, and four noodle shops a ringgit
# apart. The noodles are there so one search can be plentiful while another is
# thin from the same spot, which is the whole distinction the widening turns on.
#
# All on the origin's meridian, so the distance in each name is the distance
# from the origin, and near enough to round prices that in walk mode the whole
# outing is the meal.
_NEAR_WESTERN = Place(
    "s1",
    "Barat Dekat",
    "Western",
    _north(2.0),
    _ORIGIN_LNG,
    Money(1800),
    "high",
    True,
    "2 km away, and the only western place inside the radius.",
    address="1 Jalan Barat, Kuala Lumpur",
)
_NEAR_NOODLES: tuple[Place, ...] = tuple(
    Place(
        f"s{index + 1}",
        f"Mee Dekat {index}",
        "Noodles",
        _north(index / 5),
        _ORIGIN_LNG,
        Money(900 + index * 100),
        "high",
        True,
        f"{index * 200} m away, one of the four noodle shops in range.",
        address=f"{index} Jalan Mee, Kuala Lumpur",
    )
    for index in range(1, 5)
)
# A hundred metres past the line, which is the case the whole feature is about:
# nothing distinguishes this place from the one at 2 km except a cutoff.
_JUST_PAST_THE_LINE = Place(
    "s6",
    "Barat Jauh Satu",
    "Western",
    _north(5.1),
    _ORIGIN_LNG,
    Money(1900),
    "high",
    True,
    "5.1 km away — a hundred metres outside the radius.",
    address="6 Jalan Barat, Kuala Lumpur",
)
# Nearer than most of what follows and far past any ordinary ceiling, so a
# ceiling still binds out here.
_DEAR_AND_FAR = Place(
    "s7",
    "Barat Mahal",
    "Western",
    _north(5.3),
    _ORIGIN_LNG,
    Money(9000),
    "low",
    True,
    "5.3 km away, and dearer than anything else in this world.",
    address="7 Jalan Barat, Kuala Lumpur",
)
# Nearer and cheaper than most of what follows, and not halal: reaching past the
# radius must not reach past what the user eats.
_NON_HALAL_AND_FAR = Place(
    "s8",
    "Chophouse Jauh",
    "Western",
    _north(5.5),
    _ORIGIN_LNG,
    Money(1500),
    "medium",
    False,
    "5.5 km away, cheap, and not halal.",
    address="8 Jalan Barat, Kuala Lumpur",
)
_FURTHER_WESTERN: tuple[Place, ...] = tuple(
    Place(
        f"s{index}",
        f"Barat Jauh {name}",
        "Western",
        _north(km),
        _ORIGIN_LNG,
        Money(sen),
        "medium",
        True,
        f"{km} km away.",
        address=f"{index} Jalan Barat, Kuala Lumpur",
    )
    for index, name, km, sen in (
        (9, "Dua", 6.5, 2000),
        (10, "Tiga", 7.4, 2100),
        (11, "Empat", 8.2, 2200),
    )
)
# Outside the radius and never offered, because a search for noodles from here
# has four of them in range and does not need a fifth from two towns over.
_FAR_NOODLES = Place(
    "s12",
    "Mee Jauh",
    "Noodles",
    _north(6.0),
    _ORIGIN_LNG,
    Money(900),
    "high",
    True,
    "6 km away, and the cheapest noodles in this world.",
    address="12 Jalan Mee, Kuala Lumpur",
)
# Past twice the radius, and the cheapest western place anywhere in this world.
# It is here to be left out: the reach has to stop somewhere, or a search of the
# whole city arrives wearing the word "nearby".
_BEYOND_THE_REACH = Place(
    "s13",
    "Barat Terlalu Jauh",
    "Western",
    _north(10.5),
    _ORIGIN_LNG,
    Money(800),
    "high",
    True,
    "10.5 km away, past twice the radius, and cheaper than all of them.",
    address="13 Jalan Barat, Kuala Lumpur",
)

_SPREAD: tuple[Place, ...] = (
    _NEAR_WESTERN,
    *_NEAR_NOODLES,
    _JUST_PAST_THE_LINE,
    _DEAR_AND_FAR,
    _NON_HALAL_AND_FAR,
    *_FURTHER_WESTERN,
    _FAR_NOODLES,
    _BEYOND_THE_REACH,
)

# Six places on a ladder out from the origin, for the one question the worlds
# above cannot ask: how far each mode reaches. Every rung sits just inside or
# just outside one of the three radii the travel budgets work out to -- about
# 1.9 km on foot, 8.4 km by transit and 12.5 km by ride -- so a search has to
# hold exactly the rungs its own mode reaches and none of the next one's.
#
# All halal, all one kind, all the same price, so nothing but distance can
# decide what comes back.
_LADDER: tuple[Place, ...] = tuple(
    Place(
        f"g{index}",
        f"Tangga {index}",
        "Malaysian",
        _north(km),
        _ORIGIN_LNG,
        Money(1200),
        "high",
        True,
        note,
        address=f"{index} Jalan Tangga, Kuala Lumpur",
    )
    for index, km, note in (
        (1, 1.8, "1.8 km out: inside a twenty-five-minute walk, and inside everything else."),
        (2, 2.1, "2.1 km out: past the walk, well inside the train."),
        (3, 8.2, "8.2 km out: the last rung a forty-five-minute train ride reaches."),
        (4, 8.7, "8.7 km out: past the train, inside the Grab."),
        (5, 12.3, "12.3 km out: the last rung a forty-five-minute Grab reaches."),
        (6, 13.0, "13.0 km out: past all three of them."),
    )
)

# Three hundred and twenty places packed into the twelve kilometres north of the
# origin, for the other question a wide radius raises: not how far it reaches
# but how much it holds. A ride reaches every one of them, and one search cannot
# ask a router about three hundred and twenty destinations in one URL.
#
# The far ones are the cheap ones, on purpose. The cut is by distance, so the
# cheapest place in this world is exactly the one a search is not going to see,
# and a guard that had quietly become "the cheapest few hundred" would show it.
_THRONG: tuple[Place, ...] = tuple(
    Place(
        f"t{index:03d}",
        f"Kedai {index:03d}",
        "Malaysian",
        _north(index * 0.038),
        _ORIGIN_LNG,
        Money(5000 - index),
        "high",
        True,
        f"{round(index * 38)} m out, and {index} sen cheaper than the first of them.",
        address=f"{index} Jalan Ramai-Ramai, Kuala Lumpur",
    )
    for index in range(1, 321)
)

PLACE_WORLD = PlaceWorld(
    places=(_CHEAP, _MID, _NEAR_NON_HALAL, _PRICEY, _FAR_NON_HALAL, _NOODLES, _SECOND_CAFE),
    crowd=_CROWD,
    multi_kind=(_TWO_KINDS, _ONE_KIND, _OTHER_KIND),
    believed=(_BELIEVED_CHICKEN, _TAGGED_CHICKEN, _BOTH_WAYS, _NO_CHICKEN),
    spread=_SPREAD,
    ladder=_LADDER,
    throng=_THRONG,
    origin={"lat": _ORIGIN_LAT, "lng": _ORIGIN_LNG},
    # George Town, Penang: ~294 km from all seven.
    out_of_range={"lat": 5.4141, "lng": 100.3288},
    # 4.9 km further south than Chophouse Lima, which puts that one place inside
    # the 5 km radius and the other six well outside it. It is not halal, so
    # the halal toggle is the only thing that can empty a search from here.
    lone_non_halal={"lat": _north(-8.9), "lng": _ORIGIN_LNG},
    # 16 km north of the origin, which is out on the edge of the ``spread``
    # world: nothing at all inside 5 km of here, and four western places between
    # 5 and 10 km. The one origin from which "nothing within range" and "here is
    # somewhere to eat" are both true at once.
    spread_outskirts={"lat": _north(16.0), "lng": _ORIGIN_LNG},
    cheap=_CHEAP,
    mid=_MID,
    near_non_halal=_NEAR_NON_HALAL,
    pricey=_PRICEY,
    far_non_halal=_FAR_NON_HALAL,
    noodles=_NOODLES,
    second_cafe=_SECOND_CAFE,
    two_kinds=_TWO_KINDS,
    one_kind=_ONE_KIND,
    other_kind=_OTHER_KIND,
    tagged_chicken=_TAGGED_CHICKEN,
    believed_chicken=_BELIEVED_CHICKEN,
    both_ways=_BOTH_WAYS,
    no_chicken=_NO_CHICKEN,
    near_western=_NEAR_WESTERN,
    just_past_the_line=_JUST_PAST_THE_LINE,
    dear_and_far=_DEAR_AND_FAR,
    non_halal_and_far=_NON_HALAL_AND_FAR,
    far_noodles=_FAR_NOODLES,
    beyond_the_reach=_BEYOND_THE_REACH,
)


class StubRouting:
    """A router with a fixed, per-place answer, given in road metres by id.

    Deliberately not derived from the coordinates: the whole point of routing
    is that the road is longer than the line between its ends, so a stub that
    computed the straight line and called it a road would prove nothing. Any
    place not named is left unrouted, which is how a partly-answered search is
    written.
    """

    def __init__(
        self, metres_by_id: dict[str, float], places: tuple[Place, ...] = PLACE_WORLD.places
    ) -> None:
        self._by_coordinate = {
            (place.lat, place.lng): metres_by_id.get(place.id) for place in places
        }
        # What the planner actually asked for, so a test can assert it was one
        # call covering every candidate rather than one call per place.
        self.calls: list[tuple[tuple[float, float], list[tuple[float, float]]]] = []

    async def road_metres(
        self, origin: tuple[float, float], destinations: Sequence[tuple[float, float]]
    ) -> list[float | None]:
        destinations = [tuple(point) for point in destinations]
        self.calls.append((origin, list(destinations)))
        return [self._by_coordinate.get(point) for point in destinations]


@contextmanager
def serving(
    routing: RoutingAdapter | None = None, places: tuple[Place, ...] = PLACE_WORLD.places
) -> Iterator[PlaceWorld]:
    """Point the adapter registry at the fixed world and a chosen router.

    Defaults to ``NoRouting``: no test in this suite reaches the network, and
    the planner's straight-line fallback is the behaviour most of them are
    about anyway.
    """
    # get_adapters is lru_cache'd, so patching what it builds from only bites
    # once the cache is dropped -- and the shipped set and the configured router
    # only come back for the next test if it is dropped again once the patch is
    # off.
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(registry, "FakeMaps", lambda: FakeMaps(places))
            patch.setattr(registry, "choose_routing", lambda: routing or NoRouting())
            get_adapters.cache_clear()
            yield PLACE_WORLD
    finally:
        # Cleared again with the patches off, so a test that failed mid-way
        # cannot leave the fixed world cached for whatever runs next.
        get_adapters.cache_clear()


@pytest.fixture
def place_world():
    """Serve the fixed world above in place of the 189 shipped KL places.

    A day-plan test that named a real place would be asserting on a data file
    regenerated from OpenStreetMap, and would go red on the next refresh with
    nothing about the planner having changed.
    """
    with serving() as world:
        yield world
