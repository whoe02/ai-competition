import json
from datetime import date
from importlib.resources import files

from kira.adapters.fakes import (
    KL_PLACES,
    FakeMaps,
    FakeOcr,
    FakeVoice,
    InMemoryStorage,
    NoRouting,
    ScriptedLlm,
    place_from_record,
)
from kira.adapters.geo import haversine_km
from kira.adapters.osrm import OsrmRouting
from kira.adapters.protocols import (
    LlmAdapter,
    MapsAdapter,
    OcrAdapter,
    Place,
    RoutingAdapter,
    StorageAdapter,
    VoiceAdapter,
)
from kira.adapters.registry import choose_routing, get_adapters, straight_line_reason
from kira.config import get_settings
from kira.money import Money

KLCC_LAT = 3.1577
KLCC_LNG = 101.7120

# The district centres scripts/fetch-kl-places.py allocates the set across, and
# the radius the day-plan endpoint searches by default. Kept here rather than
# imported so the assertion below states the promise in its own terms: the
# generator can change how it meets it, but not whether it does.
DISTRICT_CENTRES: dict[str, tuple[float, float]] = {
    "KLCC": (3.1577, 101.7120),
    "Bukit Bintang": (3.1466, 101.7106),
    "Chow Kit": (3.1650, 101.6980),
    "Bangsar": (3.1285, 101.6709),
    "Mid Valley": (3.1177, 101.6770),
    "Mont Kiara": (3.1725, 101.6500),
    "Sri Hartamas": (3.1650, 101.6520),
    "Cheras": (3.0833, 101.7500),
    "Ampang": (3.1500, 101.7600),
    "Setapak": (3.2000, 101.7200),
    "Wangsa Maju": (3.2050, 101.7350),
    "Sentul": (3.1850, 101.6900),
    "Kepong": (3.2100, 101.6350),
    "Segambut": (3.1900, 101.6650),
    "Old Klang Road": (3.0950, 101.6750),
    "Sri Petaling": (3.0650, 101.6900),
    "Bukit Jalil": (3.0580, 101.6900),
    "Titiwangsa": (3.1750, 101.7050),
}
DEFAULT_RADIUS_KM = 5.0


class TestProtocolConformance:
    def test_every_fake_satisfies_its_protocol(self):
        assert isinstance(FakeOcr(), OcrAdapter)
        assert isinstance(FakeVoice(), VoiceAdapter)
        assert isinstance(FakeMaps(), MapsAdapter)
        assert isinstance(NoRouting(), RoutingAdapter)
        assert isinstance(InMemoryStorage(), StorageAdapter)
        assert isinstance(ScriptedLlm(["hello"]), LlmAdapter)


class TestFakeOcr:
    def test_reads_the_demo_receipt_deterministically(self):
        first = FakeOcr().read_receipt(b"any bytes")
        second = FakeOcr().read_receipt(b"different bytes")
        assert first == second
        assert first.merchant == "Nasi Kandar Pelita"
        assert first.amount == Money(1890)
        assert first.confidence == 94
        assert isinstance(first.occurred_on, date)


class TestFakeVoice:
    def test_returns_the_demo_transcript(self):
        read = FakeVoice().transcribe(b"audio")
        assert read.amount == Money(1400)
        assert read.confidence == 71
        assert "fourteen" in read.transcript.lower()


class TestTheShippedKlSet:
    """The one place that asserts on the shipped data file itself.

    Everything else that plans a day runs against the small fixed world in
    conftest, because the file here is generated from OpenStreetMap and gets
    refreshed. So these are invariants a refresh must preserve, never the
    identity of any one place.
    """

    def test_every_record_parses_into_a_place(self):
        assert all(isinstance(place, Place) for place in KL_PLACES)
        # A truncated or empty file would leave the planner able to find nowhere
        # at all, which is a failure worth being loud rather than silent.
        assert len(KL_PLACES) > 100

    def test_ids_are_unique(self):
        assert len({place.id for place in KL_PLACES}) == len(KL_PLACES)

    def test_every_estimate_is_a_positive_amount_of_whole_sen(self):
        for place in KL_PLACES:
            assert isinstance(place.estimate, Money)
            assert isinstance(place.estimate.sen, int)
            assert place.estimate.sen > 0

    def test_every_place_has_an_address(self):
        # The planner quotes a fare to get to these places, so they have to be
        # findable. Coordinates are not an address, and a blank one on screen
        # is a row the user cannot act on.
        for place in KL_PLACES:
            assert place.address.strip(), place.name

    def test_the_kinds_in_the_file_reach_the_places_the_loader_builds(self):
        # Read straight off the shipped file, because the loader is the thing
        # under test here: a record can state four cuisines and still arrive as
        # one place findable by a single word, which is the bug this whole
        # field exists to fix and the one nothing else here would catch.
        raw = json.loads(
            (files("kira.adapters") / "data" / "kl_places.json").read_text(encoding="utf-8")
        )
        records = {record["id"]: record for record in raw["places"]}
        assert len(records) == len(KL_PLACES)
        for place in KL_PLACES:
            assert list(place.kinds) == records[place.id]["kinds"], place.name
            # The label is the first of them: it is the word the row shows and
            # the one the estimate was banded from, so a list that began with
            # anything else would price a place as one thing and show another.
            assert place.kinds[0] == place.kind, place.name
        several = sum(len(place.kinds) > 1 for place in KL_PLACES)
        assert several > 20, several

    def test_what_a_model_believes_arrives_beside_what_osm_states(self):
        # Read off the shipped file for the same reason the test above is: the
        # loader is what is under test, and a record can carry a whole second
        # list and still arrive as a place that believes nothing.
        raw = json.loads(
            (files("kira.adapters") / "data" / "kl_places.json").read_text(encoding="utf-8")
        )
        records = {record["id"]: record for record in raw["places"]}
        for place in KL_PLACES:
            stored = records[place.id].get("also_serves") or []
            assert list(place.also_serves) == stored, place.name
            # The one rule the whole second field exists for. A belief folded
            # into the tags would be indistinguishable from a tag, and nothing
            # downstream could say which of the two it was acting on.
            assert not set(place.also_serves) & set(place.kinds), place.name

    def test_the_field_is_on_every_record_or_on_none_of_them(self):
        """The generator's promise that it never writes a half-enriched file.

        There is no model to ask on a machine with no API key, and the
        generator's answer to that is to leave the field off entirely rather
        than off some records. The distinction is load-bearing: an empty list
        is a model saying it does not know this shop, and an absent field is
        nobody ever having been asked, and a file mixing the two says neither.
        """
        raw = json.loads(
            (files("kira.adapters") / "data" / "kl_places.json").read_text(encoding="utf-8")
        )
        present = {"also_serves" in record for record in raw["places"]}
        assert len(present) == 1, "some records carry also_serves and some do not"

    def test_confidence_is_always_one_of_the_three_bands(self):
        assert {place.confidence for place in KL_PLACES} <= {"high", "medium", "low"}

    def test_every_place_sits_inside_greater_kl(self):
        # Load-bearing beyond tidiness. "Nothing within range" is a state the
        # screen must still be able to reach and says its own thing about, and a
        # refresh that reached into Penang or Johor would quietly remove it --
        # here, and from the demo, where standing outside KL is how you see it.
        for place in KL_PLACES:
            assert 3.02 <= place.lat <= 3.25, place.name
            assert 101.61 <= place.lng <= 101.76, place.name

    def test_both_halal_and_non_halal_places_are_present(self):
        # A set that were all one or all the other would make the halal filter
        # untestable against real data and useless in the app.
        assert any(place.halal for place in KL_PLACES)
        assert any(not place.halal for place in KL_PLACES)

    def test_every_district_has_a_halal_place_within_the_default_radius(self):
        """The whole reason this file replaced eight hand-written places.

        The Halal chip is on by default, so a district whose only halal-tagged
        places OSM knows are chains the generator's variety caps throttle comes
        back reading "nothing within range" in a suburb full of food. Cheras is
        the thin one: the generator's floor pass leaves it exactly two, and
        without this the next refresh could take both away with the suite green
        and only the screen to say so.
        """
        for district, (lat, lng) in DISTRICT_CENTRES.items():
            nearby = FakeMaps().places_near(lat, lng, DEFAULT_RADIUS_KM)
            halal = [place for place in nearby if place.halal]
            assert halal, f"{district} has no halal place within {DEFAULT_RADIUS_KM} km"


class TestReadingOneStoredRecord:
    """The loader against records the shipped file does not happen to contain.

    Every field added since the first version is optional on the way in,
    because the file is generated by hand and a checkout can be carrying one
    written before the field existed. That has to load, not raise.
    """

    def _a_record(self) -> dict:
        raw = json.loads(
            (files("kira.adapters") / "data" / "kl_places.json").read_text(encoding="utf-8")
        )
        return dict(raw["places"][0])

    def test_a_record_written_before_the_field_existed_still_loads(self):
        record = self._a_record()
        record.pop("also_serves", None)
        place = place_from_record(record)
        assert place.also_serves == ()
        # And nothing else about it was disturbed by the field being missing.
        assert place.kinds == tuple(record["kinds"])
        assert place.estimate == Money(record["estimate_sen"])

    def test_the_beliefs_round_trip_as_written(self):
        record = self._a_record()
        record["also_serves"] = ["Chicken", "Dessert"]
        assert place_from_record(record).also_serves == ("Chicken", "Dessert")


class TestPlaceItself:
    def test_believing_nothing_is_the_default_and_stays_the_default(self):
        place = Place("x1", "Only", "Test", KLCC_LAT, KLCC_LNG, Money(100), "high", True, "")
        # ``kinds`` falls back to the label, so every caller can read it and be
        # reading the whole truth. ``also_serves`` deliberately does not: a
        # model that was never asked believes nothing, and standing the label
        # in for it would invent an opinion out of a tag.
        assert place.kinds == ("Test",)
        assert place.also_serves == ()

    def test_a_belief_never_reaches_the_kinds_a_place_is_found_by(self):
        place = Place(
            "x1",
            "Only",
            "Burgers",
            KLCC_LAT,
            KLCC_LNG,
            Money(100),
            "high",
            True,
            "",
            kinds=("Burgers",),
            also_serves=("Chicken",),
        )
        assert place.kinds == ("Burgers",)
        assert place.also_serves == ("Chicken",)


class TestFakeMaps:
    def test_radius_filters(self):
        near = FakeMaps().places_near(KLCC_LAT, KLCC_LNG, 1.0)
        wider = FakeMaps().places_near(KLCC_LAT, KLCC_LNG, 3.0)
        assert 0 < len(near) < len(wider) < len(KL_PLACES)
        assert all(haversine_km(KLCC_LAT, KLCC_LNG, p.lat, p.lng) <= 1.0 for p in near)

    def test_it_serves_an_injected_set_instead_of_the_shipped_one(self):
        # How a test builds a world of its own rather than asserting on data.
        only = Place("x1", "Only", "Test", KLCC_LAT, KLCC_LNG, Money(100), "high", True, "")
        assert FakeMaps(places=(only,)).places_near(KLCC_LAT, KLCC_LNG, 5.0) == [only]


class TestInMemoryStorage:
    def test_round_trips_bytes(self):
        storage = InMemoryStorage()
        key = storage.put("receipts/1.jpg", b"\xff\xd8\xff")
        assert storage.get(key) == b"\xff\xd8\xff"


class TestScriptedLlm:
    def test_replays_its_script_in_order(self):
        llm = ScriptedLlm(["one", "two"])
        assert llm.complete("s", []) == "one"
        assert llm.complete("s", []) == "two"
        assert llm.complete("s", []) == "two"


class TestNoRouting:
    async def test_it_answers_nothing_for_every_destination(self):
        answers = await NoRouting().road_metres((3.1577, 101.7120), [(3.1, 101.7), (3.2, 101.6)])
        # One entry per destination, all None: the shape the planner lines up
        # against its candidates, saying it has nothing for any of them.
        assert answers == [None, None]

    async def test_no_destinations_is_no_answers(self):
        assert await NoRouting().road_metres((3.1577, 101.7120), []) == []


class TestChoosingARouter:
    """Which router the registry builds, and the stated reason when it is none.

    Kept as a reason rather than a boolean for the same purpose the Butler's
    ``offline_reason`` serves: the degraded path is a state the app can name.
    """

    def test_it_uses_osrm_when_routing_is_on_and_a_url_is_set(self, monkeypatch):
        monkeypatch.setenv("ROUTING_ENABLED", "true")
        monkeypatch.setenv("OSRM_BASE_URL", "https://router.example")
        get_settings.cache_clear()
        try:
            assert straight_line_reason() is None
            assert isinstance(choose_routing(), OsrmRouting)
        finally:
            get_settings.cache_clear()

    def test_routing_switched_off_says_so_and_routes_nothing(self, monkeypatch):
        monkeypatch.setenv("ROUTING_ENABLED", "false")
        get_settings.cache_clear()
        try:
            assert straight_line_reason() == "ROUTING_ENABLED is off"
            assert isinstance(choose_routing(), NoRouting)
        finally:
            get_settings.cache_clear()

    def test_no_url_says_so_rather_than_building_a_client_that_cannot_work(
        self, monkeypatch
    ):
        monkeypatch.setenv("ROUTING_ENABLED", "true")
        monkeypatch.setenv("OSRM_BASE_URL", "   ")
        get_settings.cache_clear()
        try:
            assert straight_line_reason() == "no OSRM base URL is configured"
            assert isinstance(choose_routing(), NoRouting)
        finally:
            get_settings.cache_clear()


class TestRegistry:
    def test_defaults_to_fakes(self):
        adapters = get_adapters()
        assert isinstance(adapters.ocr, FakeOcr)
        assert isinstance(adapters.maps, FakeMaps)

    def test_the_suite_never_gets_a_router_that_can_reach_the_network(self):
        # conftest pins ROUTING_ENABLED off. If that ever stops holding, the
        # day-plan tests start making real requests to a volunteer-run service
        # and their fares start depending on what it said that morning.
        assert isinstance(get_adapters().routing, NoRouting)
