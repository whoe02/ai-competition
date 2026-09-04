"""The planner as a specialist: what it chooses, and what it cannot say.

The search underneath is unchanged and tested in `test_day_plan_tool`. What is
new is the turn on top of it — the one that picks — and the property that makes
the turn safe: it returns an id, and Python resolves the name.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from kira.agent.agents.day_plan import (
    PlaceChoice,
    _choice_rows,
    _findings,
    _selection_block,
    run_day_plan_agent,
)
from kira.agent.tools import REGISTRY
from kira.agent.tools.day_plan import DayPlanIntent
from kira.agent.tools.spec import AgentContext, ToolContext
from kira.services.dashboard import today_dashboard
from kira.services.snapshot import load_snapshot


class Picker:
    """A model whose structured output is exactly the choice a test names."""

    def __init__(self, choice, *, refuses: bool = False):
        self.choice, self.refuses, self.asked = choice, refuses, []

    def with_structured_output(self, _schema, **_kwargs):
        if self.refuses:
            raise NotImplementedError("no structured output here")
        return self

    async def ainvoke(self, conversation, **_kwargs):
        self.asked.append(conversation)
        return self.choice


async def _context(session, user, today) -> ToolContext:
    return ToolContext(
        session=session,
        user=user,
        today=today,
        snapshot=await load_snapshot(session, user, today),
        dashboard=await today_dashboard(session, user, today),
    )


async def _run(session, user, today, picker, place_world, **fields):
    tools = await _context(session, user, today)
    ctx = AgentContext(
        tools=tools,
        thread_id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        model_factory=(lambda **_: picker) if picker is not None else None,
    )
    intent = DayPlanIntent(request="somewhere for lunch", **place_world.origin, **fields)
    return await run_day_plan_agent(ctx, intent)


class TestTheRegistryEntry:
    def test_the_planner_is_a_specialist_now(self):
        spec = REGISTRY.get("start_day_planning")
        assert spec.kind == "workflow"
        assert spec.agent is not None

    def test_it_carries_the_users_own_sentence(self):
        assert "request" in DayPlanIntent.model_fields
        assert issubclass(DayPlanIntent, BaseModel)


class TestWhatItReports:
    async def test_the_chosen_place_comes_back_resolved(
        self, session, butler, today, place_world
    ):
        user, _ = butler
        cheapest = place_world.cheap
        picker = Picker(
            PlaceChoice(place_id=cheapest.id, reason="it leaves room for the rest of the day")
        )
        report = await _run(session, user, today, picker, place_world)

        assert report.findings["recommendation"]["name"] == cheapest.name
        assert report.findings["recommendation"]["reason"].startswith("it leaves room")
        assert report.llm_calls == 1

    async def test_the_search_payload_is_carried_through_whole(
        self, session, butler, today, place_world
    ):
        # The Butler answers from this, and offline the deterministic composer
        # reads it directly. Summarising it here would take the figures away
        # from both.
        user, _ = butler
        picker = Picker(PlaceChoice(place_id=place_world.cheap.id, reason="cheapest"))
        report = await _run(session, user, today, picker, place_world)

        for key in ("places", "room_sen", "cap_sen", "price_landscape", "near_misses"):
            assert key in report.findings
        # The user's sentence was for the choosing turn, and is not a finding.
        assert "request" not in report.findings

    async def test_an_invented_id_resolves_to_nothing_and_the_cheapest_stands(
        self, session, butler, today, place_world
    ):
        # "Sushi Tei (Mid Valley Megamall), RM42", expressed as an id. There is
        # no such row, so there is no such name to put in the report.
        user, _ = butler
        picker = Picker(PlaceChoice(place_id="sushi-tei-mid-valley", reason="it looked good"))
        report = await _run(session, user, today, picker, place_world)

        assert report.findings["recommendation"]["name"] == place_world.cheap.name
        assert "Sushi" not in str(report.findings["recommendation"])

    async def test_a_model_that_cannot_choose_still_produces_a_recommendation(
        self, session, butler, today, place_world
    ):
        user, _ = butler
        report = await _run(session, user, today, Picker(None, refuses=True), place_world)

        assert report.llm_calls == 0
        assert report.findings["recommendation"]["name"] == place_world.cheap.name
        assert report.findings["recommendation"]["reason"] == (
            "the cheapest whole outing in range"
        )

    async def test_the_evidence_is_the_searchs_own_rows(
        self, session, butler, today, place_world
    ):
        user, _ = butler
        picker = Picker(PlaceChoice(place_id=place_world.cheap.id, reason="cheapest"))
        report = await _run(session, user, today, picker, place_world)
        labels = [row.label for row in report.evidence]

        assert "Safe to spend today" in labels
        assert "Cheapest nearby" in labels


class TestTheOneThingItMayKnowBetterThanTheData:
    def test_a_vouched_for_place_gets_its_own_labelled_row(self):
        found = {"m-1": {"id": "m-1", "name": "McDonald's", "kind": "Burgers", "total_sen": 1800}}
        chosen = PlaceChoice(
            place_id="m-1",
            reason="closest",
            also_consider_id="m-1",
            also_consider_reason="it does fried chicken too",
        )
        (row,) = _choice_rows(chosen, found, "MYR")

        # Labelled as Kira's suggestion, so the row underneath still saying
        # Burgers reads as the record rather than as a contradiction.
        assert row.label == "Kira also suggests"
        assert "McDonald's at RM18.00" in row.value
        assert "fried chicken" in row.value

    def test_a_suggestion_with_no_reason_earns_no_row(self):
        found = {"m-1": {"id": "m-1", "name": "McDonald's", "kind": "Burgers", "total_sen": 1800}}
        chosen = PlaceChoice(place_id="m-1", reason="closest", also_consider_id="m-1")
        assert _choice_rows(chosen, found, "MYR") == ()

    def test_a_suggestion_about_a_place_that_was_not_returned_earns_no_row(self):
        chosen = PlaceChoice(
            place_id="m-1",
            reason="closest",
            also_consider_id="somewhere-invented",
            also_consider_reason="I am sure it does chicken",
        )
        assert _choice_rows(chosen, {}, "MYR") == ()

    def test_the_recorded_kind_travels_with_the_suggestion(self):
        found = {"m-1": {"id": "m-1", "name": "McDonald's", "kind": "Burgers", "total_sen": 1800}}
        chosen = PlaceChoice(
            place_id="m-1",
            reason="closest",
            also_consider_id="m-1",
            also_consider_reason="it does fried chicken",
        )
        payload = {"places": [], "nearest_over_cap": [], "near_misses": []}
        findings = _findings(payload, chosen, None, found)

        # The claim is the model's and the category stays the data's, side by
        # side, so the Butler writing from this cannot merge the two.
        assert findings["also_consider"]["recorded_kind"] == "Burgers"
        assert findings["also_consider"]["suggestion"] == "it does fried chicken"


class TestWhatTheChoosingTurnIsShown:
    def test_it_is_given_ids_prices_and_kinds_and_no_instructions_to_answer(self):
        block = _selection_block(
            {
                "room_sen": 5000,
                "cap_sen": 1500,
                "kind": "Noodles",
                "places": [
                    {"id": "a-1", "name": "Kopi Kaki", "kind": "Mamak", "total_sen": 1150,
                     "km": 0.4}
                ],
                "nearest_over_cap": [],
                "near_misses": [],
                "price_landscape": [{"kind": "Mamak", "count": 3, "cheapest_total_sen": 1100}],
            },
            "MYR",
        )

        assert "a-1: Kopi Kaki · Mamak · RM11.50 · 0.4 km" in block
        assert "Today's room: RM50.00" in block
        assert "Kind asked for: Noodles" in block
        assert "Mamak: 3 in range, cheapest whole outing RM11.00" in block

    def test_an_empty_list_says_so_rather_than_showing_nothing(self):
        block = _selection_block(
            {
                "room_sen": 1000,
                "cap_sen": 1000,
                "kind": None,
                "places": [],
                "nearest_over_cap": [
                    {"id": "o-1", "name": "Kopi Kaki", "kind": "Mamak", "total_sen": 1150,
                     "km": 0.4}
                ],
                "near_misses": [],
                "price_landscape": [],
            },
            "MYR",
        )

        assert "Nothing came in under the ceiling." in block
        assert "Closest above the ceiling:" in block
        assert "o-1: Kopi Kaki" in block

    def test_places_outside_the_radius_are_labelled_as_outside_it(self):
        # The block is what the choosing turn reads. A group headed like any
        # other list would have it recommending a place twice as far away as
        # was asked for, with nothing on the page to say so.
        block = _selection_block(
            {
                "room_sen": 5000,
                "cap_sen": 5000,
                "kind": "Western",
                "places": [
                    {"id": "a-1", "name": "Barat Dekat", "kind": "Western",
                     "total_sen": 1800, "km": 2.0}
                ],
                "nearest_over_cap": [],
                "nearest_beyond_radius": [
                    {"id": "f-1", "name": "Barat Jauh", "kind": "Western",
                     "total_sen": 1900, "km": 5.1}
                ],
                "near_misses": [],
                "price_landscape": [],
            },
            "MYR",
        )

        assert "Outside the search radius — further away than was asked for:" in block
        assert "f-1: Barat Jauh · Western · RM19.00 · 5.1 km" in block

    def test_a_search_that_reached_nowhere_says_nothing_about_the_radius(self):
        block = _selection_block(
            {
                "room_sen": 5000,
                "cap_sen": 5000,
                "kind": None,
                "places": [
                    {"id": "a-1", "name": "Kopi Kaki", "kind": "Mamak",
                     "total_sen": 1150, "km": 0.4}
                ],
                "nearest_over_cap": [],
                "nearest_beyond_radius": [],
                "near_misses": [],
                "price_landscape": [],
            },
            "MYR",
        )

        assert "Outside the search radius" not in block
