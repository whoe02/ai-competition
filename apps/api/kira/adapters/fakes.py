"""Deterministic stand-ins used by the test suite and offline demo mode."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from importlib.resources import files

from kira.adapters.geo import haversine_km
from kira.adapters.protocols import Place, ReceiptRead, VoiceRead
from kira.money import Money

DEMO_DATE = date(2026, 9, 3)


def place_from_record(record: dict) -> Place:
    """One stored record as the planner's Place.

    The single place a line of the data file becomes an object, so the shape
    the file is allowed to have is stated once. Every field added since the
    first version is read with a default: the generator is run by hand and a
    checkout can be carrying a file written before the field existed, which
    must load rather than raise.
    """
    return Place(
        record["id"],
        record["name"],
        record["kind"],
        record["lat"],
        record["lng"],
        # Estimates are stored as whole sen, so they stay integer money the
        # whole way in -- no float ever touches this path.
        Money(record["estimate_sen"]),
        record["confidence"],
        record["halal"],
        record["note"],
        record["address"],
        # Every cuisine OSM states for the place, display kind first. A
        # record from before the field existed carries none, and Place
        # reads that as the one kind it shows.
        tuple(record.get("kinds") or ()),
        # What a model believes the place also serves. Absent from every record
        # in a file generated with no model to ask, which reads as the empty
        # tuple -- nothing is believed about anywhere, which is exactly true.
        tuple(record.get("also_serves") or ()),
    )


def _load_kl_places() -> tuple[Place, ...]:
    """Read the curated KL set that ships inside the package.

    Eight hand-written places only covered the few hundred metres around KLCC,
    so the planner returned nothing for anyone standing anywhere else in the
    city. The set is a data file rather than a literal because it is generated
    (scripts/fetch-kl-places.py) and refreshed; ``importlib.resources`` reads it
    from the installed package, not from a path that only exists in a checkout.
    """
    raw = json.loads(
        (files("kira.adapters") / "data" / "kl_places.json").read_text(encoding="utf-8")
    )
    return tuple(place_from_record(record) for record in raw["places"])


# Places APIs expose a price band, not menu prices. These estimates are curated
# and labelled so the UI cannot imply that a provider returned a real price.
KL_PLACES: tuple[Place, ...] = _load_kl_places()


class FakeOcr:
    """Always read the deterministic demo receipt."""

    def read_receipt(self, image: bytes) -> ReceiptRead:
        return ReceiptRead(
            merchant="Nasi Kandar Pelita",
            amount=Money(1890),
            occurred_on=DEMO_DATE,
            confidence=94,
            note="Line item total matched, tax line ignored.",
        )


class FakeVoice:
    def transcribe(self, audio: bytes) -> VoiceRead:
        return VoiceRead(
            transcript="Grab from the office to KLCC, fourteen ringgit",
            merchant="Grab — office to KLCC",
            amount=Money(1400),
            confidence=71,
            note="Heard 'fourteen ringgit'. Amount is worth a second look.",
        )


class FakeMaps:
    def __init__(self, places: tuple[Place, ...] | None = None) -> None:
        """Serve the shipped set unless a caller hands over its own.

        Tests inject a small fixed world so their scenarios describe behaviour
        rather than whatever the last data refresh happened to put near KLCC.
        """
        self._places = KL_PLACES if places is None else places

    def places_near(self, lat: float, lng: float, radius_km: float) -> list[Place]:
        return [
            place
            for place in self._places
            if haversine_km(lat, lng, place.lat, place.lng) <= radius_km
        ]


class NoRouting:
    """A router that answers nothing, for when there is no router.

    Not a stub that pretends: it is the offline half of a two-state feature.
    Every destination comes back ``None``, the planner falls back to the
    straight line, and each place it returns says ``straight_line`` so the
    screen can too. Tests run on this by default, which is what keeps the suite
    off the network and its fares reproducible.
    """

    async def road_metres(
        self, origin: tuple[float, float], destinations: Sequence[tuple[float, float]]
    ) -> list[float | None]:
        return [None] * len(destinations)


class InMemoryStorage:
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> str:
        self._blobs[key] = data
        return key

    def get(self, key: str) -> bytes:
        return self._blobs[key]


class ScriptedLlm:
    """Replay a fixed script, repeating its last line for longer conversations."""

    def __init__(self, script: list[str]) -> None:
        if not script:
            raise ValueError("ScriptedLlm needs at least one line")
        self._script = list(script)
        self._index = 0

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:
        line = self._script[min(self._index, len(self._script) - 1)]
        self._index += 1
        return line
