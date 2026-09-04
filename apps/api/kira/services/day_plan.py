"""Turn nearby curated places into money-constrained outings.

Ports kira-prototype.jsx's evaluate() (line 661): cost, travel time, and how
much of today's safe-to-spend each outing would use.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from kira.adapters.fakes import KL_PLACES
from kira.adapters.geo import haversine_km
from kira.adapters.protocols import Place
from kira.adapters.registry import get_adapters
from kira.db.models import SOURCE_PLAN, User
from kira.money import round_half_up
from kira.services.transactions import TransactionView, create_transaction

Mode = Literal["walk", "transit", "ride"]
Band = Literal["ok", "tight", "over"]
# Which distance the fare and the clock below were actually built from. It
# travels with every place because it is per-place: one search can route some
# destinations and fail on others, and a single flag for the list would have to
# lie about half of it.
DistanceBasis = Literal["road", "straight_line"]
# Why a search kept this place. ``tagged`` is OpenStreetMap stating the cuisine
# outright; ``inferred`` is a model, asked once at build time, believing the
# place also serves it; ``judged`` is a model reading this search's own request
# and saying this place answers it, with nothing in the data to point at. All
# three are matches and all three are in the list, but they are not the same
# kind of truth and nothing downstream may present them as one: a tag is a
# record about a real business, the other two are guesses about one.
MatchBasis = Literal["tagged", "inferred", "judged"]
# How well a ranking model thought a place answers the request. Only ever set
# where a model actually judged this search; the deterministic filter leaves it
# None, because a word either matched or it did not and there is no degree in
# that.
MatchStrength = Literal["strong", "weak"]
# Which of the two narrowed this search. ``deterministic`` is the kind filter --
# the offline path, and the whole of the product where the relevance pass is
# off. ``model`` is a model having read the request. Carried on the result so a
# screen can say which it is looking at rather than presenting a fallback as an
# answer.
Ranking = Literal["model", "deterministic"]


# ── What kind of food ─────────────────────────────────────────────────────────


def kind_key(value: str) -> str:
    """The form two kind words are compared in.

    Forgiving in exactly one direction: the user's spelling is allowed to
    differ from the data's by case and by a plural ending, so "noodle" and
    "noodles" both reach ``Noodles`` and "japanese" reaches ``Japanese``.
    Nothing else is forgiven. A prefix rule would have "chi" reaching both
    Chicken and Chinese, and a substring rule would have "tea" reaching
    Steakhouse -- both of which answer a question the user did not ask.
    """
    folded = " ".join(value.split()).casefold()
    return folded[:-1] if folded.endswith("s") else folded


def known_kinds() -> tuple[str, ...]:
    """Every kind of food the curated set actually carries, alphabetically.

    Every kind, not only the ones shown as labels: a place tagged
    ``steak_house;seafood`` is found by a search for seafood, so seafood is a
    word the vocabulary has to offer even if no place in the set is labelled
    with it.

    Derived from the loaded data rather than written down beside it. The set is
    regenerated from OpenStreetMap (scripts/fetch-kl-places.py), and a
    hand-kept list would go on offering a word the data no longer has -- a
    filter that matches nothing, for a reason nobody reading the code can see.

    This is the vocabulary offered to a model and checked against what a
    sentence was read as. It is deliberately not what ``find_places`` filters
    on: that matches against the kinds of the places actually in range, so a
    search stays correct under a maps adapter that is not this one.
    """
    return _KL_KINDS


def resolve_kind(value: str) -> str | None:
    """The curated set's own spelling of a kind word, or None if it has none.

    None is the answer to "hawker" and to "something nice": both are words the
    data has no column for, and treating either as a filter would empty a list
    for a reason the user cannot act on.

    A whole phrase is allowed to carry the word: "fried chicken" reaches
    ``Chicken`` and "middle eastern food" reaches ``Middle Eastern``, because
    people name food the way they eat it rather than the way a column is
    headed. The match is still whole-word against the data's own vocabulary, so
    the rules above hold -- "hawker" and "something nice" carry no kind word and
    still resolve to nothing, and "tea" still does not reach Steakhouse.
    """
    exact = _KL_KINDS_BY_KEY.get(kind_key(value))
    if exact is not None:
        return exact
    # Longest first, so "middle eastern food" is not read as merely "eastern"
    # were a one-word kind ever to overlap a two-word one.
    folded = f" {' '.join(value.split()).casefold()} "
    for key, kind in sorted(_KL_KINDS_BY_KEY.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<!\w){re.escape(key)}s?(?!\w)", folded):
            return kind
    return None


# Built once, off the shipped file. Two spellings of one key would leave the
# alphabetically last standing here, which is arbitrary and harmless: the
# filter itself compares keys, so both spellings match either way, and only the
# word offered to a model would be the other one.
_KL_KINDS: tuple[str, ...] = tuple(sorted({k for place in KL_PLACES for k in place.kinds}))
_KL_KINDS_BY_KEY: dict[str, str] = {kind_key(kind): kind for kind in _KL_KINDS}


@dataclass(frozen=True, slots=True)
class ModeCost:
    base_sen: int
    per_km_sen: int
    min_per_km: float
    wait_min: float


MODES: dict[Mode, ModeCost] = {
    "walk": ModeCost(base_sen=0, per_km_sen=0, min_per_km=13.0, wait_min=0.0),
    "transit": ModeCost(base_sen=210, per_km_sen=0, min_per_km=4.5, wait_min=7.0),
    "ride": ModeCost(base_sen=500, per_km_sen=190, min_per_km=3.2, wait_min=5.0),
}


@dataclass(frozen=True, slots=True)
class EvaluatedPlace:
    id: str
    name: str
    kind: str
    # What this place can be found by, ``kind`` first. Carried through the
    # evaluation because the kind filter and the landscape both run after it.
    kinds: tuple[str, ...]
    # What a model believes it also serves, beyond the tags above. Carried for
    # the same two readers, and kept in its own field for the same reason the
    # place itself keeps it in one: the filter may match on either, and every
    # answer built from that has to be able to say which of the two it was.
    also_serves: tuple[str, ...]
    address: str
    # Where it stands, so a client can point a map at this shop rather than at
    # its name. A quarter of the addresses above are a locality rather than a
    # doorstep, and eight of the names in the demo set belong to two branches
    # each -- a name search reaches the wrong one of those with no warning.
    lat: float
    lng: float
    # The distance every figure below was computed from, whichever kind it is.
    km: float
    # The road figure on its own, or None where the router did not answer for
    # this place. Stated separately from ``km`` so a client can show the real
    # driving distance without having to know which basis produced ``km``.
    road_km: float | None
    distance_basis: DistanceBasis
    travel_sen: int
    minutes: int
    total_sen: int
    # None when there is no room left today: a share of nothing is not a number,
    # and any stand-in would be indistinguishable from a real ratio.
    share: float | None
    band: Band
    confidence: str
    halal: bool
    note: str
    # Why the search kept this place, or None where nothing was asked for and
    # there was nothing to match. None is also what the places a filter turned
    # away carry: they matched nothing, so there is no basis to state.
    #
    # Defaulted because it is not known at evaluation time. A place is priced
    # before any request is considered, and the basis is stamped on afterwards
    # by the one step that knows what was asked.
    match_basis: MatchBasis | None = None
    # How strongly a ranking model thought this place answers the request, or
    # None where no model judged it -- which is every place on the deterministic
    # path. It is the model's only say in the order: strong matches stand ahead
    # of weak ones, and inside each group the totals below still decide.
    match_strength: MatchStrength | None = None
    # Why this place is on the list, in a few words a row can print as they
    # stand: "Tagged chicken", "Also serves chicken", "The model thinks this
    # serves beef". It exists because a row otherwise cannot explain itself --
    # a place labelled Dessert answering a search for chicken is either a good
    # answer or a bug, and the label alone does not say which.
    #
    # Every word of it is composed here, from what the data says and from a
    # single food word the model was allowed to contribute. Never a sentence the
    # model wrote, and never a name: see ``_judged``.
    match_reason: str = ""


@dataclass(frozen=True, slots=True)
class Judgement:
    """One line of a ranking model's answer: a place, and how well it fits.

    ``place_id`` has to be one of the ids the model was handed. Anything else is
    dropped rather than trusted -- see ``_judged``. That is the guard that keeps
    this apart from the failure this project has already produced once, where a
    model with nothing to go on answered with a restaurant that does not exist.
    A model that can only return identifiers can only ever return real places.

    ``serves`` is the model's own two or three words for what this place serves
    that answers the request -- "beef", "grilled fish". It is the only thing it
    contributes to what a row says, and it is not a sentence: the sentence is
    composed here, so nothing the model wrote reaches the screen unframed.
    Empty is ordinary, and means the row falls back to quoting the request.
    """

    place_id: str
    strength: MatchStrength
    serves: str = ""


class PlaceRanker(Protocol):
    """Reads a request and says which of these places answer it.

    The implementation lives above this layer, in ``kira.agent``, and is handed
    in by whoever is calling. A service that reached up for it would invert the
    one dependency this app keeps straight, and -- more to the point here -- a
    search with nothing handed in runs the deterministic filter along the exact
    path it ran before any of this existed.

    None is every way of not having an answer: no model configured, the feature
    off, a timeout, a refusal, a reply that would not parse. It means fall back
    to the kind filter. An empty sequence is a different thing entirely -- a
    model that read the request, looked at the places, and says none of them
    answer it.
    """

    async def __call__(
        self, request: str, places: Sequence[EvaluatedPlace]
    ) -> Sequence[Judgement] | None: ...


@dataclass(frozen=True, slots=True)
class KindPrice:
    """One row of the price landscape: what a kind of food costs from here.

    ``cheapest_total_sen`` is a whole outing -- meal and travel together -- so
    it is the same figure the places themselves carry, and a ceiling can be
    held against it directly.

    ``count`` is how many places a filter for this kind would return, which is
    not a share of the list: see ``price_landscape``. A filter matches a tag or
    a belief, so a row can be counting either, and a row can exist because of a
    belief alone -- it says what a search for that word would come back with,
    which is the only thing it has ever promised.
    """

    kind: str
    count: int
    cheapest_total_sen: int


def price_landscape(evaluated: Iterable[EvaluatedPlace]) -> tuple[KindPrice, ...]:
    """What each kind of food within range costs, cheapest kind first.

    Grouped on ``kind_key`` rather than on the raw word, so that one row
    answers for one filter: whatever a kind filter would match, exactly one row
    here describes.

    A place that carries several kinds is counted under every one of them, and
    that is what keeps the promise in the line above true. The filter matches
    any of a place's kinds, so a steakhouse OSM also calls seafood comes back
    from a search for seafood; counted only under the word on its label, the
    seafood row would be short by one place, or missing entirely -- the
    landscape saying there is no seafood here while the list beneath it shows
    some. The price is that the counts no longer sum to the length of the list.
    They never were meant to: this is one answer per kind, not a division of
    the places between them.

    A believed kind counts exactly as a tagged one does, and for that same
    reason. The filter matches either, so a chicken search reaches the burger
    place a model says fries chicken; counted only under the tags, the chicken
    row would promise fewer places than the search hands back. What kind of
    truth each row rests on is not lost by this -- it is on the rows underneath,
    where a place says outright which of the two matched it.
    """
    # The kind is carried beside the place because a row is labelled with the
    # word its own group was matched on -- the seafood row says "Seafood", not
    # whatever the cheapest place in it happens to be labelled.
    by_key: dict[str, list[tuple[str, EvaluatedPlace]]] = {}
    for place in evaluated:
        # Once per key per place, tags read first. A search returns a place
        # once however many of its words match, so a place standing twice in
        # one group would have the row promising more than the list can show.
        # The shipped generator already drops a belief that restates a tag, but
        # this is the count the row is judged on and it holds for any adapter.
        counted: set[str] = set()
        for kind in (*place.kinds, *place.also_serves):
            key = kind_key(kind)
            if key in counted:
                continue
            counted.add(key)
            by_key.setdefault(key, []).append((kind, place))
    rows = []
    for group in by_key.values():
        kind, cheapest = min(group, key=lambda pair: pair[1].total_sen)
        rows.append(KindPrice(kind, len(group), cheapest.total_sen))
    return tuple(sorted(rows, key=lambda row: (row.cheapest_total_sen, row.kind)))


def evaluate_place(
    place: Place,
    origin_lat: float,
    origin_lng: float,
    mode: Mode,
    room_sen: int,
    road_metres: float | None = None,
) -> EvaluatedPlace:
    """room_sen is always today's real safe-to-spend -- it is NOT the same as
    the caller's display cap_sen, which only filters what is shown.

    ``road_metres`` is what the routing adapter said about this place, or None
    if it said nothing. A car is charged for the road it drives, so where there
    is a road figure it is the one the fare and the travel time are built on;
    the great circle only stands in when there is not, and the basis returned
    with the place says which of the two happened.
    """
    # Kept regardless: it is the fallback, and computing it is free next to the
    # call that may or may not have replaced it.
    straight_line_km = haversine_km(origin_lat, origin_lng, place.lat, place.lng)
    road_km = None if road_metres is None else road_metres / 1000
    basis: DistanceBasis = "straight_line" if road_km is None else "road"
    km = straight_line_km if road_km is None else road_km
    cost = MODES[mode]
    # Distance is a measurement, so a float is right for it. The fare it implies
    # is money, so it is not: the per-km charge is accumulated in whole sen and
    # divided down with the app's own half-up rounding. Handing it to a float and
    # calling round() would round halves to even, which money.py forbids outright
    # -- at 150 m of a ride that is 528 sen where the fare is 529.
    metres = round(km * 1000)
    travel_sen = (
        0 if km < 0.12 else cost.base_sen + round_half_up(cost.per_km_sen * metres, 1000)
    )
    minutes = round(cost.wait_min + km * cost.min_per_km) + 6
    total_sen = place.estimate.sen + travel_sen
    share = total_sen / room_sen if room_sen > 0 else None
    # With nothing left today, every outing is over what is left of it.
    band: Band = (
        "over" if share is None else "ok" if share <= 0.6 else "tight" if share <= 1.0 else "over"
    )
    return EvaluatedPlace(
        id=place.id,
        name=place.name,
        kind=place.kind,
        kinds=place.kinds,
        also_serves=place.also_serves,
        address=place.address,
        lat=place.lat,
        lng=place.lng,
        km=km,
        road_km=road_km,
        distance_basis=basis,
        travel_sen=travel_sen,
        minutes=minutes,
        total_sen=total_sen,
        share=share,
        band=band,
        confidence=place.confidence,
        halal=place.halal,
        note=place.note,
    )


@dataclass(frozen=True, slots=True)
class PlacesFound:
    """What the maps adapter had, and what survived each filter in turn.

    An empty ``places`` has four unrelated causes and the caller must not have
    to guess between them, so each filter states what it left behind:

    * ``nearby_count`` is what the radius held. Nil means distance is the cause,
      and no ceiling and no toggle will close it.
    * ``matching_count`` is what was still standing after the halal filter, and
      before the kind filter and the ceiling ran. Nil against a non-nil
      ``nearby_count`` means the halal toggle is the cause -- raising the
      ceiling would do nothing, and telling the user to raise it sends them at
      a slider that cannot help.
    * ``kind_count`` is what was still standing after the food-type filter --
      or after the relevance pass, where ``ranking`` says a model ran instead --
      and equals ``matching_count`` when nothing was asked for. Nil against a
      non-nil ``matching_count`` means there is nothing of that kind around
      here at all -- again not a ceiling, and not a distance either, since
      other food is in range. It counts places, so a place that carries the
      asked-for kind alongside two others is one of them, and it is the same
      figure as the ``landscape`` row for that kind. Tagged and believed
      matches are counted alike, because both are in the list: which of the two
      any one place is stands on the place itself, in ``match_basis``.
    * anything left after that, with ``places`` still empty, is the ceiling:
      the one cause the user can actually drag away.

    The counts nest -- ``nearby_count >= matching_count >= kind_count >=
    len(places)`` -- so the first of them that is nil is the cause.

    ``landscape`` is the whole price picture behind ``places``: every kind of
    food in range, how many of each, and the cheapest outing among them. See
    ``find_places`` for what it deliberately does and does not narrow by.

    ``nearest_over_cap`` is the answer to the one empty list the user can do
    nothing with: a ceiling of RM10 where the cheapest thing around is RM11.50.
    "Nothing under RM10" is true and useless -- the person still has to eat, and
    the search already knows what the nearest thing costs. So the cheapest few
    of what the ceiling turned away come back here, and only here: never folded
    into ``places``, because a widened ceiling nobody asked for is the same lie
    as a dropped "halal". Every other filter still holds -- these are halal if
    halal was asked for, and the kind that was asked for -- so the only thing
    relaxed is the one figure the user can see and drag.

    It is populated on a completely empty ``places`` and never on a thin one.
    Empty-only is a rule a person can hold in their head, and it keeps "the
    ceiling is being respected" something they can go on trusting.

    ``near_misses`` is the other half of a kind filter: a few of the places it
    turned away, with the kind they really are and the price they really cost.
    It exists because the tags are one word per place and a menu is not. OSM
    calls McDonald's ``burger`` and stops there, so a search for chicken finds
    KFC and walks the user past a McDonald's that fries chicken all day. Some of
    that gap is closed before this list is built: a place a model was asked
    about at build time and believed serves the thing is a match now, and turns
    up in ``places`` marked ``inferred`` rather than down here. What is left is
    the rest of the gap -- the shops nobody was asked about, and the ones the
    model did not recognise.
    So these rows are handed over for it to reason across: real places, really
    nearby, at prices this search measured. What none of them is, is a match.
    Each one keeps its own kind, and anything said about what it serves beyond
    that word belongs to whoever said it. Present only where a kind was asked
    for: with no filter, nothing was turned away.

    Ordered by distance rather than by price, which nothing else here is: see
    ``_near_misses``. It follows that one of these can cost more than the
    ``landscape`` row for its own kind, and that is the two saying different
    things rather than disagreeing -- the row is the cheapest of that kind
    anywhere in range, and this is the closest one.

    ``nearest_beyond_radius`` is the same idea one filter along, for the line
    that throws away more than any other. A search for Western food from Bukit
    Bintang finds three places inside 5 km; nineteen of them are in the set, and
    the fourth is a hundred metres past the cutoff. For a common kind a radius
    that tight is merely thin, and for a rare one it is the whole answer. So
    where a narrowed search comes back with few places, the nearest matching
    ones from just outside the radius come back here -- in their own field,
    never in ``places``, for the same reason ``nearest_over_cap`` is: these are
    further away than the user asked for, and folding them in would be the same
    lie as a dropped "halal".
    Everything else still holds over them, the ceiling included, so distance is
    the only thing relaxed. Their distances, fares and travel times are the real
    ones for the longer journey -- measured by the same router and priced by the
    same fare table as the list above -- because the whole point of the group is
    that the user can see what the extra kilometres cost.

    ``loose_matches`` is the third group set apart, and the line relaxed for it
    is relevance itself. A ranking model says of each place it keeps whether it
    is plainly the thing that was asked for or only a fair second best, and the
    second sort is not an answer to the question: a dessert cafe and a bakery
    came back from a search for Western food, drawn exactly like the burger
    place above them. So a weak match never stands in ``places``. It comes back
    here, where a client has to head it as loosely related before it can draw a
    single row -- and where a badge that means "this is the one" can never land
    on it.

    A weak match is also allowed to be dropped outright, which none of the other
    groups is. See ``find_places``: past a handful of real answers the loose ones
    stop being alternatives and start being padding, and a list padded out to
    look longer is the thing the whole group exists to stop.

    ``ranking`` says which of the two narrowed this search: a model that read
    the request, or the deterministic kind filter. It is stated because the two
    are not equally good and the difference is invisible in the list itself. A
    fallback presented as an answer is the failure this whole field exists to
    prevent -- a screen that cannot say "I could not reach my model, so this is
    the word filter" will say nothing, and a search that quietly went back to
    matching two dozen cuisine tags looks exactly like one that did not.

    Every count above and the landscape are about the radius and nothing else.
    A place in ``nearest_beyond_radius`` is in none of them: it was never inside
    ``nearby_count``, so it cannot reach ``matching_count`` or ``kind_count``,
    and the landscape goes on describing what is actually in range. The counts
    still nest, and the first of them that is nil is still the cause.

    ``kind_count`` does count the loose matches, and that is the one place where
    a count is deliberately larger than the list beneath it. Those places were in
    range and the model did keep them, so leaving them out would have the count
    disagreeing with what the model actually said. The nesting above still holds:
    ``kind_count >= len(places)``, with the difference being the loose group and
    whatever was trimmed off the end of it.
    """

    places: tuple[EvaluatedPlace, ...]
    nearby_count: int
    matching_count: int
    kind_count: int
    landscape: tuple[KindPrice, ...]
    nearest_over_cap: tuple[EvaluatedPlace, ...] = ()
    nearest_beyond_radius: tuple[EvaluatedPlace, ...] = ()
    loose_matches: tuple[EvaluatedPlace, ...] = ()
    near_misses: tuple[EvaluatedPlace, ...] = ()
    ranking: Ranking = "deterministic"


# ── The order the matches are read in ─────────────────────────────────────────

# A weak match stands behind a strong one, and behind everything the
# deterministic filter produced -- which carries no strength at all, because a
# word either matched or it did not. Reading None as strong is what keeps the
# order on that path byte-for-byte what it was before any of this existed.
_STRENGTH_ORDER: dict[MatchStrength | None, int] = {None: 0, "strong": 0, "weak": 1}

# Where two outings cost the same, the place the map actually records goes in
# front of the one somebody guessed at. A model's judgement about this search
# sits with the beliefs, for the same reason: both are guesses, and neither is a
# record. This reproduces the tie-break that was here before, which read
# ``match_basis == "inferred"`` and had only the two values to tell apart.
_BASIS_ORDER: dict[MatchBasis | None, int] = {
    None: 0,
    "tagged": 0,
    "inferred": 1,
    "judged": 1,
}


def _order_key(place: EvaluatedPlace) -> tuple[int, int, int]:
    """Strength, then price, then how well founded the match is.

    Price is the middle term and never the outer one, and that is the whole
    shape of what a ranking model is allowed to do here. It may say a place
    answers the request strongly or weakly; it may not make a dearer outing look
    cheaper than it is. Inside a group of equally relevant places the money is
    still what orders them, and every figure in the group is one this search
    measured.

    On the deterministic path the first term is constant and the third is the
    tie-break that was always here, so this sorts exactly as it used to.
    """
    return (
        _STRENGTH_ORDER[place.match_strength],
        place.total_sen,
        _BASIS_ORDER[place.match_basis],
    )


# How many of the turned-away places are offered back when the ceiling admitted
# nothing at all. One would read as the answer rather than as the cheapest thing
# that did not fit; a full dozen would read as the ceiling having been widened.
NEAREST_OVER_CAP = 3


def _nearest_over_cap(turned_away: Sequence[EvaluatedPlace]) -> tuple[EvaluatedPlace, ...]:
    """The cheapest few of what the ceiling excluded, each banded ``over``.

    The band is set rather than left as evaluated, and that is the honest
    reading rather than a cosmetic one. ``band`` is what every client already
    renders as "this does not fit what you asked for", and not fitting is the
    entire reason these places are here: each one is above the ceiling this
    search was run under. Left alone, a place under a hand-dragged ceiling but
    well inside today's room would come back ``ok`` and could be drawn exactly
    like a place that fitted -- which is the one thing this group must never
    look like.

    ``share`` is untouched, because that is a real ratio against a real room and
    nothing here has changed it.
    """
    # Ranked exactly as the list above the ceiling is, tie-break included. These
    # are the same places under the same question, and two orders for one answer
    # would put a belief in front of a tag here and behind it a slider's width
    # away.
    nearest = sorted(turned_away, key=_order_key)[:NEAREST_OVER_CAP]
    return tuple(replace(place, band="over") for place in nearest)


# How many of the places a kind filter turned away are handed back beside the
# ones it kept. Modest on purpose: a dozen matches and a whole price landscape
# already go over with them, and a long second list would stop reading as an
# aside and start reading as the answer.
NEAR_MISSES = 4


def _near_misses(turned_away: Sequence[EvaluatedPlace]) -> tuple[EvaluatedPlace, ...]:
    """The nearest place of each kind the filter turned away, nearest first.

    One per kind rather than four places outright, because breadth is the whole
    value of this list. Four Indian restaurants a ringgit apart are four goes at
    the same guess; a burger place, a cafe, a mamak and a noodle shop are four
    different ones, and only one of them has to be somewhere the reader of this
    list actually knows the menu of.

    Nearest rather than cheapest, which is the one place in this module that
    does not rank on money, and it earns it twice over. A near miss is only
    worth mentioning if it beats the matches at something, and what it can beat
    them at is being right here: from Bukit Bintang the tagged chicken is a
    kilometre off and there is a McDonald's forty metres away. And the shops
    anyone can be confident about the menu of are the chains, which is exactly
    what "the nearest burger place to an arbitrary corner of KL" tends to be --
    there are eight McDonald's in the shipped set and one Alfresco Café, and
    cheapest-first picked the Alfresco every time on a tie.

    Still held to the ceiling by the caller: somewhere the user cannot afford
    is not an alternative to anything.
    """
    # Ties broken all the way down to the id, so the same search cannot return
    # two different shops on two runs because a data refresh reordered a file.
    nearest: dict[str, EvaluatedPlace] = {}
    for place in sorted(turned_away, key=lambda p: (p.km, p.total_sen, p.id)):
        nearest.setdefault(kind_key(place.kind), place)
    return tuple(nearest.values())[:NEAR_MISSES]


# The three things a row can say about why it is here, and the whole vocabulary
# of it. Two are read straight off the data. The third is the only one a model
# has any hand in, and even there its contribution is the food word alone.
def _tagged_reason(kind: str) -> str:
    return f"Tagged {kind.lower()}"


def _believed_reason(kind: str) -> str:
    return f"Also serves {kind.lower()}"


def _judged_reason(serves: str, request: str) -> str:
    """Said as a belief, out loud, every time.

    "The model thinks" is not hedging for its own sake. This row is on the list
    because something with no menu in front of it read a name and a category and
    formed an opinion; drawn like a tagged row it would arrive wearing the map's
    authority, and the user would have no way to tell the two apart.
    """
    if serves:
        return f"The model thinks this serves {serves}"
    return f"The model thinks this answers “{' '.join(request.split())}”"


def _first_matching(words: Iterable[str], wanted: str) -> str | None:
    """The first of ``words`` that is the kind asked for, in its own spelling."""
    return next((word for word in words if kind_key(word) == wanted), None)


def _matching(evaluated: Sequence[EvaluatedPlace], wanted: str) -> list[EvaluatedPlace]:
    """Every place a search for ``wanted`` reaches, each stamped with why.

    Two different claims come back in one list, and that is the point of the
    stamp. OpenStreetMap tagging a place chicken is a record about a real
    business; a model believing McDonald's also fries chicken is a guess about
    one -- and the guess is what makes the list wide enough to be useful, since
    OSM tags McDonald's burger and stops there. Both are matches. What must not
    happen is the two arriving indistinguishable, so the reason is written onto
    the place here, at the one step that knows what was asked for.

    A tag beats a belief wherever both would answer. A place OSM already calls
    chicken is not made less certain by a model agreeing with it.

    The words are the place's own rather than the user's, so a row says what the
    data records about it: someone searching "noodle" reads "Tagged noodles".
    """
    matched: list[EvaluatedPlace] = []
    for place in evaluated:
        tagged = _first_matching(place.kinds, wanted)
        if tagged is not None:
            matched.append(
                replace(place, match_basis="tagged", match_reason=_tagged_reason(tagged))
            )
            continue
        believed = _first_matching(place.also_serves, wanted)
        if believed is not None:
            matched.append(
                replace(place, match_basis="inferred", match_reason=_believed_reason(believed))
            )
    return matched


def _named_in(request: str, words: Iterable[str]) -> str | None:
    """The first of ``words`` the request actually says, or None if it says none.

    The same whole-word rule ``resolve_kind`` uses, and forgiving in the same
    one direction -- case and a plural ending, nothing else. It runs against the
    place's own words rather than against the shipped vocabulary, because a
    place in range can carry a kind that vocabulary has never heard of, and
    because a search has to stay correct under a maps adapter that is not the
    curated one.
    """
    folded = f" {' '.join(request.split()).casefold()} "
    for word in words:
        if re.search(rf"(?<!\w){re.escape(kind_key(word))}s?(?!\w)", folded):
            return word
    return None


def _answers_the_request(serves: str, request: str) -> bool:
    """Whether the model's own few words are about the thing that was asked for.

    This is the check that arrived with a complaint. A search for Western food
    came back with a dessert cafe and a bakery, and the reason under each of
    them read "The model thinks this serves Bakery" -- a true enough sentence
    about the shop and no answer whatever to the question. A row that cannot say
    why it answers *this* request explains nothing, and drawn beside a row that
    can, it makes the whole list look guessed at.

    So the model's words have to touch the request. Whole-word and forgiving of
    a plural, the same rule ``_named_in`` applies to a kind word, and word by
    word rather than as a phrase: "beef noodles" answers "somewhere for beef",
    where "Bakery" answers "western food" not at all.

    It is a coarse rule and it is coarse in the safe direction. "laksa" under
    "something warm" says nothing the request says, so it comes back weak --
    which is a real answer sent to the loose group. The alternative is a row
    claiming a connection this app cannot show, beside figures it measured, and
    of the two mistakes that is the one that costs the list its credibility.
    """
    return _named_in(request, serves.split()) is not None


def _judged(
    evaluated: Sequence[EvaluatedPlace],
    judgements: Sequence[Judgement],
    request: str,
) -> list[EvaluatedPlace]:
    """The places a ranking model kept, each stamped with why it is here.

    Only ids it was actually given survive, and that is the whole guardrail
    rather than a tidiness check. A model that returns an identifier can only
    return a place that exists, was measured, and has a price behind it; the
    moment one it composed were let through, the list would carry a shop nobody
    can go to at a price nobody measured -- which is exactly what happened here
    once already, under a name that read perfectly plausibly.

    Nothing about a place changes but why it is on the list. The total, the
    fare, the distance, the share and the band all come through untouched: they
    were computed before this ran and the model has no way to reach them.

    The reason prefers what can be proved. Where the request actually says a
    word the map records for this place, the row says so and the model's opinion
    is not needed; where it says a word the build-time belief carries, the row
    says that instead. Only where neither holds -- a Dessert place answering a
    search for beef -- does the row fall back to the model's own account of
    itself, and there it says out loud that that is what it is.

    And a row that cannot say anything about the request is weak, whatever the
    model called it. The first two branches are already provably about the
    request: the request itself said the word. The third is the model's word
    alone, and where that word is not about what was asked -- "Bakery", under a
    search for Western food -- the claim is dropped and the strength comes down
    with it. A verdict of "strong" resting on a reason that explains nothing is
    the pairing that made the list look untrustworthy in the first place.
    """
    by_id = {place.id: place for place in evaluated}
    kept: list[EvaluatedPlace] = []
    seen: set[str] = set()
    for judgement in judgements:
        place = by_id.get(judgement.place_id)
        # An unknown id is dropped in silence, and a repeat of one already kept
        # with it: a place standing twice would have the counts promising more
        # than the list can show, exactly as a doubled landscape row would.
        if place is None or place.id in seen:
            continue
        seen.add(place.id)
        basis: MatchBasis
        strength = judgement.strength
        tagged = _named_in(request, place.kinds)
        if tagged is not None:
            basis, reason = "tagged", _tagged_reason(tagged)
        elif (believed := _named_in(request, place.also_serves)) is not None:
            basis, reason = "inferred", _believed_reason(believed)
        elif _answers_the_request(judgement.serves, request):
            basis, reason = "judged", _judged_reason(judgement.serves, request)
        elif judgement.serves.strip():
            # The words are dropped rather than printed under a hedge. "The
            # model thinks this serves Bakery" is not made honest by the word
            # "thinks" -- it is off the subject, and a row saying nothing about
            # the request at least says that much accurately by quoting it.
            #
            # Only where it said something, though. Saying the wrong thing is a
            # reason to trust the verdict less; saying nothing is not. A model
            # that names no food has made no claim to be off the subject about,
            # and demoting it would quietly turn every terse answer weak --
            # which is how a strong match ends up in the loosely-related group
            # for the crime of being brief.
            basis, reason, strength = "judged", _judged_reason("", request), "weak"
        else:
            basis, reason = "judged", _judged_reason("", request)
        kept.append(
            replace(
                place,
                match_basis=basis,
                match_strength=strength,
                match_reason=reason,
            )
        )
    return kept


# ── The loose matches, and how few of them survive ────────────────────────────

# How many weak matches are ever offered.
#
# The complaint was a list of ten with a padded tail, so the answer had to be a
# number and not a hope. Three is enough to be a second shelf worth glancing at
# and few enough that nobody mistakes it for the answer -- the same size as the
# group offered from above the ceiling, and for the same reason.
LOOSE_MATCHES = 3


def _loose(under_cap: Sequence[EvaluatedPlace], answers: int) -> tuple[EvaluatedPlace, ...]:
    """The few weak matches worth offering, or none where the answer is enough.

    This is the deliberate answer to "should the model be returning fewer weak
    matches", and it is settled here rather than by asking the model nicely. A
    prompt is a request; this is arithmetic. Three attempts at steering this
    model's behaviour by writing more prompt are already on the record in this
    project, and the third one ended with an invented restaurant.

    Dropped altogether once the strong matches outnumber ``FEW_NEARBY``. Past a
    handful of places that plainly are what was asked for, a loosely-related one
    is not an alternative to them -- it is length. That is the same trigger the
    group from beyond the radius uses and the same instinct the ceiling group
    follows: a second list is worth showing exactly when the first one is thin.

    Capped rather than sorted afresh: ``under_cap`` arrives in ``_order_key``
    order, so the cheapest weak matches are already at the front of it.
    """
    if answers > FEW_NEARBY:
        return ()
    return tuple(place for place in under_cap if place.match_strength == "weak")[:LOOSE_MATCHES]


# ── Reaching past the radius ──────────────────────────────────────────────────

# How thin a narrowed list has to be before the search looks past the radius.
#
# Three, because three is the number the complaint arrived with: a search for
# Western food from Bukit Bintang holds exactly three places inside 5 km, and
# sixteen more of the same kind are outside it. Firing only on an empty list
# would leave that search exactly as it was -- three is not nought, and the user
# is no better off for the rule that says so. Firing always would be worse the
# other way: a dozen good places nearby, with a tail of distant ones underneath
# that nobody asked about. Three is where a list stops being a choice and starts
# being whatever happened to fall inside the line.
FEW_NEARBY = 3

# How much further than the radius the search will reach, as a multiple of it.
#
# A multiple rather than a distance, because the radius is the question: a 1 km
# search widened to a fixed 6 km would be answering a different one, where
# doubling keeps the wider search recognisably about the same part of town. And
# bounded at all because the alternative is "the nearest match anywhere", which
# is a search of the whole city handed over as though it were nearby.
BEYOND_RADIUS_REACH = 2.0

# How many places from beyond the radius are ever measured. It bounds one call
# to the router and, where a model is narrowing, one prompt: without it a thin
# search from the middle of town would price and rank most of the city in order
# to hand back four rows.
BEYOND_RADIUS_CANDIDATES = 24

# How many come back. Four rather than the ceiling group's three: the trigger
# above is three, so a group that could only ever offer three more would answer
# "why so few" with as few again. Still short enough that nobody could read it
# as the radius having been widened on their behalf.
NEAREST_BEYOND_RADIUS = 4


def _carries(place: Place, wanted: str) -> bool:
    """Whether a search for ``wanted`` would keep this place, before it is priced.

    The same two fields ``_matching`` reads, over a place nothing has measured
    yet. It exists so the widened search can drop what the filter is going to
    drop before paying a router to measure it. Nothing is described here: the
    basis and the reason are still written on by ``_matching`` afterwards, so
    there is exactly one place that says why a place is on a list.
    """
    return (
        _first_matching(place.kinds, wanted) is not None
        or _first_matching(place.also_serves, wanted) is not None
    )


async def _nearest_beyond_radius(
    *,
    lat: float,
    lng: float,
    mode: Mode,
    halal_only: bool,
    cap_sen: int,
    room_sen: int,
    radius_km: float,
    inside: set[str],
    wanted: str | None,
    request: str,
    rank: PlaceRanker | None,
) -> tuple[EvaluatedPlace, ...]:
    """The nearest few matching places from just outside the radius.

    ``inside`` is every id the radius held, before any filter ran. Excluding by
    id rather than by distance is what makes this group disjoint from all three
    of the others by construction: a place the halal filter or the ceiling
    turned away cannot come back here wearing "further than you asked", which it
    is not.

    ``wanted`` is the kind filter where the deterministic filter narrowed the
    list this group stands beside, and None where a model did -- exactly as in
    ``find_places``, where a model that answered leaves ``kind`` narrowing
    nothing. Which of the two it was decides how this group is narrowed too,
    because one group narrowed by a word beside another narrowed by a model
    would be two answers where ``ranking`` can only describe one.

    A model that cannot answer for these places hands back nothing rather than
    falling through to the word filter. The near list would still be the
    model's, and a group narrowed by something else beneath it would be a
    difference the response has no field to state. An empty group says nothing
    and is the honest answer to having nothing to say.

    Every figure on these places is measured for the longer journey, by the same
    router and the same fare table as the list above. That is the whole reason
    they can be offered at all: the user can see the extra kilometres and what
    they cost, and decide.
    """
    adapters = get_adapters()

    def kept(place: Place) -> bool:
        if place.id in inside:
            return False
        if halal_only and not place.halal:
            return False
        # The kind filter is applied here, before anything is measured, rather
        # than after: routing a place the filter is certain to drop is a call to
        # a public service bought for nothing. Where a model is narrowing there
        # is no such certainty and nothing to apply, so everything nearby goes
        # through to be priced and asked about.
        return wanted is None or _carries(place, wanted)

    beyond = [
        place
        for place in adapters.maps.places_near(lat, lng, radius_km * BEYOND_RADIUS_REACH)
        if kept(place)
    ]
    if not beyond:
        # Nothing out there worth measuring, so nothing is measured. This is the
        # line that keeps a search which cannot be helped -- a corner of town
        # with nothing around it for miles -- from costing a router call and a
        # model call to find that out.
        return ()
    # Nearest first, on the straight line, because that is the only distance
    # there is before the router has been asked. The id breaks a tie so that two
    # runs of one search cannot measure two different shortlists.
    beyond.sort(key=lambda place: (haversine_km(lat, lng, place.lat, place.lng), place.id))
    beyond = beyond[:BEYOND_RADIUS_CANDIDATES]

    routed = await adapters.routing.road_metres(
        (lat, lng), [(place.lat, place.lng) for place in beyond]
    )
    if len(routed) != len(beyond):
        # Same reasoning as the search inside the radius: an adapter that
        # answered a different number of destinations cannot be lined up with
        # them, and pairing them off anyway would put one place's distance on
        # another place's fare.
        routed = [None] * len(beyond)
    evaluated = [
        evaluate_place(place, lat, lng, mode, room_sen, road_metres=metres)
        for place, metres in zip(beyond, routed, strict=True)
    ]

    if wanted is not None:
        matched = _matching(evaluated, wanted)
    else:
        judgements = None if rank is None else await rank(request, evaluated)
        if judgements is None:
            return ()
        matched = _judged(evaluated, judgements, request)

    # Nearest first, and the one group in this module ordered on distance for a
    # reason of its own: distance is the thing that was relaxed to get here, so
    # it is the thing the reader is owed in order. A cheapest-first order would
    # put a place nine kilometres out ahead of one a hundred metres past the
    # line, which is the wrong end of the only question this group answers.
    #
    # Held to the ceiling all the way: reaching past the radius is one thing,
    # and reaching past what the user can pay while doing it would be relaxing
    # two filters for the price of asking about one.
    #
    # And held to a strong verdict, which is the same rule read once more. A
    # place that is only loosely what was asked for AND further away than was
    # asked for has nothing left to recommend it: the extra kilometres were
    # spent to find a better answer, not a vaguer one.
    affordable = [
        place
        for place in matched
        if place.total_sen <= cap_sen and place.match_strength != "weak"
    ]
    nearest = sorted(affordable, key=lambda place: (place.km, place.total_sen, place.id))
    # The band is left exactly as it was evaluated, which is where this parts
    # company with ``_nearest_over_cap``. There the band is forced to "over"
    # because every place in that group fails the ceiling and the band is what a
    # client renders as "this does not fit". Here the ceiling was honoured, so
    # these do fit; stamping "over" on them would be stating something false
    # about the money in order to say something true about the distance. The
    # distance says itself, on ``km``, on every row.
    return tuple(nearest[:NEAREST_BEYOND_RADIUS])


async def find_places(
    *,
    lat: float,
    lng: float,
    mode: Mode,
    halal_only: bool,
    cap_sen: int,
    room_sen: int,
    radius_km: float = 5.0,
    kind: str | None = None,
    request: str = "",
    rank: PlaceRanker | None = None,
) -> PlacesFound:
    """cap_sen filters what is shown; room_sen (today's safe-to-spend) drives
    share/band and must never be swapped with cap_sen.

    ``kind`` narrows to one sort of food, matched against the kinds of the
    places actually in range -- not against the shipped vocabulary, so a search
    stays correct under a maps adapter that is not the curated one. It matches
    any kind a place carries, not just the one it is labelled with, and it also
    matches what a model believes the place serves beyond its tags, so a search
    for chicken reaches the McDonald's that OSM only ever calls a burger shop.
    Every place that comes back says which of the two kept it, in
    ``match_basis`` -- a widened list is only worth having if the user can still
    tell a record from a guess. A word nothing matches returns nothing. It never
    widens back out to the whole list: an unmatched filter answered with
    everything is the same lie as a dropped "halal", and ``kind_count`` is there
    to say which filter it was. What it turned away is not thrown away either --
    a few of those places come back in ``near_misses``, in their own field and
    under their own kinds, for a caller that knows something about a menu that
    neither the tags nor the beliefs do.

    ``radius_km`` is a hard line for everything above and a soft one for exactly
    one field. Where a narrowed search comes back with ``FEW_NEARBY`` places or
    fewer, the nearest matching places from just outside the radius come back in
    ``nearest_beyond_radius`` -- separately, so no reading of the answer can have
    them nearby. Nothing widens for an unnarrowed browse: everything in range is
    already the answer to "what is around me", and topping that up with distant
    places would be answering a question nobody asked. See
    ``_nearest_beyond_radius``.

    ``request`` is the user's own sentence, and ``rank`` is something that can
    read it against the places in range. Given both, the model's verdict is what
    narrows the search and ``kind`` narrows nothing: the two are not run one
    over the other, because the word filter is the thing the model is there to
    replace. Two dozen cuisine tags is the whole of what ``kind`` can match, and
    "satay", "nasi lemak" and "beef" are none of them.

    That verdict comes in two strengths, and only the strong one is an answer.
    ``places`` holds the places the model said plainly are what was asked for; a
    weak match goes to ``loose_matches``, capped and often dropped outright --
    see ``_loose``. So ``places`` can be short beside a ``kind_count`` that is
    not, and that is the two saying different things rather than disagreeing:
    the count is what the model kept, the list is what it stood behind.

    Given neither -- which is the default, and the whole product while the
    feature is off -- not one line below behaves differently from the day before
    this existed. There is no model to reach, so there is no timeout to wait
    through and no call to pay for. The same holds when ``rank`` answers None:
    it could not reach a model, and the deterministic filter takes the search
    back exactly as it was. ``ranking`` on the result says which of the two
    happened, because the difference is not visible in a list of places.

    The order below is load-bearing. Routing happens after the radius and the
    halal filter and before the kind filter and the ceiling, because it is the
    only step that costs a network call and the only step whose answer changes
    what the ceiling is judging. It stays ahead of the kind filter -- one
    request either way, the same one it was before this filter existed -- so
    that the landscape below is priced on the same roads the list is. A
    landscape built on straight lines under a list built on roads would be two
    prices for the same outing.
    """
    adapters = get_adapters()
    # The radius is measured in a straight line, and that is correct as a
    # pre-filter: the great circle between two points is never longer than a
    # road between them, so a straight-line radius can only ever be too
    # generous. Nothing the road would have put inside it is dropped here --
    # only extra candidates come through, and the ceiling below removes them.
    # Routing first, to filter on road distance, would mean asking a public
    # service about the whole city to throw most of it away.
    nearby = adapters.maps.places_near(lat, lng, radius_km)
    matching = [place for place in nearby if not halal_only or place.halal]

    # One call for everything still standing. A 5 km radius holds a few dozen
    # places, well inside what OSRM's table service answers in one request, so
    # the whole search costs one round trip however many places it found.
    routed = await adapters.routing.road_metres(
        (lat, lng), [(place.lat, place.lng) for place in matching]
    )
    if len(routed) != len(matching):
        # An adapter that answered a different number of destinations than it
        # was asked about cannot be lined up with them, and pairing them off
        # anyway would put one place's distance on another place's fare. The
        # straight line is wrong by a known amount; that would be wrong by an
        # unknown one.
        routed = [None] * len(matching)

    evaluated = [
        evaluate_place(place, lat, lng, mode, room_sen, road_metres=metres)
        for place, metres in zip(matching, routed, strict=True)
    ]

    # The landscape is built here, before the kind filter and before the
    # ceiling, and both omissions are deliberate.
    #
    # It ignores the ceiling because its whole job is to say what the ceiling
    # ruled out. A landscape computed after the cap could only ever list what
    # the user can already see, and "the Japanese places start at RM42, which
    # is past today's room anyway" would be unsayable -- those rows would be
    # exactly the ones missing.
    #
    # It ignores the kind filter for the same reason one step out: when the
    # answer to "I want noodles" is that there are none, the useful reply is
    # what is there instead, and a landscape narrowed to noodles would be empty
    # beside an empty list.
    #
    # It does honour the halal filter, because that is not a ceiling to argue
    # with -- it is the user saying what they eat, and offering them the cheap
    # pork noodles they excluded is not information they asked for.
    landscape = price_landscape(evaluated)

    # Blank is nobody asking for a kind. A word that is not blank and matches
    # nothing is a different thing entirely, and comes back empty below.
    wanted = kind_key(kind) if kind and kind.strip() else None

    # The relevance pass, where there is one and a request for it to read. It
    # runs after the pricing so the model sees the places as the search
    # measured them, and before the ceiling so that dragging the ceiling is
    # still a local filter over an answer already given.
    #
    # None covers every way of not having an answer, and every one of them ends
    # in the same place: the kind filter, unchanged. Nothing is half-applied --
    # a list narrowed by a model that then failed would be neither of the two
    # things the screen can describe.
    judgements = None if rank is None or not request.strip() else await rank(request, evaluated)

    if judgements is None:
        # Any of the kinds a place carries, not only the one on its label. OSM
        # states two cuisines for a fifth of the places it knows anything
        # about, and matching on the label alone hid every one of the others: a
        # search for fried chicken missed Nando's, which OSM tags chicken and
        # portuguese.
        of_kind = evaluated if wanted is None else _matching(evaluated, wanted)
        ranking: Ranking = "deterministic"
        # Nobody asked for a kind, so nothing was turned away: see below.
        narrowed = wanted is not None
    else:
        of_kind = _judged(evaluated, judgements, request)
        ranking = "model"
        # A model that answered has narrowed the search even where it kept
        # everything, so what it left out is a near miss like any other.
        narrowed = True

    # The ceiling runs last, on the total the road produced. Applying it to a
    # straight-line total would admit places the user cannot actually afford --
    # the 3.7 km that is really 8.1 km of driving is RM12.05 of fare under a
    # ceiling it clears and RM20.39 in the car it does not.
    #
    # Price still orders the list, and a model's verdict never touches it: see
    # ``_order_key``.
    under_cap = sorted((p for p in of_kind if p.total_sen <= cap_sen), key=_order_key)

    # Split at the one line a model is allowed to draw: whether a place plainly
    # is the thing that was asked for, or is only near enough to mention. The
    # answers stay in ``places``; the rest go to their own field, where a client
    # has to say what they are before drawing one. Nothing is re-sorted -- the
    # order above already puts every strong match ahead of every weak one, so
    # this only cuts the list where it was already divided.
    #
    # ``match_strength`` is None on the whole deterministic path, so on that
    # path the answers are the list and the loose group is always empty.
    answers = [place for place in under_cap if place.match_strength != "weak"]
    loose = _loose(under_cap, len(answers))

    # What the kind filter turned away, held to the same ceiling the list is.
    # Disjoint from the list by id rather than by a second run of the filter,
    # so no reading of the two can ever put one place in both -- including the
    # place that matched on the second of the three kinds it carries.
    #
    # Only where a kind was actually asked for. With no filter nothing was
    # turned away, and a "did not match" list under no filter would be a group
    # of places with nothing in common but having been left out of nothing.
    matched = {place.id for place in of_kind}
    near_misses = (
        ()
        if not narrowed
        else _near_misses([p for p in evaluated if p.id not in matched and p.total_sen <= cap_sen])
    )

    # The one step that looks past the radius, and only from a narrowed search
    # that came back thin. An unnarrowed browse is left alone: everything in
    # range already is the answer to "what is around me", and there is no filter
    # over it for the distance to be compensating for.
    #
    # Thinness is counted over the answers alone. A list of one real match and
    # five loose ones is a thin answer wearing a long list, and it is exactly
    # the search that has most to gain from looking a little further out.
    beyond_radius: tuple[EvaluatedPlace, ...] = ()
    if narrowed and len(answers) <= FEW_NEARBY:
        beyond_radius = await _nearest_beyond_radius(
            lat=lat,
            lng=lng,
            mode=mode,
            halal_only=halal_only,
            cap_sen=cap_sen,
            room_sen=room_sen,
            radius_km=radius_km,
            # Every id the radius held, before any filter ran, so that nothing
            # already weighed and turned away can come back as somewhere new.
            inside={place.id for place in nearby},
            # None where the model narrowed this search: ``kind`` narrowed
            # nothing above and must narrow nothing out there either.
            wanted=None if judgements is not None else wanted,
            request=request,
            rank=rank,
        )

    return PlacesFound(
        places=tuple(answers),
        nearby_count=len(nearby),
        matching_count=len(matching),
        kind_count=len(of_kind),
        landscape=landscape,
        # Only where the ceiling admitted nothing whatever -- and a loose match
        # under the ceiling counts, because the ceiling did admit it. This group
        # answers "nothing came in under RM10", which is not the sentence a
        # search with somewhere loosely related under RM10 is telling.
        nearest_over_cap=() if under_cap else _nearest_over_cap(of_kind),
        nearest_beyond_radius=beyond_radius,
        loose_matches=loose,
        near_misses=near_misses,
        ranking=ranking,
    )


class UnknownPlace(LookupError):
    """No place with that id sits within range of where the plan was built."""


def find_place(place_id: str, *, lat: float, lng: float, radius_km: float = 5.0) -> Place | None:
    """The place a plan row's id names, or None if nothing around here is it.

    Scoped to the same search the plan came from rather than to the whole
    curated set, and on purpose. An id is a handle on a row somebody was shown;
    one resolved from the other side of the city would put a place on today
    that never appeared in any list. The radius defaults to ``find_places``'s
    own, so an id that came out of a plan resolves back through it.
    """
    for place in get_adapters().maps.places_near(lat, lng, radius_km):
        if place.id == place_id:
            return place
    return None


# ── Adding a plan to today ────────────────────────────────────────────────────

# Every place the planner knows is somewhere to eat, so a planned outing is
# food. Travel is folded into the same row rather than split off into a second
# transport draft: the user tapped one price for one outing, and two rows to
# confirm separately is not what they added.
PLAN_CATEGORY = "food"

# The curated set carries a word, not a percentage. The word is turned into a
# figure here so that every client agrees on what "high" is worth, and so that
# none of them can quietly promote an estimate.
#
# All three sit well under what a read claims -- the receipt reader's own scans
# come in at 94 -- because a price band is a weaker thing than a total printed
# on a slip. Even "high" means the estimate is well founded, never that the bill
# will read RM12.50.
PLAN_CONFIDENCE: dict[str, int] = {"high": 70, "medium": 50, "low": 30}

# A band this module does not recognise is read as the least certain one. The
# alternative -- refusing it, or splitting the difference at "medium" -- would
# either lose the user's tap over a vocabulary change or state more certainty
# than anything actually supports.
UNKNOWN_BAND_CONFIDENCE = PLAN_CONFIDENCE["low"]

# Said on the draft itself, because the toast that announced it is gone by the
# time the user reaches Activity. Three things it has to carry: where it came
# from, that the price is an estimate rather than a bill, and -- the part the
# whole design rests on -- that nothing has happened to today's money yet.
PLAN_NOTE = (
    "Planned, not spent — this is an estimate from your day plan. "
    "Nothing counts against today until you confirm it."
)


def confidence_for(band: str) -> int:
    """The percentage a place's confidence band is worth on a draft."""
    return PLAN_CONFIDENCE.get(band, UNKNOWN_BAND_CONFIDENCE)


async def add_to_today(
    session: AsyncSession,
    user: User,
    *,
    name: str,
    total_sen: int,
    confidence: str,
    today: date,
) -> TransactionView:
    """Put a planned outing on today's drafts. An intention, not a spend.

    A receipt says "I spent this"; a plan says "I intend to". Both are proposals
    until the user says otherwise, which is why this goes through
    ``create_transaction`` like every other capture path instead of writing a
    row of its own — and why adding one moves no figure. Drafts are excluded
    from every engine calculation, so safe-to-spend is exactly what it was until
    the user comes back and confirms they actually ate.

    ``total_sen`` is the whole outing, meal and travel together: it is the
    figure on the row that was tapped, and a draft for the meal alone would not
    be the thing the user thought they added.
    """
    return await create_transaction(
        session,
        user,
        merchant=name,
        amount_sen=total_sen,
        occurred_on=today,
        category=PLAN_CATEGORY,
        source=SOURCE_PLAN,
        confidence=confidence_for(confidence),
        note=PLAN_NOTE,
    )
