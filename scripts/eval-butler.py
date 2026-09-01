"""Does the Butler reach for the right thing? Ask a live model and count.

Run from apps/api:  .venv/bin/python ../../scripts/eval-butler.py
                    .venv/bin/python ../../scripts/eval-butler.py --only places
                    .venv/bin/python ../../scripts/eval-butler.py --repeat 3

The test suite drives the offline stand-in, which is deterministic by
construction: it proves the graph, the guard and the write boundary, and it can
prove nothing at all about selection. Whether "i want eat fried chicken" reaches
the planner is a fact about a particular model on a particular day, and the only
way to know it is to ask.

So this runs on demand, never in CI. It costs money, it needs a key, and a red
result is a finding rather than a broken build. What it is for:

  - deciding whether `insist` can retire. That node exists because a live Qwen
    answered a question about food with no tool call at all. If the reasoning
    turn -- now split off from the voice block, at temperature 0, with the
    planner's 4,792 characters no longer in front of it -- reaches the planner
    on its own across these turns, the node is scaffolding rather than
    structure. `--no-insist` measures exactly that.
  - noticing a model change. A new id behind BUTLER_MODEL is a new set of
    habits, and this is the cheapest way to find out which.

Each case names a turn and what should happen: which capability the Butler
reaches for, and whether the answer is allowed to carry a figure. Nothing here
asserts on wording -- that is what the offline suite pins.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass, field

from kira.agent import run as butler_run
from kira.agent.llm import offline_reason
from kira.config import get_settings
from kira.db.models import ButlerMessage
from kira.db.session import get_sessionmaker
from kira.seed.demo import DEMO_TODAY, seed_demo_user
from kira.services.butler_thread import ensure_thread
from sqlalchemy import delete


@dataclass(frozen=True, slots=True)
class Case:
    label: str
    text: str
    # Every one of these must appear in tools_used. A capability the turn also
    # reached for that is not named here is reported but is not a failure:
    # looking something extra up is a judgement call, not a mistake.
    expects: tuple[str, ...] = ()
    # Named for the turns that must NOT reach for something -- a greeting that
    # goes shopping through the ledger is the other half of the same problem.
    forbids: tuple[str, ...] = ()
    group: str = "general"


CASES: tuple[Case, ...] = (
    # ── the planner. The reason `insist` exists. ──────────────────────────────
    Case("plain ask", "Where can I eat nearby today?", ("start_day_planning",), group="places"),
    Case("a craving", "i want eat fried chicken", ("start_day_planning",), group="places"),
    Case("halal only", "somewhere halal under RM15", ("start_day_planning",), group="places"),
    Case("no verb at all", "hungry", ("start_day_planning",), group="places"),
    Case("a kind, no ask", "japanese?", ("start_day_planning",), group="places"),
    # ── the goal specialist ───────────────────────────────────────────────────
    Case(
        "a new goal",
        "I want RM1,000 for a Penang trip by December 2026. I already saved RM200.",
        ("start_goal_planning",),
        group="goals",
    ),
    Case(
        "a purchase against a goal",
        "Would buying a RM600 phone hurt my house goal?",
        ("start_goal_planning",),
        group="goals",
    ),
    Case(
        "progress is a read, not a handoff",
        "how are my goals doing?",
        ("list_goals",),
        forbids=("start_goal_planning",),
        group="goals",
    ),
    # ── ordinary reads ────────────────────────────────────────────────────────
    Case("today", "how much can I spend today?", ("calculate_safe_to_spend",), group="money"),
    Case("bills", "what bills are coming up?", ("list_commitments",), group="money"),
    Case("logging", "I spent RM12 on lunch at the mamak", ("add_transaction",), group="money"),
    Case(
        "logging with no amount",
        "I bought lunch at the mamak",
        forbids=("add_transaction",),
        group="money",
    ),
    # ── chaining. The whole point of closing the loop. ────────────────────────
    Case(
        "two questions in one",
        "Somewhere cheap for dinner — and does it hurt my house goal?",
        ("start_day_planning", "start_goal_planning"),
        group="chain",
    ),
    # ── turns that are not questions about money ──────────────────────────────
    Case("a greeting", "hey", forbids=("calculate_safe_to_spend",), group="small talk"),
    Case("thanks", "thanks, that helps", group="small talk"),
)


@dataclass
class Outcome:
    case: Case
    used: list[str] = field(default_factory=list)
    answer: str = ""
    seconds: float = 0.0
    error: str = ""

    @property
    def missing(self) -> list[str]:
        return [name for name in self.case.expects if name not in self.used]

    @property
    def forbidden(self) -> list[str]:
        return [name for name in self.case.forbids if name in self.used]

    @property
    def passed(self) -> bool:
        return not self.error and not self.missing and not self.forbidden

    @property
    def extra(self) -> list[str]:
        return [name for name in self.used if name not in self.case.expects]


async def _ask(case: Case) -> Outcome:
    """One turn, against a fresh thread so nothing carries over between cases."""
    outcome = Outcome(case=case)
    started = time.monotonic()
    try:
        async with get_sessionmaker()() as session:
            user = await seed_demo_user(session)
            thread = await ensure_thread(session, user)
            # Cleared before every case. History is real context, and a case
            # that only passes because the one before it warmed the
            # conversation is not measuring what it says it measures.
            await session.execute(
                delete(ButlerMessage).where(ButlerMessage.thread_id == thread.id)
            )
            await session.commit()
            result = await butler_run.run_turn(
                session, user, thread, text=case.text, today=DEMO_TODAY
            )
        outcome.used = list(result.tools_used)
        outcome.answer = result.answer
    # This is a diagnostic runner: report any failed case and keep measuring
    # the rest, rather than making one flaky provider call hide every result.
    except Exception as exc:  # noqa: BLE001
        outcome.error = f"{type(exc).__name__}: {exc}"
    outcome.seconds = time.monotonic() - started
    return outcome


def _report(outcomes: list[Outcome], budget: float) -> int:
    width = max(len(outcome.case.label) for outcome in outcomes)
    group = ""
    for outcome in outcomes:
        if outcome.case.group != group:
            group = outcome.case.group
            print(f"\n{group}")
        mark = "ok  " if outcome.passed else "FAIL"
        over = "!" if outcome.seconds > budget else " "
        print(f"  {mark} {outcome.case.label:<{width}}  {outcome.seconds:5.1f}s{over} "
              f"{', '.join(outcome.used) or '(nothing)'}")
        if outcome.error:
            print(f"       raised {outcome.error}")
        if outcome.missing:
            print(f"       never reached {', '.join(outcome.missing)}")
        if outcome.forbidden:
            print(f"       should not have reached {', '.join(outcome.forbidden)}")

    passed = sum(1 for outcome in outcomes if outcome.passed)
    slow = sum(1 for outcome in outcomes if outcome.seconds > budget)
    slowest = max(outcome.seconds for outcome in outcomes)
    print(f"\n{passed}/{len(outcomes)} reached what they should.")
    print(f"slowest {slowest:.1f}s; {slow} over the {budget:g}s budget.")
    return 0 if passed == len(outcomes) else 1


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="run one group: places, goals, money, chain, small talk")
    parser.add_argument("--repeat", type=int, default=1, help="ask each turn N times")
    parser.add_argument(
        "--no-insist",
        action="store_true",
        help="stand the insist node down, to see what the model reaches for unaided",
    )
    options = parser.parse_args()

    reason = offline_reason()
    if reason is not None:
        print(f"OFFLINE — {reason}.")
        print("This measures a live model's choices. There is nothing here to measure.")
        return 2

    settings = get_settings()
    print(f"model   : {settings.butler_model} (fallback {settings.butler_fallback_model})")
    print(f"reasoning temperature {settings.butler_reasoning_temperature}, "
          f"budget {settings.butler_turn_budget_seconds:g}s")

    if options.no_insist:
        # Patched rather than configured: standing the node down is a
        # measurement, not a setting anyone should be able to ship.
        from kira.agent.nodes import insist as insist_node

        async def stand_down(_state, _runtime):
            return {}

        insist_node.insist.__code__ = stand_down.__code__
        print("insist   : stood down — measuring the model unaided")

    cases = [case for case in CASES if not options.only or case.group == options.only]
    if not cases:
        print(f"No cases in group {options.only!r}.")
        return 2

    outcomes: list[Outcome] = []
    for _ in range(options.repeat):
        for case in cases:
            outcomes.append(await _ask(case))

    return _report(outcomes, settings.butler_turn_budget_seconds)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
