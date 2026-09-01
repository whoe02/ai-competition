"""Reading a request for somewhere to eat against the places actually in range.

The day planner narrows a search by matching a word against the cuisines
OpenStreetMap recorded, which for the whole of central Kuala Lumpur is two dozen
words. "beef", "satay", "nasi lemak", "laksa", "roti canai", "bak kut teh" and
"vegetarian" are none of them, and every one of those searches hands back an
empty list. Chicken works because Chicken happens to be one of the two dozen.

So the model is asked instead: here are the places, here is what the person
said, which of these answer it. It chooses; it does not compose. What comes back
is identifiers out of the rows it was handed and a couple of words for what each
one serves — never a name, never a price, never a distance. Those are measured,
and an identifier it did not receive is dropped by ``find_places`` rather than
trusted. That is the guard, in code, against the failure this project has
already produced once: a model with no tool results and an instruction to answer
invented a restaurant, and it read perfectly plausibly.

None is the answer to every way of not having one — the feature off, no key, a
timeout, a refusal, a reply that would not parse — and the planner falls back to
the deterministic filter unchanged. It follows ``plan_intent``, which does the
same for the ask box, for the same reason: a dead venue network must degrade the
answer, never hold the screen.
"""

from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from collections.abc import Sequence
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from kira.agent.llm import get_chat_model, offline_reason
from kira.config import get_settings
from kira.money import Money
from kira.services.day_plan import EvaluatedPlace, Judgement, kind_key


class RelevantPlace(BaseModel):
    """One place the model says answers the request."""

    id: str = Field(
        max_length=64,
        description="The id of one of the places you were given, copied exactly.",
    )
    strength: Literal["strong", "weak"] = Field(
        description=(
            "'strong' when this place is plainly the thing that was asked for, "
            "'weak' when it is a fair second best."
        ),
    )
    serves: str = Field(
        default="",
        max_length=40,
        description=(
            "What this place serves that answers the request, in two or three "
            "words: 'beef noodles', 'satay'. Not a sentence, and no prices."
        ),
    )


class Relevance(BaseModel):
    """Which of the places in front of you answer the request."""

    relevant: list[RelevantPlace] = Field(
        default_factory=list,
        description=(
            "Every place that answers the request, best first. Empty if none of "
            "them do."
        ),
    )


# Short on purpose. Three attempts at steering this model's behaviour by writing
# more of it are on the record here, and the third made Qwen stop calling tools
# altogether — after which, told to answer with no tool results in front of it,
# it invented a restaurant. Everything that actually has to hold is held in code
# below and in ``find_places``: an unknown id is dropped, money and distance are
# never read back from the reply, and a failure of any kind falls through to the
# word filter. This says what the job is and then stops.
_INSTRUCTION = """You are matching one request for somewhere to eat against a fixed list of places.

Say which of them answer the request, by id, and for each whether it is a strong or a
weak match. Choose only from the ids below — an id that is not in the list is dropped.

Judge what the place serves and nothing else. The prices and distances are here so you
know what the row is; they are already measured and are not yours to weigh.

The places:
{places}"""


def _price(sen: int) -> str:
    """The estimate as a person reads it. Display only — see ``_row``."""
    return f"RM{Money(sen).ringgit_str()}"


def _row(place: EvaluatedPlace) -> str:
    """One place, in the few fields relevance actually turns on.

    Not the whole record. Sixty-five places is a small prompt at five or six
    fields each and a long one at fifteen, and the rest of a place — its band,
    its share of today's room, its confidence, its coordinates — is either
    already decided or none of this model's business.

    The price and the distance are here because a row without them reads as a
    name floating free, and because the caller asked for them. They travel one
    way: nothing that comes back carries a figure, and ``find_places`` reads
    only ids and strengths out of the answer, so there is no path by which a
    model could alter one.
    """
    other = [k for k in place.kinds if kind_key(k) != kind_key(place.kind)]
    bits = [place.id, place.name, place.kind]
    if other:
        bits.append("also tagged " + ", ".join(other))
    if place.also_serves:
        bits.append("believed to do " + ", ".join(place.also_serves))
    bits.append(_price(place.total_sen))
    bits.append(f"{place.km:.1f} km")
    return " | ".join(bits)


# A food word, and nothing that could be mistaken for a measurement. A figure
# here would be a price or a distance the model authored, printed on a row
# beside the ones this search measured, and the user could not tell them apart.
# Dropped rather than scrubbed: a reason that quotes the request is a true
# sentence, where a half-erased one is a guess about what was meant.
_A_FIGURE = re.compile(r"\d")


def _serves(said: str) -> str:
    words = " ".join(said.split())
    return "" if _A_FIGURE.search(words) else words


# Dragging the ceiling re-runs the search, and the ceiling only ever filters
# locally: the same request over the same places has the same answer, so asking
# again would buy a call and a wait for a result already known. The key is the
# request and the ids the model was actually shown, which together are precisely
# its input — so a different origin, radius or halal setting produces different
# ids and misses, and a change of travel mode, which moves fares and not
# relevance, hits. That is a better key than the origin and mode themselves,
# which would miss on a mode change that cannot change the answer.
#
# Process-local, small, and never persisted. It holds an opinion about a menu,
# not a figure anyone will be shown: nothing in it is money, and the worst a
# stale entry can do is rank one restaurant where it ranked it a minute ago.
_CACHE_LIMIT = 64
_cache: OrderedDict[tuple[str, tuple[str, ...]], tuple[Judgement, ...]] = OrderedDict()


def _key(request: str, places: Sequence[EvaluatedPlace]) -> tuple[str, tuple[str, ...]]:
    return (" ".join(request.split()).casefold(), tuple(place.id for place in places))


def clear_cache() -> None:
    """Forget every remembered ranking. For tests, and for a reload."""
    _cache.clear()


async def rank(
    request: str, places: Sequence[EvaluatedPlace]
) -> tuple[Judgement, ...] | None:
    """Which of these places answer that request, or None if nothing could say.

    A ``PlaceRanker``. Every return of None means the caller should fall back to
    the deterministic kind filter; an empty tuple means the model read the
    request, looked at the places, and says none of them answer it — which is a
    real answer and is not the same thing.
    """
    settings = get_settings()
    # Checked here as well as by the caller, so that no route can turn this on
    # by forgetting to turn it off. A teammate on the same checkout must not pay
    # for a call they did not ask for.
    if not settings.plan_search_llm_enabled:
        return None
    if not request.strip() or not places:
        return None
    if offline_reason() is not None:
        return None

    key = _key(request, places)
    remembered = _cache.get(key)
    if remembered is not None:
        _cache.move_to_end(key)
        return remembered

    model = get_chat_model(streaming=False).with_structured_output(Relevance)
    conversation = [
        SystemMessage(_INSTRUCTION.format(places="\n".join(_row(place) for place in places))),
        HumanMessage(request),
    ]
    try:
        # The timeout bounds the whole call, retries included, as it does in
        # ``plan_intent`` — and it is shorter, because underneath this one there
        # is a filter that answers instantly and underneath that one there is
        # nothing.
        async with asyncio.timeout(settings.plan_search_llm_timeout_seconds):
            read = await model.ainvoke(conversation)
    except TimeoutError:
        return None
    except Exception:
        # A refusal, a dead network, an answer the parser rejected. None of them
        # is the user's problem, and none of them may leave a half-ranked list.
        return None

    if not isinstance(read, Relevance):
        # Prose where a filled schema was asked for.
        return None

    judged = tuple(
        Judgement(place_id=row.id.strip(), strength=row.strength, serves=_serves(row.serves))
        for row in read.relevant
        if row.id.strip()
    )
    # Only a real answer is remembered. A timeout cached would turn one slow
    # call into a search that is quietly the word filter for as long as the
    # process lives.
    _cache[key] = judged
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_LIMIT:
        _cache.popitem(last=False)
    return judged
