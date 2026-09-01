"""Narrow, provider-agnostic contracts for every external integration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from kira.money import Money


@dataclass(frozen=True, slots=True)
class ReceiptRead:
    merchant: str
    amount: Money
    occurred_on: date
    confidence: int
    note: str


@dataclass(frozen=True, slots=True)
class VoiceRead:
    transcript: str
    merchant: str
    amount: Money
    confidence: int
    note: str


@dataclass(frozen=True, slots=True)
class Place:
    id: str
    name: str
    kind: str
    lat: float
    lng: float
    estimate: Money
    confidence: str
    halal: bool
    note: str
    # Where it actually is, in words. A place named on a screen that quotes a
    # fare to get there has to be findable, and coordinates are not an address.
    # Defaulted so the small worlds the tests build stay readable.
    address: str = ""
    # Every kind of food this place serves, ``kind`` first. OpenStreetMap lets
    # one place carry several cuisines and a fifth of the tagged places in KL
    # do -- Nando's is chicken and portuguese, Jake's Charbroil is a steakhouse
    # and seafood -- so a place that serves two things has to be findable by
    # either. ``kind`` above stays the single word a row is labelled with and
    # the one its estimate was banded from; this is for matching only.
    kinds: tuple[str, ...] = ()
    # What a language model believes this place also serves, beyond the kinds
    # above. OSM tags McDonald's ``burger`` and stops there, and that it also
    # fries chicken is world knowledge no data refresh reaches; the generator
    # asks a model once, at build time, and ships the answer here.
    #
    # Never merged into ``kinds``, and that separation is the whole point of a
    # second field. ``kinds`` is what OpenStreetMap states about a real
    # business, this is what a model guessed about one, and anything that acts
    # on either has to be able to say which it leaned on. Empty is the ordinary
    # case, and it means two different things that only the file can tell
    # apart: nothing was asked, or a model was asked and did not know the shop.
    also_serves: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Never empty, so nothing downstream has to remember a fallback: a
        # place with one cuisine carries a one-word tuple of its own kind, and
        # every caller can read ``kinds`` and be reading the whole truth.
        # ``also_serves`` deliberately gets no such fallback: a model that was
        # never asked believes nothing, and standing the label in for it would
        # invent an opinion out of a tag.
        if not self.kinds:
            object.__setattr__(self, "kinds", (self.kind,))


@runtime_checkable
class OcrAdapter(Protocol):
    def read_receipt(self, image: bytes) -> ReceiptRead: ...


@runtime_checkable
class VoiceAdapter(Protocol):
    def transcribe(self, audio: bytes) -> VoiceRead: ...


@runtime_checkable
class MapsAdapter(Protocol):
    def places_near(self, lat: float, lng: float, radius_km: float) -> list[Place]: ...


@runtime_checkable
class RoutingAdapter(Protocol):
    """Distance along the roads, which is the only distance a fare is charged on.

    One origin, many destinations, one call: the planner asks about every
    candidate it is going to price at once, because a per-place round trip to a
    router is a page that loads at the speed of the slowest one.

    The answer is one entry per destination, in the order they were given, and
    ``None`` wherever this destination could not be routed. An answer that is
    all ``None`` is the router saying nothing at all -- off, unreachable, or
    refusing -- and the caller falls back to the straight line and says so. It
    is a normal state, not an error: implementations do not raise.
    """

    async def road_metres(
        self, origin: tuple[float, float], destinations: Sequence[tuple[float, float]]
    ) -> list[float | None]: ...


@runtime_checkable
class StorageAdapter(Protocol):
    def put(self, key: str, data: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...


@runtime_checkable
class LlmAdapter(Protocol):
    def complete(self, system: str, messages: list[dict[str, str]]) -> str: ...
