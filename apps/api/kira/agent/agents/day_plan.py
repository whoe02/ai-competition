"""The Planner specialist, behind the Butler's `start_day_planning` handoff.

It used to be a tool, and its description was 4,792 characters — two thirds of
the entire schema payload bound to every reasoning turn the Butler took,
whether or not the question was about food. All of it was advice about how to
choose a place and how to talk about one, read by a model that was deciding
between twenty-one tools.

So it is an agent now. The search is the same deterministic call it always was.
What follows it is one model turn whose only job is the choice, and which reads
those rules because they are its rules. What it returns is an id, never a name:
Python looks the place up in the set the search returned, so the invented
restaurant this app has been caught producing twice is not something this path
can express.

The Butler still writes the answer. This reports.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from kira.agent.llm import get_chat_model
from kira.config import get_settings

# `kira.agent.tools.spec` is imported inside the functions below, never at the
# top. The tool module names this agent in its spec, so importing the two the
# other way round -- an agent module first -- would walk back into a
# half-initialised package. Which module a test happens to import first is not
# something this file should be able to break.

MODULE = "day_plan"


class PlaceChoice(BaseModel):
    """One choice out of the set the search returned."""

    place_id: str = Field(
        description=(
            "The id of the one place you recommend, copied from the list. Not its "
            "name and not its position."
        )
    )
    reason: str = Field(
        max_length=300,
        description=(
            "Why that one, in a sentence or two — against today's room, against a "
            "goal, against something the user has had Kira remember. State no "
            "figure: the numbers are added around this from the search."
        ),
    )
    alternative_ids: list[str] = Field(
        default_factory=list,
        max_length=2,
        description="At most two other ids worth mentioning, best first.",
    )
    also_consider_id: str | None = Field(
        default=None,
        description=(
            "Optionally one id from `near_misses` that you believe serves what was "
            "asked for anyway — a global chain whose menu you actually know. Leave "
            "unset for a place you cannot vouch for."
        ),
    )
    also_consider_reason: str = Field(
        default="",
        max_length=160,
        description=(
            "Why you believe that one serves it, as your own suggestion. Empty "
            "unless also_consider_id is set."
        ),
    )


SELECTION = """You choose one place to eat out of a list that has already been measured.

The search below is done. Every name, price, distance and category in it is real
and none of it is yours to change. Your whole job is to pick one and say why.

Recommend one place. The user asked where to go, so the answer is a name. A count
and a price range — "five halal options from RM13 to RM14" — is not an answer to
where to eat; it is a description of the filter, and reading the whole list back is
the same failure spread over more words.

Why that one is the part worth writing. Weigh it against today's room, against a
goal the user is saving for, and against anything they have had Kira remember. The
places come back cheapest first and only the cheapest dozen come back at all, so
leading with the first one is itself a choice about price: make it on purpose
rather than by reading down from the top.

A remembered preference acts in two places and nowhere else — on the search that has
already run, and on which of these you pick. "I don't like walking far" means the
short journey wins over the cheap one; say so when it does.

`near_misses` is the closest few places the kind filter did NOT match, each with the
kind the data really gives it. It is there for the one thing you know and the data
does not: what a place actually serves. The kinds come from OpenStreetMap, which
records one word per place and no menu — it calls McDonald's burgers and stops, so a
search for chicken finds KFC and says nothing about the McDonald's across the road.

Point at one of those only where your knowledge is actually good. A global chain —
McDonald's, KFC, Starbucks, Subway — you can be confident about. "Restoran MK Corner"
you cannot: you have no idea what is on its menu, and a guess dressed as knowledge
sends someone across town on the strength of a name. Say nothing about the ones you
do not know, and put nothing in `also_consider_id` unless you would stand behind it.

`nearest_over_cap` appears only when nothing at all came in under the ceiling, and it
is the closest few places above it. Choose the first one and say how far over it is —
"nothing under RM10, and the closest is RM11.50" is an answer; an apology is not.
Never present one as fitting, and never count it among the places that did.

`price_landscape` is every kind of food in range with the cheapest whole outing of
each, whatever the ceiling and whatever kind was asked for. Read it before you settle
for nothing, and let it shape your reason: what the money does reach is more use than
what it does not. Its rows are prices, not places — there is no id in one, so nothing
in it is choosable.

Every field you return is an id out of the lists below, or a sentence with no figure
in it. You cannot name a place and you cannot quote a price: both are read back out
of the search from the id you give, which is what makes an invented restaurant
impossible here rather than merely discouraged."""


def _lines(rows: list[dict[str, Any]], currency: str) -> str:
    from kira.agent.tools.spec import money_str
    from kira.money import Money

    return "\n".join(
        f"- {row['id']}: {row['name']} · {row['kind']} · "
        f"{money_str(Money(row['total_sen'], currency))} · {row['km']:.1f} km"
        for row in rows
    )


def _selection_block(payload: dict[str, Any], currency: str) -> str:
    from kira.agent.tools.spec import money_str
    from kira.money import Money

    def money(sen: int) -> str:
        return money_str(Money(sen, currency))

    blocks = [
        f"Today's room: {money(payload['room_sen'])}. "
        f"Ceiling applied: {money(payload['cap_sen'])}."
        + (f" Kind asked for: {payload['kind']}." if payload.get("kind") else "")
    ]
    if payload["places"]:
        blocks.append(
            "Places under the ceiling, cheapest first:\n"
            + _lines(payload["places"], currency)
        )
    else:
        blocks.append("Nothing came in under the ceiling.")
    if payload["nearest_over_cap"]:
        blocks.append(
            "Closest above the ceiling:\n" + _lines(payload["nearest_over_cap"], currency)
        )
    if payload["near_misses"]:
        blocks.append(
            "near_misses — the kind filter turned these away:\n"
            + _lines(payload["near_misses"], currency)
        )
    if payload["price_landscape"]:
        blocks.append(
            "What the money reaches, by kind:\n"
            + "\n".join(
                f"- {row['kind']}: {row['count']} in range, cheapest whole outing "
                f"{money(row['cheapest_total_sen'])}"
                for row in payload["price_landscape"]
            )
        )
    return "\n\n".join(blocks)


def _by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every place the search returned, in one lookup. The only source of names."""
    found: dict[str, dict[str, Any]] = {}
    for key in ("places", "nearest_over_cap", "near_misses"):
        for row in payload.get(key) or []:
            found[row["id"]] = row
    return found


async def _choose(ctx, payload: dict[str, Any]) -> PlaceChoice | None:
    """One model turn, bounded, and worth nothing if it misses.

    A failed choice is not a failed turn: the search stands, the cheapest place
    is a defensible recommendation, and `_report` falls back to it. So this is
    allowed to be the fast, cheap, occasionally-unavailable half.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    factory = ctx.model_factory
    model = factory(streaming=False) if factory is not None else get_chat_model(
        streaming=False, temperature=get_settings().butler_reasoning_temperature
    )
    try:
        picker = model.with_structured_output(PlaceChoice)
    except (NotImplementedError, AttributeError):
        # The offline stand-in has no structured output and no opinion. The
        # deterministic fallback below is exactly what it would have said.
        return None

    conversation = [
        SystemMessage(SELECTION),
        HumanMessage(
            f"{_selection_block(payload, ctx.currency)}\n\n"
            f"What they asked for: {payload.get('request') or 'somewhere to eat'}"
        ),
    ]
    try:
        async with asyncio.timeout(get_settings().day_plan_choose_timeout_seconds):
            chosen = await picker.ainvoke(conversation)
    except Exception:
        return None
    return chosen if isinstance(chosen, PlaceChoice) else None


def _named(found: dict[str, dict[str, Any]], place_id: str | None) -> dict[str, Any] | None:
    return found.get(place_id) if place_id else None


async def run_day_plan_agent(ctx, intent):
    from kira.agent.tools.day_plan import PlanArgs, run_search
    from kira.agent.tools.spec import AgentReport

    args = PlanArgs.model_validate(intent.model_dump(exclude={"request"}))
    ctx.emit("thinking", text="Checking what is actually near you")
    searched = await run_search(ctx.tools, args)
    payload = dict(searched.value)
    payload["request"] = getattr(intent, "request", "")

    found = _by_id(payload)
    chosen = await _choose(ctx, payload) if found else None

    pick = _named(found, chosen.place_id if chosen else None)
    if pick is None and payload["places"]:
        # Either no model was reachable or it named an id the search never
        # returned. Cheapest first is the order the service already put them
        # in, so the fallback is a real recommendation rather than an apology.
        pick = payload["places"][0]

    return AgentReport(
        findings=_findings(payload, chosen, pick, found),
        evidence=searched.evidence + _choice_rows(chosen, found, ctx.currency),
        llm_calls=1 if chosen is not None else 0,
    )


def _choice_rows(chosen: PlaceChoice | None, found: dict[str, dict[str, Any]], currency: str):
    """The one row the search cannot produce: a place the planner vouched for.

    Everything else on the panel was measured. This is the suggestion the model
    is allowed to make — that a place tagged burgers also fries chicken — and it
    is labelled as a suggestion so the row beneath it, still saying Burgers, is
    not read as contradicting it.
    """
    from kira.agent.tools.spec import EvidenceRow, money_str
    from kira.money import Money

    if chosen is None or not chosen.also_consider_reason:
        return ()
    other = _named(found, chosen.also_consider_id)
    if other is None:
        return ()
    return (
        EvidenceRow(
            "Kira also suggests",
            f"{other['name']} at {money_str(Money(other['total_sen'], currency))} "
            f"— {chosen.also_consider_reason}",
        ),
    )


def _findings(
    payload: dict[str, Any],
    chosen: PlaceChoice | None,
    pick: dict[str, Any] | None,
    found: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """The report, which is the search plus the choice made over it.

    The whole payload is carried through unchanged because the Butler's answer
    is written from it and the offline composer reads it directly. What is added
    is `recommendation` — a name and a price the planner has already resolved
    from an id, so the Butler has nothing left to pick and nothing to invent.
    """
    findings = dict(payload)
    findings.pop("request", None)
    if pick is not None:
        findings["recommendation"] = {
            "name": pick["name"],
            "kind": pick["kind"],
            "total_sen": pick["total_sen"],
            "id": pick["id"],
            "fits_today": pick.get("band"),
            "reason": chosen.reason if chosen else "the cheapest whole outing in range",
        }
    if chosen is not None:
        findings["alternatives"] = [
            {"name": row["name"], "total_sen": row["total_sen"], "id": row["id"]}
            for identifier in chosen.alternative_ids
            if (row := found.get(identifier)) is not None
        ]
        other = _named(found, chosen.also_consider_id)
        if other is not None and chosen.also_consider_reason:
            findings["also_consider"] = {
                "name": other["name"],
                "recorded_kind": other["kind"],
                "total_sen": other["total_sen"],
                "suggestion": chosen.also_consider_reason,
            }
    return findings
