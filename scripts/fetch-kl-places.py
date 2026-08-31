#!/usr/bin/env python3
"""Build the curated KL place set the day planner's FakeMaps serves.

Run once, by hand, when the demo set needs refreshing. Use the API's own
interpreter, so the enrichment pass below can reach the app's model config:

    apps/api/.venv/bin/python scripts/fetch-kl-places.py

It writes apps/api/kira/adapters/data/kl_places.json. Nothing at runtime and
nothing in the test suite calls Overpass or a model -- a volunteer-run service
must not become a build dependency, the demo must work with no network at all,
and a search must not cost quota.

Names and coordinates come from OpenStreetMap. Prices do not: OSM has no menu
prices, and neither does any Places API, so the estimate is banded from the
kind of place it is and shipped with the confidence that deserves. Neither does
OSM know what is actually on a menu, which is what the enrichment pass is for.
"""

from __future__ import annotations

import json
import math
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

OVERPASS = "https://overpass-api.de/api/interpreter"
OUT = Path(__file__).resolve().parents[1] / "apps/api/kira/adapters/data/kl_places.json"

# Kuala Lumpur, loosely. Deliberately stops short of Selangor: the "nothing
# within range" state is a real one the UI must still be able to reach, and a
# test pins Penang returning nothing.
BBOX = (3.02, 101.61, 3.25, 101.76)

TARGET_TOTAL = 200

# OSM's halal tagging skews hard to fast-food chains: of 111 tagged places in
# KL, 33 are McDonald's. Taking them all buries the 51 independents -- the
# nasi kandar shops and kopitiams that are the point of the screen -- under a
# list that reads "McDonald's, McDonald's, McDonald's", all at the same price,
# so the ranking says nothing either. A brand earns a couple of slots, no more.
NAME_CAP_TOTAL = 6
NAME_CAP_DISTRICT = 1

# ...but variety must not cost a district its whole list. The Halal chip is on
# by default, and in outer KL the only halal-tagged places OSM knows are the
# very chains the cap throttles: within 5 km of Cheras it knows two McDonald's
# and three Marrybrown, and nothing else. Better a repeated brand there than a
# screen reading "nothing within range" in a suburb full of food.
HALAL_FLOOR_PER_DISTRICT = 2
FLOOR_RADIUS_KM = 5.0

# Each district gets its own share of the total so the set covers the city
# rather than piling up wherever OSM mappers were most active.
DISTRICTS: dict[str, tuple[float, float]] = {
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

# (label, estimate in sen, confidence). A band, not a price: the app says so on
# every row. Confidence tracks how standardised the pricing actually is, so a
# chain reads "high" and a place we know nothing about reads "low".
CUISINE_BANDS: dict[str, tuple[str, int, str]] = {
    "mamak": ("Mamak", 1200, "high"),
    "malaysian": ("Malaysian", 1400, "medium"),
    "malay": ("Malay", 1200, "high"),
    "indian": ("Indian", 1300, "high"),
    "pakistani": ("Pakistani", 1500, "medium"),
    "arab": ("Middle Eastern", 2600, "low"),
    "chinese": ("Chinese", 1800, "medium"),
    "cantonese": ("Chinese", 2000, "medium"),
    "noodle": ("Noodles", 1400, "medium"),
    "ramen": ("Ramen", 2800, "medium"),
    "japanese": ("Japanese", 4200, "low"),
    "sushi": ("Japanese", 4600, "low"),
    "korean": ("Korean", 4000, "low"),
    "thai": ("Thai", 2200, "medium"),
    "vietnamese": ("Vietnamese", 2000, "medium"),
    "indonesian": ("Indonesian", 1600, "medium"),
    "western": ("Western", 3500, "low"),
    "american": ("Western", 3500, "low"),
    "burger": ("Burgers", 1800, "high"),
    "pizza": ("Pizza", 2800, "medium"),
    "italian": ("Italian", 4200, "low"),
    "seafood": ("Seafood", 4500, "low"),
    "steak_house": ("Steakhouse", 8000, "low"),
    "chicken": ("Chicken", 1600, "high"),
    "coffee_shop": ("Cafe", 1500, "high"),
    "cafe": ("Cafe", 1500, "high"),
    "breakfast": ("Breakfast", 1400, "medium"),
    "dessert": ("Dessert", 1200, "medium"),
    "ice_cream": ("Dessert", 1000, "high"),
    "bakery": ("Bakery", 1100, "high"),
    "sandwich": ("Sandwiches", 1600, "high"),
}

AMENITY_FALLBACK: dict[str, tuple[str, int, str]] = {
    "fast_food": ("Fast food", 1500, "high"),
    "food_court": ("Food court", 1400, "medium"),
    "cafe": ("Cafe", 1600, "medium"),
    "restaurant": ("Restaurant", 2200, "low"),
}


def fetch() -> list[dict]:
    query = f"""
    [out:json][timeout:180];
    (
      node["amenity"~"^(restaurant|fast_food|cafe|food_court)$"]["name"]
        ({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
    );
    out body;
    """
    body = urllib.parse.urlencode({"data": query}).encode()
    request = urllib.request.Request(
        OVERPASS,
        data=body,
        headers={"User-Agent": "kira-demo-seed/1.0 (one-off curated demo fixture)"},
    )
    with urllib.request.urlopen(request, timeout=200) as response:
        return json.load(response)["elements"]


def cuisine_hits(tags: dict) -> list[tuple[str, int, str]]:
    """Every band the cuisine tag resolves to, in the order OSM states them.

    OSM lets one place carry several cuisines separated by semicolons, and 532
    of the 2,564 tagged places in the KL box do -- Nando's is
    ``chicken;portuguese``, Jake's Charbroil is ``steak_house;seafood``. Two
    spellings of one band (``cantonese;chinese``) collapse to one entry, since
    the point of the list is what the place can be found by.
    """
    hits: list[tuple[str, int, str]] = []
    labels: set[str] = set()
    for raw in (tags.get("cuisine") or "").split(";"):
        hit = CUISINE_BANDS.get(raw.strip().lower())
        if hit and hit[0] not in labels:
            labels.add(hit[0])
            hits.append(hit)
    return hits


def band(tags: dict) -> tuple[str, int, str]:
    """Label, estimate and confidence for a place, from what OSM knows of it.

    The FIRST cuisine that resolves, exactly as it always was. Recording the
    rest widens what a place can be found by and must not move what it costs:
    a place has not become dearer because OSM also calls it a seafood place.
    """
    hits = cuisine_hits(tags)
    if hits:
        label, sen, confidence = hits[0]
        # A recognisable chain prices predictably; an unbranded shop does not.
        if tags.get("brand") and confidence != "high":
            confidence = "high" if sen < 3000 else "medium"
        return label, sen, confidence
    return AMENITY_FALLBACK.get(tags.get("amenity", ""), ("Restaurant", 2200, "low"))


def kinds_of(tags: dict, primary: str) -> list[str]:
    """Every kind the place can be searched by, the display label first.

    A place whose cuisine tag resolved to nothing was banded off its amenity
    instead, so the one label ``band`` produced is all it can be found by.
    """
    return [hit[0] for hit in cuisine_hits(tags)] or [primary]


def is_halal(tags: dict) -> bool:
    """Only what OpenStreetMap actually states.

    Nothing is inferred from cuisine. Marking a halal place non-halal costs it
    custom; marking a non-halal place halal misleads someone about something
    that matters, and those two errors are not worth trading against each
    other. The UI never renders "not halal" -- the filter simply omits what is
    unverified -- so silence here stays honest.
    """
    return (tags.get("diet:halal") or "").lower() in {"yes", "only"}


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius, rad = 6371.0, math.pi / 180
    d_lat, d_lng = (lat2 - lat1) * rad, (lng2 - lng1) * rad
    h = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin(d_lng / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(h))


def district_of(lat: float, lng: float) -> str:
    return min(
        DISTRICTS,
        key=lambda name: (DISTRICTS[name][0] - lat) ** 2 + (DISTRICTS[name][1] - lng) ** 2,
    )


def signal(tags: dict) -> int:
    """Better-mapped entries are likelier to still be standing."""
    return sum(
        bool(tags.get(key))
        for key in ("cuisine", "brand", "website", "opening_hours", "addr:street")
    )


def address_of(tags: dict, district: str) -> str:
    """A street address where OSM has one, the locality where it does not.

    Only 23% of KL's food POIs carry addr:street, so most of these are the
    district rather than a doorstep. Never fabricate the rest of a line from a
    house number with no street to hang it on -- the row already carries a Maps
    link built from the coordinates, which finds the place regardless.
    """
    street = (tags.get("addr:street") or "").strip()
    if not street:
        return f"{district}, Kuala Lumpur"
    number = (tags.get("addr:housenumber") or "").strip()
    city = (tags.get("addr:city") or "Kuala Lumpur").strip()
    line = f"{number} {street}".strip()
    postcode = (tags.get("addr:postcode") or "").strip()
    tail = f"{postcode} {city}".strip()
    return f"{line}, {tail}"


# ── what a model believes, kept apart from what OpenStreetMap states ──────────

# OSM's cuisine tag is one or two words and a menu is not, so a place is often
# findable by nothing it actually sells: McDonald's is tagged ``burger`` and
# stops there, though it fries chicken all day. No refresh of the data reaches
# that, because there is no tag for it -- the only thing in this project that
# knows is a language model.
#
# So it is asked once, here, and the answer ships in the file. Not at query
# time: search stays instant, a search costs no quota, and the offline demo
# gets the benefit too, which a call made on a dead venue network never would.
#
# What comes back is stored in its own field and never folded into ``kinds``.
# ``kinds`` is what OpenStreetMap states about a real business; ``also_serves``
# is what a model believes about one. Everything downstream has to be able to
# say which of the two it is leaning on, and it cannot do that once they are
# one list.

# Roughly ten calls for the whole set rather than one per place. The user pays
# for these.
ENRICH_BATCH = 20

# A model answering with eight kinds for one coffee shop has stopped
# recognising the place and started listing food. What it named first is what it
# was surest of, so the tail is what goes.
ENRICH_MAX_PER_PLACE = 4

# What OSM says about the premises rather than about the plate. A place lands on
# one of these only because its cuisine tag resolved to nothing, so the label is
# the generator admitting it knows nothing about the menu -- which makes it the
# one answer a model must not be allowed to give. Offered them it took them:
# every McDonald's in the city came back "Fast food" and nothing else, which is
# true, adds nothing, and crowded out the chicken. Derived rather than listed,
# so a label that is also a real cuisine tag survives -- ``Cafe`` is both, and a
# shop that sells coffee is a fact about the plate.
PREMISES_NOT_FOOD = {label for label, _, _ in AMENITY_FALLBACK.values()} - {
    label for label, _, _ in CUISINE_BANDS.values()
}

ENRICH_PROMPT = """\
These are real restaurants and food shops in Kuala Lumpur, Malaysia. For each
one you have its name, the cuisines OpenStreetMap records for it, and the
district it stands in.

OpenStreetMap's cuisine tag is one or two words and a menu is not, so a place is
often findable by nothing it actually sells. It tags McDonald's "burger" and
stops there, though anyone in Malaysia can walk into one and order fried
chicken.

For each numbered place below, say which of these kinds a person could actually
walk in and order, beyond the ones already listed against it:

{vocabulary}

Rules:
- Use only words from that list, spelled exactly as they are written there.
- Add a kind for one of two reasons, and there is no third. Either it is a chain
  or a well-known shop and you actually know its menu -- a McDonald's in
  Malaysia sells fried chicken as well as burgers. Or its name says what it
  sells: "Ayam Goreng Berhantu" and "Nasi Ayam Hainan Chee Meng" are chicken
  shops whatever their tags say.
- Anything weaker is not a reason. "A place of this sort usually has it" is not
  one, and neither is "it might be on the menu somewhere".
- If you do not know the place, answer with an empty list. That is the correct
  answer and not a failure.
- Never dispute what OpenStreetMap already says. You may add kinds to a place.
  You may not remove one, and you may not say one is wrong.

Reply with JSON and nothing else: an object whose keys are the numbers below and
whose values are lists of kinds. For example:
{{"1": ["Chicken"], "2": [], "3": ["Cafe", "Dessert"]}}

{places}
"""

_JSON_OBJECT = re.compile(r"\{.*\}", re.S)


def fold(value: str) -> str:
    """The form two kind words are compared in.

    The same rule ``kira.services.day_plan.kind_key`` uses -- case and a plural
    ending, and nothing else -- so a word this pass keeps is a word that filter
    can actually match. Restated rather than imported because importing it would
    load the very file this script is in the middle of writing.
    """
    folded = " ".join(value.split()).casefold()
    return folded[:-1] if folded.endswith("s") else folded


def no_model_reason() -> str | None:
    """Why the enrichment pass cannot run right now, or None if it can.

    The Butler's own answer to the question rather than a second reading of the
    environment: one place decides whether there is a model to talk to, and it
    is the place the running app asks. The import is guarded because this script
    is also useful with nothing installed but the standard library.
    """
    try:
        from kira.agent.llm import offline_reason
    except ImportError as error:
        return f"kira is not importable here ({error})"
    return offline_reason()


def batch_prompt(vocabulary: list[str], batch: list[tuple[str, list[str], str]]) -> str:
    """One call's worth of places, as the model sees them.

    The name comes first because in Malaysia it is usually the strongest signal
    there is: "Nasi Ayam Hainan Chee Meng" is a chicken rice shop whatever its
    tags say, and a model reads that off the sign the way a person would.
    """
    places = "\n".join(
        f"{number}. {name} — OpenStreetMap says: {', '.join(kinds)} — {district}"
        for number, (name, kinds, district) in enumerate(batch, start=1)
    )
    listed = "\n".join(f"- {kind}" for kind in vocabulary)
    return ENRICH_PROMPT.format(vocabulary=listed, places=places)


def read_reply(
    reply: str, batch: list[tuple[str, list[str], str]], vocabulary: list[str]
) -> list[list[str]]:
    """One list of kinds per place in the batch, filtered to what is allowed.

    Every rule the prompt states is enforced again here, because a prompt is a
    request and this is the guarantee. A word outside the vocabulary -- "hawker",
    "street food" -- matches nothing the filter has and would sit in the file
    looking like data. A kind OSM already states would be a guess wearing the
    tag's clothes, and it is also how a model contradicts OSM without appearing
    to: re-asserting a tag is the first step towards disputing one.

    Always exactly as long as the batch, so beliefs cannot slide onto the wrong
    shops when a model skips a number.
    """
    match = _JSON_OBJECT.search(reply)
    if not match:
        raise ValueError(f"no JSON object in the reply: {reply[:200]!r}")
    answer = json.loads(match.group(0))
    if not isinstance(answer, dict):
        raise ValueError(f"expected a JSON object, got {type(answer).__name__}")

    allowed = {fold(kind): kind for kind in vocabulary}
    inferred: list[list[str]] = []
    for number, (_, kinds, _district) in enumerate(batch, start=1):
        raw = answer.get(str(number), answer.get(number, []))
        stated = {fold(kind) for kind in kinds}
        kept: list[str] = []
        seen: set[str] = set()
        for word in raw if isinstance(raw, list) else []:
            kind = allowed.get(fold(str(word)))
            if kind is None or fold(kind) in stated or fold(kind) in seen:
                continue
            seen.add(fold(kind))
            kept.append(kind)
        inferred.append(kept[:ENRICH_MAX_PER_PLACE])
    return inferred


def enrich(
    places: list[tuple[str, list[str], str]], vocabulary: list[str]
) -> list[list[str]] | None:
    """What each place also serves, or None if nothing was asked.

    None is the honest answer to "there was no model", and it is why this
    returns a whole answer or no answer at all. A file where some records carry
    the field and others do not would be unreadable: nothing downstream could
    tell a model saying "I do not know this shop" from a call that never
    happened. So one failed call abandons the pass rather than shipping half of
    one, and the file goes out exactly as it did before this existed.
    """
    reason = no_model_reason()
    if reason is not None:
        print(f"skipping the enrichment pass: {reason}", file=sys.stderr)
        print("  the file is written without also_serves", file=sys.stderr)
        return None

    from langchain_core.messages import HumanMessage

    from kira.agent.llm import get_chat_model

    model = get_chat_model()
    batches = [places[at : at + ENRICH_BATCH] for at in range(0, len(places), ENRICH_BATCH)]
    print(f"asking the model about {len(places)} places in {len(batches)} calls…", file=sys.stderr)

    inferred: list[list[str]] = []
    for number, batch in enumerate(batches, start=1):
        try:
            reply = model.invoke([HumanMessage(batch_prompt(vocabulary, batch))])
            content = reply.content if isinstance(reply.content, str) else str(reply.content)
            answered = read_reply(content, batch, vocabulary)
        except Exception as error:  # noqa: BLE001 -- any failure abandons the pass
            print(f"  call {number}/{len(batches)} failed: {error}", file=sys.stderr)
            print("  abandoning the pass; the file is written with no", file=sys.stderr)
            print("  also_serves at all rather than with half of one", file=sys.stderr)
            return None
        inferred.extend(answered)
        gained = sum(len(kinds) for kinds in answered)
        print(f"  {number}/{len(batches)}: {gained} inferences", file=sys.stderr)
    return inferred


def main() -> int:
    print("fetching from Overpass (one query, whole city)…", file=sys.stderr)
    elements = fetch()
    print(f"  {len(elements)} named food POIs in the KL box", file=sys.stderr)

    by_district: dict[str, list[dict]] = defaultdict(list)
    halal_pool: list[dict] = []
    for element in elements:
        tags = element.get("tags", {})
        name = (tags.get("name") or "").strip()
        if not name or len(name) > 80:
            continue
        record = {
            "lat": element["lat"],
            "lng": element["lon"],
            "tags": tags,
            "name": name,
            "osm_id": element["id"],
        }
        record["district"] = district_of(record["lat"], record["lng"])
        if is_halal(tags):
            halal_pool.append(record)
        else:
            by_district[record["district"]].append(record)

    print(f"  {len(halal_pool)} carry a diet:halal tag", file=sys.stderr)

    total_seen: dict[str, int] = defaultdict(int)
    district_seen: dict[tuple[str, str], int] = defaultdict(int)

    def take(
        record: dict, *, district_cap: int = NAME_CAP_DISTRICT, honour_total: bool = True
    ) -> bool:
        """Admit a place unless its name is already carrying the list.

        The floor pass sets ``honour_total=False``: a brand that has spent its
        global slots on richer districts must not thereby leave a thin one with
        nothing. Variety is a preference, coverage is the requirement -- and
        getting this the wrong way round is what emptied Cheras twice.
        """
        name = record["name"]
        here = (name, record["district"])
        if honour_total and total_seen[name] >= NAME_CAP_TOTAL:
            return False
        if district_seen[here] >= district_cap:
            return False
        total_seen[name] += 1
        district_seen[here] += 1
        return True

    # Independents before chains, and better-mapped before worse: an unbranded
    # shop is both likelier to be interesting and the thing the caps protect.
    def order(pool: list[dict]) -> list[dict]:
        return sorted(pool, key=lambda r: (bool(r["tags"].get("brand")), -signal(r["tags"]), r["name"]))

    # Halal places are the scarce resource -- the chip is on by default -- so
    # they get first refusal on the slots.
    chosen = [record for record in order(halal_pool) if take(record)]

    # No district may be left with an empty list under the default filter. Where
    # variety has starved one, admit the nearest halal places it actually has,
    # repeated brand and all.
    picked_ids = {id(record) for record in chosen}
    for name, (lat, lng) in DISTRICTS.items():
        def within(pool: list[dict]) -> int:
            return sum(
                1 for r in pool if haversine_km(lat, lng, r["lat"], r["lng"]) <= FLOOR_RADIUS_KM
            )

        shortfall = HALAL_FLOOR_PER_DISTRICT - within(chosen)
        if shortfall <= 0:
            continue
        nearby = sorted(
            (r for r in halal_pool if id(r) not in picked_ids),
            key=lambda r: haversine_km(lat, lng, r["lat"], r["lng"]),
        )
        for record in nearby:
            if shortfall <= 0:
                break
            if haversine_km(lat, lng, record["lat"], record["lng"]) > FLOOR_RADIUS_KM:
                break
            if take(record, district_cap=HALAL_FLOOR_PER_DISTRICT, honour_total=False):
                chosen.append(record)
                picked_ids.add(id(record))
                shortfall -= 1

    # Fill the rest evenly by district so no corner of the city comes back empty.
    remaining = TARGET_TOTAL - len(chosen)
    per_district = max(1, remaining // len(DISTRICTS))
    for name in DISTRICTS:
        picked = 0
        for record in order(by_district.get(name, [])):
            if picked >= per_district:
                break
            if take(record):
                chosen.append(record)
                picked += 1

    records = []
    # Name, tagged kinds and district, in step with ``records``. This is
    # everything the model is told, and the district is in it because a shop's
    # neighbourhood is often what places it.
    described: list[tuple[str, list[str], str]] = []
    seen: set[str] = set()
    for index, record in enumerate(sorted(chosen, key=lambda r: (r["district"], r["name"]))):
        label, sen, confidence = band(record["tags"])
        key = f"{record['name'].lower()}|{round(record['lat'], 4)}"
        if key in seen:
            continue
        seen.add(key)
        # The label is the first of these, always. The rest are the other
        # cuisines OSM states, kept so a search for seafood can reach a
        # steakhouse that serves it.
        kinds = kinds_of(record["tags"], label)
        records.append(
            {
                "id": f"kl{index:03d}",
                "name": record["name"],
                "kind": label,
                "kinds": kinds,
                # Filled by the enrichment pass below, and deleted outright if
                # that pass did not run. Placed here so the file reads with the
                # tag and the belief about it side by side.
                "also_serves": [],
                "lat": round(record["lat"], 6),
                "lng": round(record["lng"], 6),
                "estimate_sen": sen,
                "confidence": confidence,
                "halal": is_halal(record["tags"]),
                "address": address_of(record["tags"], record["district"]),
                "note": f"{label} in {record['district']}. Estimate, not a quoted price.",
            }
        )
        described.append((record["name"], kinds, record["district"]))

    # The vocabulary the model is held to is the one the data itself uses, read
    # off the records just built. Offered a free hand it answers "hawker" and
    # "street food", which no filter has a column for -- words that match
    # nothing and quietly do nothing. Less the premises labels, which are the
    # data's way of saying the menu is unknown.
    vocabulary = sorted(
        {kind for record in records for kind in record["kinds"]} - PREMISES_NOT_FOOD
    )
    inferred = enrich(described, vocabulary)
    if inferred is None:
        for record in records:
            del record["also_serves"]
    else:
        for record, kinds in zip(records, inferred, strict=True):
            record["also_serves"] = kinds

    payload = {
        "_comment": (
            "Curated demo set for the day planner. Names and coordinates from "
            "OpenStreetMap, (c) OpenStreetMap contributors, ODbL "
            "(https://www.openstreetmap.org/copyright). Prices are NOT from OSM: "
            "no Places API exposes menu prices, so each estimate is banded from "
            "the kind of place it is and carries its own confidence. 'kind' is "
            "the label a row is shown under and the one the estimate came from; "
            "'kinds' is every cuisine OSM states for the place, that label "
            "first, and is what a search matches against. 'also_serves' is NOT "
            "from OSM either: it is what a language model believes the place "
            "also sells, asked once at build time and never merged into "
            "'kinds', so that what OSM states and what a model guessed stay "
            "tellable apart. It is absent from every record when the generator "
            "had no model to ask. 'halal' is "
            "true only where OSM states it; unverified is false, and the UI "
            "filters on it rather than labelling anything 'not halal'. "
            "Regenerate with scripts/fetch-kl-places.py."
        ),
        "places": records,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    halal_count = sum(r["halal"] for r in records)
    multi_kind = sum(len(r["kinds"]) > 1 for r in records)
    districts = defaultdict(int)
    for record in chosen[: len(records)]:
        districts[record["district"]] += 1
    print(f"wrote {len(records)} places to {OUT}", file=sys.stderr)
    print(f"  halal: {halal_count}  districts: {len(districts)}", file=sys.stderr)
    print(f"  carrying more than one kind: {multi_kind}", file=sys.stderr)

    if inferred is not None:
        gained = sum(bool(record["also_serves"]) for record in records)
        total = sum(len(record["also_serves"]) for record in records)
        common = Counter(kind for record in records for kind in record["also_serves"])
        print(f"  also_serves: {gained} places, {total} inferences", file=sys.stderr)
        said = ", ".join(f"{kind} {count}" for kind, count in common.most_common(10))
        print(f"  most inferred: {said}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
