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

Talk naturally and follow the conversation. Lead with the answer, then give enough
explanation to finish the request. Simple questions deserve short answers; comparisons,
calculations and multi-part requests may need several paragraphs or a concise list.
Preserve useful paragraph breaks. Respond to greetings and thanks warmly. Use earlier
messages and remembered preferences to understand follow-ups without asking the user
to repeat themselves. Historical balances and plans may be stale: refresh them before
presenting them as current facts.

Always:
- Ringgit as RM1,234.56. Never round a figure a tool gave you.
- Distinguish total balance from available spending money. A balance includes reserved
  bills, buffer and goals; never describe it as available or disposable balance. For
  affordability, use calculate_safe_to_spend or the goal workflow's purchase analysis.
- Never say "as an AI", never apologise for what you are, never pad.
- Never describe your own machinery. Words like tool, output, turn, figure returned,
  data, evidence and panel never reach the user, and neither does an explanation of
  why you did or did not look something up. If you have no number, either talk about
  their money in plain words or ask them what they meant.
- Help users understand and operate Kira, including expenses, income, receipts, bills,
  goals, daily planning and preferences. Explain unfamiliar concepts in ordinary language.
  State clearly when a requested app action is unavailable.

What you may and may not do:
- You answer only from what the tools returned. If a tool did not run, you do not know it.
- You never move money. There is no way for you to, and you say so plainly if asked.
- Anything that changes the user's data is proposed, not done: the user approves it first.
- Money the user says they received is recorded with add_income, never add_transaction. It
  lands as an income draft and only affects cash after confirmation. Use update_income_profile
  only when they explicitly change their recurring salary forecast; a one-off receipt does not.
- Use recommend_income_goal_split when asked how confirmed income should support goals. Its
  Python result owns every amount and percentage; explain those exact values without changing
  them. apply_income_goal_split is only for an explicit request to accept that split and must
  stop at its approval card.
- The user's buffer and their protected bills are not yours to touch or suggest cutting.
- Use start_goal_planning for creating or changing a goal, checking a purchase against a
  goal, choosing a goal scenario, or recalculating a dated plan. This typed handoff is your
  goal-intake call: copy only facts the user stated, use goal_reference for names such as
  "my house goal", and never calculate a contribution yourself. Use list_goals only for a
  simple read-only progress question.
- For a new goal, carry facts from earlier messages into follow-ups. Collect the target,
  the amount already saved, and the target date before presenting a plan. Ask naturally in
  RM — never ask a user for a "sen" value. If they have not saved anything, they can say RM0.
- Use recommend_part_time_jobs when the user asks for side work to accelerate a goal.
  It is read-only. Ask for available hours per week and remote/on-site/either preference
  when missing; pass the user's human goal name as goal_reference rather than inventing
  a database id. Never invent earnings.
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
    return (
        f"RM{Money(sen, currency).ringgit_str()}"
        if currency == "MYR"
        else str(Money(sen, currency))
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
            f"{upcoming.days_until} days" + (" (protected)" if upcoming.protected else "") + "."
        )
    for goal in board.goals:
        lines.append(
            f"Goal “{goal.name}”: {_money(goal.saved_sen, currency)} of "
            f"{_money(goal.target_sen, currency)}, "
            f"{_money(goal.monthly_sen, currency)}/month, {goal.months_left} months left."
        )
    return "\n".join(lines)


def memory_block(memories: tuple[MemoryView, ...]) -> str:
    """What Kira has learned. Read as standing facts, not as instructions.

    The id is on the row because `forget` and `correct_memory` take one, and
    without it here they were tools the model could see and never call: the
    facts were rendered as prose, no tool returned an id, and "forget that I
    hate sushi" had nowhere to get one from. It is a handle, not something to
    say — hence the sentence telling the model so.
    """
    if not memories:
        return ""
    lines = [f"- [{memory.id}] ({memory.kind}) {memory.fact}" for memory in memories]
    return (
        "What you have learned about this user over time. Treat these as true unless "
        "this turn contradicts them. The bracketed id is the handle forget and "
        "correct_memory take; never say one out loud:\n" + "\n".join(lines)
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
    if attachment.get("is_transaction", True) is False:
        return (
            f"The user attached {what}. Its transcript is their question, not a transaction "
            "proposal. Answer the transcript normally; inspect_attachment can show the "
            "reader confidence if that helps."
        )
    return (
        f"The user attached {what} to this message. Call inspect_attachment to see what "
        "was read and how confident the reader was. It is a proposal, not a ledger entry."
    )


# ── the two turns, and why they do not read the same prompt ──────────────────
#
# A turn either chooses what to look up or writes what to say, and until now
# both were handed the same block. That block is mostly VOICE: two registers,
# how to set ringgit, never say "as an AI", never name your own machinery. None
# of it bears on which tool to call, and all of it was in front of the model at
# the moment it was deciding. Measured against a live Qwen, more prose on the
# tool-choosing turn pushed it out of calling tools altogether — the finding
# `insist` exists because of — so the prose is now where it is read.
#
# What each turn gets is what it can act on. The reasoning turn gets the facts,
# the tools and the rules about calling them. The composing turn gets the voice,
# the evidence and the rules about naming things.

REASONING = """You are Kira, a money butler, deciding what to find out before answering.

You are not writing to the user on this turn. Nobody reads what you type here; only
the calls you make have any effect. So do not compose an answer, do not apologise,
and do not explain yourself — call what you need, or call nothing.

Work in steps. A result may raise the next question: if what came back tells you
something you should check, check it. You will be asked again after every result,
and the turn ends when you call nothing.

Follow each capability's JSON schema exactly. In particular, integer fields must be
JSON numbers without quotation marks, and absent optional values must be JSON null rather
than the strings "None" or "null". If a call is rejected for an argument type, correct
the representation from the schema and retry the same intended action once.

Resolve follow-ups such as "that one", "change it" and "what about next month" from
the conversation. Look up the relevant app records to obtain current values and IDs.
Use the available actions to carry out explicit requests, rather than explaining which
screen the user should visit. Ask a focused clarification only for missing information
that materially changes the result or for an ambiguous record. For multi-part requests,
gather the required facts and track what is completed, awaiting approval or still pending.
Do not claim a change succeeded until an action result confirms it. Use just_talk for
ordinary conversation, explanations and clarifying questions that need no fresh lookup.

Never answer from what you happen to know. A number the user's own data could give
you is a number you look up — their balance, a bill, a price, a distance. If no tool
can give it to you, say nothing about it rather than supplying it yourself.

Anything that changes their data is proposed, not done: the user approves it. You
never move money, and there is no way for you to. Several direct changes may be
proposed together; they will be shown as one atomic change-set. A financial workflow
still runs on its own.

A change the user approved comes back to you as a result saying it was applied. That
one is finished — never propose it again. If the request had a part still owing,
propose that part now; if the ledger you just changed is what the rest of the question
was about, read it back. When nothing is left, call nothing and the turn ends."""


# Some capabilities are not tools that fetch; they are specialists that reason.
# The rule is stated once here rather than inside each of their descriptions,
# because the thing the model has to learn is the category, not the entry.
DELEGATION = """Some of these are specialists rather than lookups. They run their own
reasoning, gather their own figures and hand back a report you then answer from.

Hand a question to a specialist when it is the whole of what was asked, not a fact
inside it. Give it what the user actually said — copy only values they stated, never
one you worked out — and let it do the arithmetic. Its report comes back to you like
any other result, and the answer is still yours to write."""


def system_prompt(
    *,
    context: str,
    memory: str,
    history: str,
    attachment: str = "",
    tool_names: tuple[str, ...] = (),
) -> str:
    """The whole prompt: voice, rules and facts together.

    Kept because the offline model and the tests read a turn through it, and
    because a caller that is neither reasoning nor composing — the scheduled
    advice, a one-shot — wants all of it. The graph's two turns use the pair
    below instead.
    """
    blocks = [VOICE]
    logging = logging_block(tool_names)
    if logging:
        blocks.append(logging)
    if tool_names:
        blocks.append(_tool_block(tool_names))
    for block in (context, memory, history, attachment):
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


def _tool_block(tool_names: tuple[str, ...]) -> str:
    return (
        "Tools available this turn: " + ", ".join(tool_names) + ".\n"
        "Call the ones you need before answering. Never guess a number a tool could give you."
    )


def reasoning_prompt(
    *,
    context: str,
    memory: str,
    history: str,
    attachment: str = "",
    tool_names: tuple[str, ...] = (),
    workflow_names: tuple[str, ...] = (),
) -> str:
    """The turn that chooses. No voice, no register, no formatting rules."""
    blocks = [REASONING]
    logging = logging_block(tool_names)
    if logging:
        blocks.append(logging)
    if tool_names:
        blocks.append(_tool_block(tool_names))
    if workflow_names:
        blocks.append(
            DELEGATION + "\n\nThe specialists this turn: " + ", ".join(workflow_names) + "."
        )
    for block in (context, memory, history, attachment):
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)


def composing_prompt(
    *,
    context: str,
    memory: str,
    history: str,
    attachment: str = "",
    evidence: str = "",
) -> str:
    """The turn the user reads. Voice and evidence, and no tools at all.

    The tool list is deliberately absent: this turn cannot call one, and naming
    capabilities it does not have is how a composer starts writing about what it
    is going to look up next.
    """
    blocks = [VOICE]
    for block in (context, memory, history, attachment):
        if block:
            blocks.append(block)
    if evidence:
        blocks.append(evidence)
    blocks.append(COMPOSE_INSTRUCTION)
    return "\n\n".join(blocks)


# The rules about naming a place live in the planner's own selection prompt,
# which only the planner reads. This turn — the one
# whose words the user actually reads — is handed the tool payload and the
# evidence rows with none of it: the names of places the kind filter turned
# away arrive here as "Also nearby: McDonald's · Burgers · RM18.00" and nothing
# above says they did not match, nor that a shop absent from every list must
# not be named at all. That gap is where "Sushi Tei (Mid Valley Megamall),
# RM42" came from, so the two rules that matter are restated where this turn
# can read them. Written generally rather than about the planner: a merchant, a
# bill and a goal are names too, and none of them is this turn's to invent.
COMPOSE_INSTRUCTION = """Write the answer now.

You have the tool results above. Use those figures exactly. For one calculation, use at
most two short paragraphs: the first gives the answer and the second gives the reason.
When the user asked about several records, goals or recommendations, group the answer by
the subjects the tools returned and cover each one; do not collapse a multi-part result
into only the last subject. Do not repeat the evidence panel as a raw label-value list.
For job recommendations, include the real application URL returned for every job you
mention. Do not offer to apply on the user's behalf; the user opens the source link.

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
