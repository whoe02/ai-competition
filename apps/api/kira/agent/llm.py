"""The chat model, in two implementations behind one interface.

Online is Qwen through DashScope's OpenAI-compatible endpoint. Offline is a
deterministic model that emits the same tool calls and writes the same shape of
answer. The graph, the tools, the guard, the evidence and the approval flow are
identical either way — a dead venue network degrades the Butler's prose, not
its behaviour.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from kira.config import get_settings
from kira.services.day_plan import kind_key, known_kinds


def _rm(sen: int | None) -> str:
    """RM60, RM18.90 — the way the number is said out loud, not stored."""
    if sen is None:
        return "RM0"
    whole, minor = divmod(abs(int(sen)), 100)
    sign = "-" if sen < 0 else ""
    body = f"{whole:,}" if minor == 0 else f"{whole:,}.{minor:02d}"
    return f"{sign}RM{body}"


_AMOUNT = re.compile(
    r"(?:rm|myr)\s?(\d{1,7}(?:,\d{3})*(?:[.,]\d{1,2})?)"
    r"|(\d{1,7}(?:,\d{3})*(?:\.\d{1,2})?)\s*ringgit",
    re.I,
)

# A comma with three digits behind it is a thousands separator and belongs to
# the whole part; a comma with one or two is the decimal point half the world
# writes. Told apart by what follows rather than assumed, because this app
# prints its own figures grouped -- ``Money.ringgit_str`` and the house style in
# prompt.py both say RM1,234.56 -- so a user quoting a figure back at the Butler
# is quoting one with a group separator in it.
_GROUPING = re.compile(r",(?=\d{3})")


def _amount_sen(text: str) -> int | None:
    match = _AMOUNT.search(text)
    if not match:
        return None
    raw = _GROUPING.sub("", match.group(1) or match.group(2)).replace(",", ".")
    whole, _, minor = raw.partition(".")
    return int(whole) * 100 + int((minor + "00")[:2] or 0)


# ── the offline model ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Route:
    """One demo-script question: which tools it needs, and how it reads back."""

    name: str
    pattern: re.Pattern[str]
    tools: tuple[str, ...]
    arguments: Any = None
    compose: Any = None


def _payload(messages: Sequence[BaseMessage], tool: str) -> dict[str, Any] | list | None:
    """The value a tool actually returned this run, or None if it did not run."""
    for message in reversed(messages):
        if isinstance(message, ToolMessage) and message.name == tool:
            try:
                return json.loads(message.content if isinstance(message.content, str) else "")
            except (json.JSONDecodeError, TypeError):
                return None
    return None


def _last_human(messages: Sequence[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


def _afford_args(text: str, attachment: dict[str, Any] | None) -> dict[str, Any]:
    sen = _amount_sen(text) or (attachment or {}).get("amount_sen") or 0
    label = ""
    for candidate in ("dinner", "lunch", "coffee", "grab", "taxi", "groceries", "movie"):
        if candidate in text.lower():
            label = candidate
            break
    return {"amount_sen": max(1, sen), "label": label}


_HALAL = re.compile(r"\bhalal\b", re.I)

# Two words the curated set uses as a kind of food that a person does not.
# "Restaurant" in a sentence means any eatery, and "breakfast" is a time of
# day: reading either as a filter would answer "where can I eat breakfast"
# with the four places tagged Breakfast and quietly drop every kopitiam in
# range. The vocabulary itself is still derived from the data below — a word
# that leaves the set only makes its line here inert.
_NOT_A_CUISINE = {"restaurant", "breakfast"}

# One pattern per kind the places actually carry, longest first so "middle
# eastern" is tried before "eastern" would be, and singular-or-plural because
# people ask for noodles and for a noodle. Built off ``kind_key`` so this and
# the filter it feeds agree on what a kind word is.
_KINDS = tuple(
    (re.compile(rf"\b{re.escape(kind_key(kind))}s?\b", re.I), kind)
    for kind in sorted(known_kinds(), key=len, reverse=True)
    if kind_key(kind) not in _NOT_A_CUISINE
)

# "I feel like noodles" names no meal, no money and no map, so the route below
# read it as small talk and answered with today's balance. It is in fact the
# clearest request the planner ever gets. What makes the trigger safe is that it
# has to land on a word the places actually carry: "I feel like saving more"
# still goes nowhere near it, and a kind that leaves the data leaves here too.
_CRAVING = (
    (
        r"\b(?:feel like|feeling like|craving|in the mood for|fancy|i want)\s+"
        # Room for how the words actually arrive between the wanting and the
        # food: "I want to eat fried chicken" puts three of them there. Bounded,
        # so the trigger still has to land on a real kind word rather than
        # wandering down the sentence looking for one.
        r"(?:\w+\s+){0,3}(?:"
        + "|".join(re.escape(kind_key(kind)) for _, kind in _KINDS)
        + r")s?\b"
    )
    if _KINDS
    # An empty alternation matches the empty string, which would read "I want"
    # on its own as a request for lunch. With no vocabulary there is no craving
    # to recognise, so this recognises nothing.
    else r"(?!)"
)


# The curated set's own spelling, keyed by the form a user's word folds to.
# Built off the same ``_KINDS`` as everything else here, so a word that is not a
# filter in a sentence is not one in a follow-up either.
_KIND_BY_KEY = {kind_key(kind): kind for _, kind in _KINDS}

# Everything a follow-up about food is made of besides the food itself. "What
# about japanese instead" is a whole sentence that means nothing but
# "japanese", and so is "korean then". Kept to words that carry no subject of
# their own, because the sentence this has to keep its hands off is "I want to
# save for a japanese trip" — which still has "want", "save" and "trip" left in
# it once these come out, and so is not a bare kind word.
_FOLLOW_UP_FILLER = re.compile(
    r"\b(?:what|how|about|instead|then|or|else|maybe|actually|rather|okay|ok|"
    r"and|hmm|please|food|cuisine|some|something|a|an|the|now|today|tonight)\b"
    r"|[^\w\s]",
    re.I,
)


def _bare_kind(text: str) -> str | None:
    """The kind of food a message is nothing but, or None if it is more.

    "Nothing but" is the whole of the safety here, and the reason this is not a
    search for a kind word anywhere in the sentence. "I want to save for a
    japanese trip" carries one and is about a holiday — and the places route is
    tried before goals, so a looser reading would answer it with dinner.
    """
    return _KIND_BY_KEY.get(kind_key(_FOLLOW_UP_FILLER.sub(" ", text)))


def _places_args(text: str) -> dict[str, Any]:
    """The parts of "noodles, halal, under RM15" a regex can be trusted with.

    Offline there is no model here to read a sentence, and the planner was
    being called with no arguments at all — so a halal request came back as
    everything nearby, which is the one filter where showing more than was
    asked for is wrong rather than merely generous. The ceiling comes out of
    the same ``_amount_sen`` the affordability route uses; a second parser
    would be a second answer to what RM15 is worth.

    An argument is only set when it was actually found. Anything unset falls to
    the tool's own default, where a guess would be a constraint the user never
    gave.
    """
    args: dict[str, Any] = {}
    if _HALAL.search(text):
        args["halal_only"] = True
    cap_sen = _amount_sen(text)
    # cap_sen is gt=0 on the tool, and "RM0" is not a ceiling anyone means.
    if cap_sen:
        args["cap_sen"] = cap_sen
    for pattern, kind in _KINDS:
        if pattern.search(text):
            args["kind"] = kind
            break
    return args


def _listed(parts: Sequence[str]) -> str:
    """a, b and c — the way a person reads a short list out loud."""
    if len(parts) < 2:
        return "".join(parts)
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _places_unread(text: str) -> str:
    """What the offline reading of a request for somewhere to eat left behind.

    It cannot name the words it missed, because it never understood any of
    them — so it says what it did read and states outright that the rest of the
    sentence went unanswered. Answering as though the whole request had been
    understood is the failure this exists to prevent: a list that quietly
    dropped half of what was asked reads exactly like one that honoured all of
    it.
    """
    read = _places_args(text)
    kept = []
    if read.get("halal_only"):
        kept.append("halal only")
    if read.get("cap_sen") is not None:
        kept.append(f"a ceiling of {_rm(read['cap_sen'])}")
    if read.get("kind") is not None:
        kept.append(f"{str(read['kind']).lower()} to eat")
    opening = "Offline I can only pick a price, the word halal and a kind of food out of a request"
    if not kept:
        return (
            f"{opening}, and I found none of them in what you asked, so nothing in it "
            "narrowed this."
        )
    return (
        f"{opening}. Out of what you asked I read {_listed(kept)}, and nothing "
        "else — any other condition in it went unread."
    )


def _priced_kinds(result: dict[str, Any]) -> list[tuple[str, int]]:
    """The price landscape as (kind, cheapest whole outing), cheapest first.

    Sorted here rather than taken on trust. The rows arrive in price order, and
    two of the sentences below read "the cheapest" straight off the front of
    them — a claim that would quietly become false if that order ever changed.
    """
    rows = []
    for row in result.get("price_landscape") or []:
        if not isinstance(row, dict):
            continue
        price = row.get("cheapest_total_sen")
        if isinstance(price, int):
            rows.append((str(row.get("kind", "")).lower(), price))
    return sorted(rows, key=lambda row: (row[1], row[0]))


def _landscape(result: dict[str, Any], limit: int = 3) -> str:
    """The cheapest few kinds of food in range, priced.

    The whole reason the planner hands the offline composer a landscape: an
    empty list is otherwise answered with an apology, where the useful answer
    is what the ceiling actually reaches. Named as kinds and never as shops —
    a row here is a price for a category, and turning one into a place to go
    would be inventing a name.
    """
    rows = _priced_kinds(result)[:limit]
    if not rows:
        return ""
    said = _listed([f"{kind} from {_rm(price)}" for kind, price in rows])
    return f"What is around you: {said}."


def _within_reach(result: dict[str, Any], cap_sen: int | None, limit: int = 3) -> str:
    """What the money does reach, said where the list came back with nothing.

    "Nothing found" is the one answer that leaves the user no move. What the
    ceiling actually reaches is a fact the landscape already holds, and it is
    the same fact whether they raise the ceiling or eat something else.

    Empty where the ceiling reaches nothing at all, and that is deliberate:
    ``_nearest_above`` answers that case with a name and a price, which is the
    same fact with somewhere to go attached. Where a kind filter is what
    emptied the list rather than the money, the two are saying different things
    and both belong in the reply.
    """
    rows = _priced_kinds(result)
    if not rows or cap_sen is None:
        return ""
    within = [row for row in rows if row[1] <= cap_sen]
    if not within:
        return ""
    said = _listed([f"{kind} from {_rm(price)}" for kind, price in within[:limit]])
    return f"{_rm(cap_sen)} reaches {said}."


def _nearest_above(result: dict[str, Any], cap_sen: int | None, limit: int = 3) -> str:
    """The closest places above the ceiling, named, where the list is empty.

    The planner only fills ``nearest_over_cap`` when the ceiling admitted
    nothing whatever, so reaching this means the honest answer to "where can I
    eat" was going to be "nowhere". That is true and it is useless: the person
    still has to eat, and the search already knows what the nearest thing costs.

    Said as being over the ceiling, in the same breath as the price, because
    that is the whole difference between offering an alternative and quietly
    raising the ceiling on the user's behalf.
    """
    rows = []
    for place in result.get("nearest_over_cap") or []:
        if not isinstance(place, dict):
            continue
        name, total = place.get("name"), place.get("total_sen")
        if isinstance(name, str) and name and isinstance(total, int):
            rows.append((name, total))
    if not rows:
        return ""
    # Sorted here rather than taken on trust, for the same reason
    # ``_priced_kinds`` is: "the closest" is a claim about the front of this
    # list, and it would quietly go false if the order upstream ever changed.
    rows.sort(key=lambda row: (row[1], row[0]))
    name, total = rows[0]
    over = "" if cap_sen is None else f", {_rm(total - cap_sen)} over {_rm(cap_sen)}"
    said = f"The closest I can get you is {name} at {_rm(total)}{over}."
    others = rows[1:limit]
    if others:
        said += " After that: " + _listed([f"{n} at {_rm(t)}" for n, t in others]) + "."
    return said


def _out_of_reach(result: dict[str, Any], cap_sen: int | None, limit: int = 3) -> str:
    """What the money does not reach, said beside a list that is not empty.

    The other half of ``_within_reach``, and the half that belongs next to a
    recommendation: the list itself already shows what the ceiling admitted, so
    the thing left unsaid is which whole kinds of food it ruled out.
    """
    if cap_sen is None:
        return ""
    above = [row for row in _priced_kinds(result) if row[1] > cap_sen]
    if not above:
        return ""
    # Named while there are few enough to name, counted once there are not.
    # "The western and japanese places" is worth more than "9 other kinds"; a
    # sentence listing nine of them is worth less than either.
    subject = (
        f"the {_listed([kind for kind, _ in above])} places"
        if len(above) <= limit
        else f"{len(above)} other kinds of food around you"
    )
    return f"{_rm(cap_sen)} will not reach {subject}, which start at {_rm(above[0][1])}."


def _kind_starts_at(result: dict[str, Any], kind: Any) -> int | None:
    """The cheapest whole outing of one kind of food, out of the landscape."""
    if not isinstance(kind, str) or not kind.strip():
        return None
    wanted = kind_key(kind)
    for row_kind, price in _priced_kinds(result):
        if kind_key(row_kind) == wanted:
            return price
    return None


def _compose_afford(messages: Sequence[BaseMessage], text: str) -> str:
    result = _payload(messages, "calculate_safe_to_spend") or {}
    thing = result.get("label") or "it"
    if result.get("fits"):
        head = (
            f"Yes — {_rm(result.get('amount_sen'))} for {thing} leaves you "
            f"{_rm(result.get('remaining_sen'))} today."
        )
        sub = (
            f"Bills and your buffer were already set aside before that number, so this is "
            f"spare. Spend it and the rest of the cycle still runs at about "
            f"{_rm(result.get('per_day_after_sen'))} a day."
        )
    else:
        head = (
            f"It fits, but it borrows — {_rm(result.get('amount_sen'))} is "
            f"{_rm(result.get('over_by_sen'))} over today's room."
        )
        sub = (
            f"Nothing breaks: the {result.get('days_to_payday', 0)} days to payday absorb it at "
            f"about {_rm(result.get('per_day_after_sen'))} a day instead. Your bills and buffer "
            "are untouched either way."
        )
    return f"{head}\n{sub}"


def _compose_snapshot(messages: Sequence[BaseMessage], text: str) -> str:
    snap = _payload(messages, "get_financial_snapshot") or {}
    activity = _payload(messages, "list_activity") or {}
    head = f"You have {_rm(snap.get('safe_today_sen'))} safe to spend today."
    sub = (
        f"{_rm(snap.get('balance_sen'))} in the account, {_rm(snap.get('reserved_sen'))} held for "
        f"bills, {_rm(snap.get('buffer_sen'))} kept as your buffer and "
        f"{_rm(snap.get('goal_reserve_sen'))} going to your goals. What is left runs at "
        f"{_rm(snap.get('per_day_sen'))} a day for {snap.get('days_to_payday', 0)} days."
    )
    drafts = activity.get("drafts") or []
    if drafts:
        sub += f" {len(drafts)} draft{'s' if len(drafts) != 1 else ''} are still waiting on you."
    return f"{head}\n{sub}"


def _compose_drop(messages: Sequence[BaseMessage], text: str) -> str:
    snap = _payload(messages, "get_financial_snapshot") or {}
    activity = _payload(messages, "list_activity") or {}
    days = activity.get("days") or []
    latest = days[0] if days else {}
    head = (
        f"Because {_rm(latest.get('total_sen'))} landed on "
        f"{latest.get('date', 'the ledger')} and the day's allowance did not grow."
    )
    sub = (
        f"Nothing was reserved differently: {_rm(snap.get('reserved_sen'))} for bills and "
        f"{_rm(snap.get('buffer_sen'))} of buffer are the same as yesterday. Today's room fell to "
        f"{_rm(snap.get('safe_today_sen'))} purely because that spending is now confirmed."
    )
    return f"{head}\n{sub}"


def _compose_goals(messages: Sequence[BaseMessage], text: str) -> str:
    goals = _payload(messages, "list_goals") or []
    if not goals:
        return (
            "You have no goals set yet.\nGive me one target and a monthly figure, and I "
            "will hold it back before I tell you what is safe to spend."
        )
    chosen = goals[0]
    for goal in goals:
        if any(word in text.lower() for word in goal["name"].lower().split()):
            chosen = goal
            break
    head = (
        f"{chosen['name']} is at {_rm(chosen.get('saved_sen'))} of "
        f"{_rm(chosen.get('target_sen'))} — {chosen.get('months_left', 0)} months to go."
    )
    sub = (
        f"That is {_rm(chosen.get('monthly_sen'))} a month, reserved before anything is called "
        "spare. It is not affected by what you spend today."
    )
    return f"{head}\n{sub}"


def _compose_bills(messages: Sequence[BaseMessage], text: str) -> str:
    bills = _payload(messages, "list_commitments") or []
    if not bills:
        return "Nothing is due.\nNo bills are on the books for the rest of this cycle."
    first = bills[0]
    total = sum(bill.get("amount_sen", 0) for bill in bills)
    head = (
        f"{first['name']} is next — {_rm(first.get('amount_sen'))} in "
        f"{first.get('days_until', 0)} days."
    )
    sub = (
        f"{len(bills)} bills totalling {_rm(total)} are already held back, which is why "
        "today's number is smaller than your balance."
    )
    return f"{head}\n{sub}"


def _compose_attachment(messages: Sequence[BaseMessage], text: str) -> str:
    read = _payload(messages, "inspect_attachment") or {}
    afford = _payload(messages, "calculate_safe_to_spend") or {}
    if not read.get("attached"):
        return (
            "I did not get the attachment.\nTry the scan or the microphone again and I "
            "will read it."
        )
    head = (
        f"{_rm(read.get('amount_sen'))} at {read.get('merchant', 'that merchant')} — "
        f"that leaves {_rm(afford.get('remaining_sen'))} for today."
    )
    sub = (
        f"I read it at {read.get('confidence', 0)}% confidence and it is sitting as a draft. "
        "Nothing counts against your day until you confirm it."
    )
    return f"{head}\n{sub}"


def _compose_remember(messages: Sequence[BaseMessage], text: str) -> str:
    return (
        "Noted — I will hold on to that.\n"
        "You can read back everything I remember, and correct or delete any of it, under More."
    )


def _compose_overspend(messages: Sequence[BaseMessage], text: str) -> str:
    snap = _payload(messages, "get_financial_snapshot") or {}
    over = _amount_sen(text) or 0
    days = max(1, snap.get("days_to_payday", 1))
    head = (
        f"{_rm(over)} over is recoverable — it is about {_rm(over // days)} a day "
        "between now and payday."
    )
    sub = (
        "Your bills and your buffer stay where they are. Comparing that against pausing a "
        "goal contribution needs the plan engine, which is not built yet — so for now I can "
        "show you the shape of it, not apply it."
    )
    return f"{head}\n{sub}"


_ASKED = re.compile(r"^\s*(?:please\s+)?remember(?:\s+that)?[,:\s]+", re.I)


def _stated(text: str) -> str:
    """The fact, not the request for it: "Remember that X" is kept as "X"."""
    fact = _ASKED.sub("", text.strip())
    return (fact[:1].upper() + fact[1:])[:280] if fact else text.strip()[:280]


def _compose_places(messages: Sequence[BaseMessage], text: str) -> str:
    result = _payload(messages, "build_day_plan") or {}
    places = result.get("places") or []
    # ``near_misses`` is in the payload and is deliberately never read here.
    # Those are the places the kind filter turned away, and the only reason to
    # mention one is knowing it serves the thing anyway -- that McDonald's,
    # tagged burgers, fries chicken all day. That is world knowledge, and this
    # composer is a handful of regexes: it has none, cannot get any, and a rule
    # that guessed from a name would be inventing a menu. So the names below
    # are the matches and nothing else, and the near misses go unmentioned
    # rather than mentioned wrongly.
    #
    # Some of that same world knowledge does reach here, and only because it
    # was written down before the demo started: a place a model believed also
    # serves the thing is a match now, and it is in ``places`` with the basis
    # recorded on it. That is still not something this composer may assert. It
    # reads the basis and says why the place is on the list; what the place
    # serves is a menu, and nothing here has read one.

    # Said whatever came back, empty list included. What was read out of the
    # request is the same either way, and it is the half of the answer the user
    # cannot check for themselves.
    unread = _places_unread(text)

    # Now that a price in the request becomes the ceiling, the two figures come
    # apart, and every sentence below that leans on one of them has to say which.
    # "The only one that fits" against a ceiling the user named is a claim about
    # their day that this list does not support.
    cap_sen, room_sen = result.get("cap_sen"), result.get("room_sen")
    own_cap = cap_sen != room_sen

    # An empty list has three different causes and the offline answer must not
    # blame the wrong one, exactly as the screen must not. The counts nest:
    # nothing in range, nothing halal in range, nothing under the ceiling.
    if not places:
        if result.get("nearby_count") == 0:
            body = (
                "Nothing I know of is within range of there. My set of places only "
                "covers central KL, so that is a gap in what I have been given, not "
                "a verdict on what is open."
            )
        elif result.get("matching_count") == 0:
            body = (
                "There are places within range, but none I can confirm are halal, so "
                "I have left them out. Say the word and I will show them anyway."
            )
        elif result.get("kind_count") == 0:
            # The fourth cause, and the one the ceiling has nothing to do with:
            # there is food in range, it is simply not that food. Saying what is
            # there instead is the whole of the answer — "no noodles" on its own
            # sends the user back to a screen they have already read. Phrased as
            # "no burgers within range" rather than "there is nothing burgers"
            # because half these words are adjectives and half are plural nouns,
            # and this is the frame that carries both.
            body = (
                f"No {str(result.get('kind', '')).lower()} within range of you — "
                f"{result.get('matching_count')} other places are, and no ceiling is "
                "what is in the way. " + _landscape(result)
            )
        else:
            # Said about the kind that was asked for where there was one. "There
            # are places nearby, but none under RM15" is a false sentence when
            # six of the seven are cheap and simply not Japanese. Where the
            # landscape knows what that kind starts at, the price is the answer:
            # it is the figure that says how far off the ceiling actually is.
            kind = result.get("kind")
            starts_at = _kind_starts_at(result, kind)
            ceiling = (
                f"The {str(kind).lower()} places within range start at {_rm(starts_at)}, "
                f"over {_rm(cap_sen)}."
                if starts_at is not None
                else f"There are places nearby, but none under {_rm(cap_sen)}."
            )
            # An empty list is where the answer stopped being useful. The
            # planner hands over the closest few places above the ceiling for
            # exactly this, so the reply is a name and a price rather than an
            # apology — while still saying, in the same sentence, that it is
            # over. What the money does reach still stands beside it: where a
            # kind filter is what emptied the list, those are two different
            # facts and the user wants both.
            rest = f"{_nearest_above(result, cap_sen)} {_within_reach(result, cap_sen)}".strip()
            if own_cap:
                body = (
                    f"{ceiling} That is the ceiling I read out of what you asked; today "
                    f"itself has room for {_rm(room_sen)}. " + rest
                )
            else:
                body = (
                    f"{ceiling} That is what today has room for, not what the food is "
                    "worth. " + rest
                )
        return f"{body.rstrip()}\n{unread}"

    # One place, named, with what the outing costs and why it is that one.
    # "Five options between RM13 and RM14" answers a question nobody asked: the
    # user wants to know where to go, and a count and a range is a description
    # of the filter rather than an answer to that.
    best = places[0]
    head = (
        f"{best.get('name')} — {_rm(best.get('total_sen'))} for the whole outing, "
        f"meal and travel together."
    )
    share = best.get("share")
    if share:
        head += f" That is about {round(share * 100)}% of today's room."

    # Counted off what the search found and not off what it handed over: the
    # planner only sends the cheapest dozen, so a figure taken from the list
    # would be about the size of the message rather than about the
    # neighbourhood.
    total = result.get("total_under_cap")
    found = total if isinstance(total, int) else len(places)

    # Why this one and not another, which is the half a list leaves out. Offline
    # the only thing here that can be weighed is the price order the service
    # returned, so that is what is claimed and no more: a preference weighed
    # against these places would be one nothing here read.
    if found <= 1:
        head += (
            f" It is the only one under {_rm(cap_sen)}."
            if own_cap
            else " It is the only one that fits."
        )
    else:
        head += (
            f" I picked it on price: it is the cheapest of the {found} that came in "
            f"under {_rm(cap_sen)}."
        )

    others = places[1:3]
    if others:
        listed = ", ".join(f"{p.get('name')} at {_rm(p.get('total_sen'))}" for p in others)
        head += f" After that: {listed}."
        # Counted rather than left implied, so three names do not read as the
        # whole list when the search found more.
        rest = found - 1 - len(others)
        if rest > 0:
            head += f" {rest} more came in under {_rm(cap_sen)} as well."

    # Which of the names just said are on this list on a belief rather than on a
    # tag. Said outright, because the widened filter is the one change that can
    # put a place in front of the user for a reason the row itself does not
    # show, and a name given with no qualification is a name the user will read
    # as the data's. The sentence stops where the belief does: it says why the
    # place is here, never that it serves the food.
    named = [best, *others]
    believed = [str(p.get("name")) for p in named if p.get("match_basis") == "inferred"]
    if believed:
        asked = str(result.get("kind") or "").lower()
        head += (
            f" {_listed(believed)} is on this list on a belief that it also does "
            f"{asked}, not on a tag saying so."
            if len(believed) == 1
            else (
                f" {_listed(believed)} are on this list on a belief that they also do "
                f"{asked}, not on tags saying so."
            )
        )

    # What the ceiling ruled out, in kinds of food. The list above is already
    # the answer to what it let through, so this is the part of the picture the
    # user cannot see from it.
    ruled_out = _out_of_reach(result, cap_sen)
    sub = f"{ruled_out} " if ruled_out else ""
    sub += "Every price is an estimate, never a quoted menu price."
    # Never let the prose imply a precision the distance did not have.
    if best.get("distance_basis") == "straight_line":
        sub += (
            " I could not reach the router, so those distances are straight lines "
            "and the real journey will be longer."
        )
    return f"{head}\n{sub} {unread}"


ROUTES: tuple[Route, ...] = (
    Route(
        "attachment",
        re.compile(r"receipt|scanned|photo|this bill|heard|voice note", re.I),
        ("inspect_attachment", "calculate_safe_to_spend"),
        arguments=lambda text, attachment: {
            "inspect_attachment": {},
            "calculate_safe_to_spend": _afford_args(text, attachment),
        },
        compose=_compose_attachment,
    ),
    Route(
        "remember",
        re.compile(r"\bremember\b|from now on|always tell me|never suggest", re.I),
        ("remember",),
        arguments=lambda text, attachment: {
            "remember": {
                "kind": "preference",
                "subject": "stated preference",
                "fact": _stated(text),
                "confidence": 95,
            }
        },
        compose=_compose_remember,
    ),
    Route(
        "overspend",
        re.compile(r"overspent|overspend|blew|over budget|went over", re.I),
        ("get_financial_snapshot", "list_activity"),
        compose=_compose_overspend,
    ),
    Route(
        "afford",
        re.compile(r"afford|can i (?:spend|get|buy|have)|enough for", re.I),
        ("calculate_safe_to_spend",),
        arguments=lambda text, attachment: {
            "calculate_safe_to_spend": _afford_args(text, attachment)
        },
        compose=_compose_afford,
    ),
    # After "afford", so a question naming an amount still gets tested against
    # today's room rather than answered with a list of restaurants.
    Route(
        "places",
        re.compile(
            r"where.*(?:eat|lunch|dinner|breakfast|food|makan)"
            r"|(?:somewhere|place|places|spot)s? to eat"
            r"|what can i eat|where should i (?:eat|go)|makan|hungry"
            r"|(?:eat|food|lunch|dinner).*(?:nearby|near me|around here)"
            # Nobody asks about halal except about food, and "somewhere halal
            # under RM15" otherwise fell through to the balance.
            r"|\bhalal\b"
            rf"|{_CRAVING}",
            re.I,
        ),
        ("build_day_plan",),
        arguments=lambda text, attachment: {"build_day_plan": _places_args(text)},
        compose=_compose_places,
    ),
    Route(
        "drop",
        re.compile(r"why (?:did|is|has)|drop|dropped|went down|fell|lower than", re.I),
        ("get_financial_snapshot", "list_activity"),
        compose=_compose_drop,
    ),
    Route(
        "goals",
        re.compile(r"goal|wedding|saving|emergency fund|on track", re.I),
        ("list_goals",),
        compose=_compose_goals,
    ),
    Route(
        "bills",
        re.compile(r"bill|rent|due|commitment|instal", re.I),
        ("list_commitments",),
        compose=_compose_bills,
    ),
    Route(
        "snapshot",
        re.compile(r".", re.S),
        ("get_financial_snapshot", "list_activity"),
        compose=_compose_snapshot,
    ),
)


# The one route that reads a message in the light of the one before it. Held by
# identity rather than by index, so a route inserted anywhere above it moves
# nothing here.
_PLACES = next(route for route in ROUTES if route.name == "places")

# How ``prompt.history_block`` writes the user's half of the conversation. The
# graph runs one checkpointed thread per turn, so by the time this turn starts
# the previous turn's messages are gone; that rendered history is what is left
# of them, and it is also the record the user can read.
_USER_SAID = "User: "


def _following_food(history: str) -> bool:
    """Whether the conversation was already about somewhere to eat.

    Folded forward over the user's turns rather than read off the last one
    alone, so a run of follow-ups keeps its footing: "I feel like japanese",
    "or korean", "italian then" is three turns about food and only the first of
    them says so in words. A turn about anything else ends the run, which is
    the point — a bare kind word means dinner because of what came before it,
    and there is nothing else here that could tell.
    """
    about = False
    for line in history.splitlines():
        if not line.startswith(_USER_SAID):
            continue
        said = line[len(_USER_SAID) :]
        # Each earlier turn is read on its own, with no history of its own to
        # lean on. That is also what stops this recurring: the call below can
        # reach `_following_food` again, but only ever with an empty history,
        # which returns straight back.
        about = route_for(said) is _PLACES or (about and _bare_kind(said) is not None)
    return about


def route_for(text: str, attachment: dict[str, Any] | None = None, history: str = "") -> Route:
    """Which route one message takes, read in the light of the turn before it.

    `history` is the conversation as `prompt.history_block` rendered it, and
    only the places route looks at it. Empty is the honest default rather than
    a convenience: a caller with no history is asking what a sentence means on
    its own, and that is the question it gets answered.
    """
    if attachment:
        return ROUTES[0]
    for route in ROUTES:
        if route.pattern.search(text):
            return route
        # A follow-up naming only a food — "what about japanese instead" — says
        # nothing a pattern can catch, and says everything once you know the
        # last turn was about where to eat. Asked at the places route's own
        # place in the order, so a question about money is still about money.
        if route is _PLACES and _bare_kind(text) and _following_food(history):
            return route
    return ROUTES[-1]


class OfflineChatModel(BaseChatModel):
    """A deterministic stand-in that emits real tool calls and real prose.

    It is not a mock in the test sense: the graph runs unmodified against it,
    which is what makes the golden conversation tests worth having.
    """

    bound_tools: list[str] = []
    attachment: dict[str, Any] | None = None
    # The conversation so far, as the system prompt renders it. Carried on the
    # model rather than read out of the messages because the graph checkpoints
    # one thread per turn: what is in `messages` is this turn and nothing else.
    history: str = ""

    @property
    def _llm_type(self) -> str:
        return "kira-offline"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> BaseChatModel:
        names = []
        for tool in tools:
            if isinstance(tool, dict):
                names.append(tool.get("function", {}).get("name") or tool.get("name", ""))
            else:
                names.append(getattr(tool, "name", ""))
        return self.model_copy(update={"bound_tools": [name for name in names if name]})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = _last_human(messages)
        route = route_for(text, self.attachment, self.history)

        # No tools bound means this is the composition turn: write the answer.
        if not self.bound_tools:
            answer = (route.compose or _compose_snapshot)(messages, text)
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=answer))])

        # Tools already ran this turn; the model has what it asked for.
        if any(isinstance(message, ToolMessage) for message in messages):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])

        arguments = route.arguments(text, self.attachment) if route.arguments else {}
        calls = [
            {
                "name": name,
                "args": arguments.get(name, {}),
                "id": f"offline-{route.name}-{index}",
                "type": "tool_call",
            }
            for index, name in enumerate(route.tools)
            if name in self.bound_tools
        ]
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="", tool_calls=calls))]
        )


# ── choosing one ──────────────────────────────────────────────────────────────


def offline_reason() -> str | None:
    """Why the Butler would run offline right now, or None if it would not."""
    settings = get_settings()
    if settings.butler_offline:
        return "BUTLER_OFFLINE is set"
    if not settings.dashscope_api_key:
        return "no DashScope API key is configured"
    return None


def get_chat_model(
    *,
    streaming: bool = False,
    attachment: dict[str, Any] | None = None,
    history: str = "",
) -> BaseChatModel:
    """The model for one call.

    `streaming` is a real distinction, not a preference: DashScope's
    compatibility mode forbids `tools` together with `stream=True`, so the
    reasoning turns bind tools and do not stream, and the composition turn
    streams and binds nothing.

    `history` reaches only the offline model, which routes on it. Online it is
    already in the system prompt, where the model reads it for itself.
    """
    if offline_reason() is not None:
        return OfflineChatModel(attachment=attachment, history=history)

    settings = get_settings()
    from langchain_openai import ChatOpenAI  # imported late; the offline path needs no SDK

    return ChatOpenAI(
        base_url=settings.dashscope_base_url,
        api_key=settings.dashscope_api_key,
        model=settings.butler_model,
        streaming=streaming,
        timeout=settings.butler_request_timeout_seconds,
        max_retries=1,
    )
