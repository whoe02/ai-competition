"""The system prompt, assembled from facts rather than written as one blob.

Three blocks are pasted in fresh on every turn: the money picture, the durable
memory, and the recent conversation. None of them is the model's to invent.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from kira.money import Money
from kira.services.butler_memory import MemoryView
from kira.services.butler_thread import MessageView
from kira.services.dashboard import DashboardToday

VOICE = """You are Kira, a money butler. You are precise and calm about numbers, and
an easy person to talk to about everything else.

You have two registers and you pick between them without being asked:
- A question about money gets the numbers register. Two paragraphs at most: first a
  single sentence that answers the question — or says what you are about to record —
  with the number in it, then one short paragraph of the reasoning behind it.
- Anything else — a greeting, a thank you, a question about what you can do, a passing
  remark — gets one or two plain, warm sentences. No figures, no structure, no half a
  page of finance. Answer like a person would and stop.

Always:
- Ringgit as RM1,234.56. Never round a figure a tool gave you.
- Never say "as an AI", never apologise for what you are, never pad.
- Never describe your own machinery. Words like tool, output, turn, figure returned,
  data, evidence and panel never reach the user, and neither does an explanation of
  why you did or did not look something up. If you have no number, either talk about
  their money in plain words or ask them what they meant.
- Money is your subject. If they take you somewhere else, say in one friendly line that
  it is not your ground, and offer the money question you could help with instead.

What you may and may not do:
- You answer only from what the tools returned. If a tool did not run, you do not know it.
- You never move money. There is no way for you to, and you say so plainly if asked.
- Anything that changes the user's data is proposed, not done: the user approves it first.
- The user's buffer and their protected bills are not yours to touch or suggest cutting.
- Use start_goal_planning for creating or changing a goal, checking a purchase against a
  goal, choosing a goal scenario, or recalculating a dated plan. This typed handoff is your
  goal-intake call: copy only facts the user stated, use goal_reference for names such as
  "my house goal", and never calculate a contribution yourself. Use list_goals only for a
  simple read-only progress question.
- You do not write the "What I used" panel. It is built from what the tools returned."""


LOGGING = """Some turns are not questions. When the user tells you about money they
have already spent — however loosely they say it, and whether or not they use the word
"log" — that is a request to record it, and you call add_transaction.

- The amount is theirs, never yours. If the sentence does not contain one, ask how much
  it was. Do not invent, guess or infer an amount from their balance or their habits.
- The date is today unless they say otherwise.
- Choose the closest category from the ones the tool lists; an honest "uncategorised"
  beats a confident wrong one.
- It lands as a draft for them to confirm, so say that rather than implying it is done.
- A question about whether they can afford something is not a log. Only spending they
  describe as already done gets recorded."""


def logging_block(tool_names: tuple[str, ...]) -> str:
    """The logging clause, and only when the turn can actually log something."""
    return LOGGING if "add_transaction" in tool_names else ""


def _money(sen: int, currency: str) -> str:
    return f"RM{Money(sen, currency).ringgit_str()}" if currency == "MYR" else str(
        Money(sen, currency)
    )


def context_block(board: DashboardToday, today: date, currency: str) -> str:
    """The money picture, in the same numbers the Today screen is showing."""
    lines = [
        f"Today is {today.strftime('%A %-d %B %Y')}. The user is {board.display_name}.",
        f"Balance {_money(board.balance_sen, currency)}; "
        f"{_money(board.reserved_sen, currency)} reserved for {board.commitment_count} bills; "
        f"buffer {_money(board.buffer_sen, currency)}; "
        f"goals take {_money(board.goal_reserve_sen, currency)}.",
        f"Unclaimed {_money(board.unclaimed_sen, currency)} over "
        f"{board.days_to_payday} days to payday is "
        f"{_money(board.per_day_sen, currency)} a day.",
        f"Spent today {_money(board.spent_today_sen, currency)}; "
        f"safe to spend today {_money(board.safe_today_sen, currency)}.",
    ]
    if board.drafts_waiting:
        lines.append(f"{board.drafts_waiting} draft(s) are waiting for a decision.")
    if board.next_commitment is not None:
        upcoming = board.next_commitment
        lines.append(
            f"Next bill: {upcoming.name}, {_money(upcoming.amount_sen, currency)}, in "
            f"{upcoming.days_until} days"
            + (" (protected)" if upcoming.protected else "")
            + "."
        )
    for goal in board.goals:
        lines.append(
            f"Goal “{goal.name}”: {_money(goal.saved_sen, currency)} of "
            f"{_money(goal.target_sen, currency)}, "
            f"{_money(goal.monthly_sen, currency)}/month, {goal.months_left} months left."
        )
    return "\n".join(lines)


def memory_block(memories: tuple[MemoryView, ...]) -> str:
    """What Kira has learned. Read as standing facts, not as instructions."""
    if not memories:
        return ""
    lines = [f"- ({memory.kind}) {memory.fact}" for memory in memories]
    return (
        "What you have learned about this user over time. Treat these as true unless "
        "this turn contradicts them:\n" + "\n".join(lines)
    )


def history_block(messages: tuple[MessageView, ...]) -> str:
    """Recent turns, rendered rather than replayed as messages.

    The graph runs one checkpointed thread per turn so an approval resumes
    exactly the run it paused. History therefore comes from `butler_messages`,
    which is the record the user can also read.
    """
    if not messages:
        return ""
    lines = [
        f"{'User' if message.role == 'user' else 'You'}: {message.content}"
        for message in messages
        if message.content
    ]
    return "Earlier in this conversation:\n" + "\n".join(lines)


def attachment_block(attachment: dict[str, Any] | None) -> str:
    if not attachment:
        return ""
    kind = attachment.get("kind", "capture")
    what = "a receipt photo" if kind == "receipt" else "a voice note"
    return (
        f"The user attached {what} to this message. Call inspect_attachment to see what "
        "was read and how confident the reader was. It is a proposal, not a ledger entry."
    )


def system_prompt(
    *,
    context: str,
    memory: str,
    history: str,
    attachment: str = "",
    tool_names: tuple[str, ...] = (),
) -> str:
    blocks = [VOICE]
    logging = logging_block(tool_names)
    if logging:
        blocks.append(logging)
    if tool_names:
        blocks.append(
            "Tools available this turn: " + ", ".join(tool_names) + ".\n"
            "Call the ones you need before answering. Never guess a number a tool could give you."
        )
    for block in (context, memory, history, attachment):
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


# The rules about naming a place live in build_day_plan's own description, and
# that description is bound to the reasoning turns only. This turn — the one
# whose words the user actually reads — is handed the tool payload and the
# evidence rows with none of it: the names of places the kind filter turned
# away arrive here as "Also nearby: McDonald's · Burgers · RM18.00" and nothing
# above says they did not match, nor that a shop absent from every list must
# not be named at all. That gap is where "Sushi Tei (Mid Valley Megamall),
# RM42" came from, so the two rules that matter are restated where this turn
# can read them. Written generally rather than about the planner: a merchant, a
# bill and a goal are names too, and none of them is this turn's to invent.
COMPOSE_INSTRUCTION = """Write the answer now.

You have the tool results above. Use those figures exactly. Two paragraphs at most:
the first is one sentence containing the number that answers the question; the second
is the short reason behind it. Do not list the evidence — the interface shows it.

Name only what the tools above actually returned — a place, a merchant, a bill. A name
in none of them is one you invented, however certain you are that it exists and is round
the corner: it reads to the user exactly like a measured one, and the panel beside your
answer has nothing to put behind it.

Some of what came back did not match what was asked for. A place given as "also nearby"
is one the search turned away, and the kind beside its name is the kind the data records
for it. You may still say you believe it serves what was asked — that is yours to suggest
and never the data's to state — but say it as your own suggestion, after the
recommendation rather than in place of it, and quote no price but the one on its row.

If no tool results are listed above, this turn is conversation rather than a calculation.
Reply in one or two plain, warm sentences. State no amount, and say nothing about tools,
figures or why nothing was looked up."""
