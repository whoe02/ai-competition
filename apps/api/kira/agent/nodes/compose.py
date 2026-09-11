"""compose — the answer, and the only turn that streams.

No tools are bound here, which is both what DashScope requires for streaming
and what keeps the model from reaching for one more number mid-sentence. The
evidence is already fixed by the time this runs.
"""

from __future__ import annotations

import json
import re

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.runtime import Runtime

from kira.agent import events, prompt
from kira.agent.llm import OfflineChatModel, _last_human, get_chat_model, route_for
from kira.agent.state import ButlerContext, ButlerState
from kira.config import get_settings

FALLBACK = (
    "I could not reach my language model just now.\n"
    "The numbers above are still live and correct — they come from your ledger, not from it."
)

CHAT_FALLBACK = "Hey — what would you like to look at?"

# Said when no tool ran, in place of an answer nothing can vouch for.
NOTHING_RAN = (
    "I didn't look anything up for that, so I'd rather not answer it from memory.\n"
    "Ask me again and I'll check properly — your figures come from your ledger, "
    "never from what I happen to recall."
)


# A model that wants to call a tool on a turn with no tools bound sometimes
# writes the call out as markup instead. Qwen did exactly this on a live turn
# and the user's whole answer was the string "<tool_code>\n</tool_code>" — the
# request it was trying to make disappeared, and what took its place was
# machinery, which is the one thing VOICE says never reaches the user.
#
# Stripped rather than trusted to a prompt rule: three separate instructions not
# to name its own machinery are already in VOICE, and this got through all of
# them. A block is removed whole, because its contents are an attempted call and
# not a sentence; a stray tag on its own is removed and the prose around it kept.
_TOOL_BLOCK = re.compile(
    r"<\s*(tool_code|tool_call|tool_use|function_call)\s*>.*?<\s*/\s*\1\s*>",
    re.I | re.S,
)
_TOOL_TAG = re.compile(r"<\s*/?\s*(?:tool_code|tool_call|tool_use|function_call)\s*>", re.I)
_FENCED_TOOL_CALL = re.compile(
    r"```(?:python|py|json)?\s*"
    r"(?=[^`]*\b(?:start_goal_planning|start_day_planning|control_app|"
    r"[a-z][a-z0-9_]*(?:goal|transaction|commitment|account|profile|memory)[a-z0-9_]*)\s*\()"
    r".*?```",
    re.I | re.S,
)


def _clean(text: str) -> str:
    """The answer with any attempted tool call taken out of it.

    Returning "" when that is all there was is deliberate: every caller already
    treats an empty answer as "this turn produced nothing worth saying" and has
    a fallback for it, and half a leaked call is worse than the fallback.
    """
    return _TOOL_TAG.sub("", _FENCED_TOOL_CALL.sub("", _TOOL_BLOCK.sub("", text))).strip()


def _model(runtime: Runtime[ButlerContext], attachment, history):
    factory = runtime.context.model_factory
    if factory is not None:
        return factory(streaming=True, attachment=attachment, history=history)
    return get_chat_model(
        streaming=True,
        attachment=attachment,
        history=history,
        temperature=get_settings().butler_compose_temperature,
    )


def _evidence_block(rows: list[list[str]]) -> str:
    if not rows:
        return (
            "Nothing was looked up this turn, so treat it as conversation rather than a\n"
            "report. State no amount, and do not mention that nothing was looked up."
        )
    lines = "\n".join(f"- {label}: {value}" for label, value in rows)
    return "These are the figures the tools returned. Use them exactly:\n" + lines


def _part_time_reply(messages: list[object]) -> str | None:
    """Use the verified job-search outcome, never model-written listings.

    The web client renders successful records as a structured table with real
    application buttons. Letting the composer repeat them in prose can turn a
    failed search into plausible but unverified roles and URLs, so both success
    and failure have a short source-derived response here instead.
    """
    for message in reversed(messages):
        if not isinstance(message, ToolMessage) or message.name != "recommend_part_time_jobs":
            continue
        try:
            value = json.loads(message.content) if isinstance(message.content, str) else None
        except json.JSONDecodeError:
            return "I couldn’t read the live work-search result. Please try again."
        if not isinstance(value, dict):
            return "I couldn’t read the live work-search result. Please try again."

        goal_name = value.get("goal_name")
        goal = goal_name if isinstance(goal_name, str) and goal_name.strip() else "your goal"
        recommendations = value.get("recommendations")
        if (
            value.get("status") == "available"
            and isinstance(recommendations, list)
            and recommendations
        ):
            # The rich listing panel is the response the user needs. This text
            # remains in the transcript for accessibility, but the client
            # deliberately suppresses it beside that panel.
            return f"Verified live work ideas for {goal}."

        if value.get("status") == "needs_input":
            missing = {
                field for field in value.get("missing_fields", []) if isinstance(field, str)
            }
            questions: list[str] = []
            if "goal_reference" in missing:
                questions.append("which goal you want to accelerate")
            if "available_hours_per_week" in missing:
                questions.append("how many hours you can work each week")
            if "work_mode" in missing:
                questions.append("whether you prefer remote, on-site, or either")
            if questions:
                requested = ", ".join(questions[:-1])
                requested = f"{requested} and {questions[-1]}" if requested else questions[-1]
                return f"To find verified live work ideas, tell me {requested}."

        reason = value.get("reason")
        detail = reason.strip() if isinstance(reason, str) and reason.strip() else (
            "No verified listings matched the current search."
        )
        return (
            f"I couldn’t provide verified live work ideas for {goal} right now. "
            f"{detail} I haven’t listed unverified alternatives."
        )
    return None


async def compose(state: ButlerState, runtime: Runtime[ButlerContext]) -> dict:
    events.emit(runtime, events.THINKING, text="Putting it in words")
    evidence = state.get("evidence") or []
    part_time_reply = _part_time_reply(list(state.get("messages") or []))
    if part_time_reply is not None:
        events.emit(runtime, events.TOKEN, text=part_time_reply)
        return {"answer": part_time_reply, "messages": [AIMessage(content=part_time_reply)]}
    conversation_turn = "just_talk" in (state.get("tools_used") or [])
    system = SystemMessage(
        prompt.composing_prompt(
            # A conversational turn must not see the snapshot it intentionally
            # chose not to read. Otherwise a greeting can repeat a balance the
            # model happened to notice in the context, which is a dashboard in
            # a friendlier voice rather than conversation.
            context="" if conversation_turn else state.get("context_block", ""),
            memory=state.get("memory_block", ""),
            # Withheld when nothing ran. Asked the same question twice, the model
            # read the places and prices out of its own earlier reply and wrote
            # them again having called nothing — prose that looked right above a
            # panel that could vouch for none of it. Three separate instructions
            # not to do that were ignored, so the history is taken away instead:
            # with no tool result to speak from, there is now nothing to copy
            # either, and what is left is the snapshot, which is real. The
            # reasoning turn still sees the whole history, so "add the second
            # one" still knows which one that was.
            history=state.get("history_block", "") if evidence or conversation_turn else "",
            attachment="" if conversation_turn else state.get("attachment_block", ""),
            evidence=_evidence_block(evidence),
        )
    )
    # The instruction goes in the system block rather than as a trailing turn:
    # the last human message must stay the user's question, not ours.
    conversation = [system, *state.get("messages", [])]

    # A specialist answered, and answered in words rather than in figures: a
    # goal request missing its target amount comes back as the question about
    # the target amount, and nothing was calculated because nothing could be.
    # There is no evidence to compose from, and the child's sentence is already
    # the honest answer — so it stands as written rather than being paraphrased
    # by a turn that would have to invent the grounding to improve on it. This
    # is the same rule as the one below, read the other way round: the Butler
    # writes from the rows, and where there are no rows there is nothing of its
    # own to add.
    reports = state.get("reports") or []
    if not evidence and reports:
        spoken = "\n\n".join(reports)
        events.emit(runtime, events.TOKEN, text=spoken)
        return {"answer": spoken, "messages": [AIMessage(content=spoken)]}

    # Nothing ran, so nobody writes prose about money this turn.
    #
    # Asked for somewhere Japanese having called no tool, the online model
    # answered "Sushi Tei (Mid Valley Megamall)" at RM42 -- a real enough
    # sounding chain, a real enough sounding mall, and no such place in the
    # shipped set, whose Japanese entries are Sushi King, Fujisawa Izakaya and
    # KAPPA Kaisen Izakaya. The panel beneath it was correctly empty, which is
    # the app working; a confident invented answer above an empty panel is still
    # exactly what this design exists to refuse. Three instructions not to did
    # nothing. Handing the turn to the offline composer instead only moved the
    # falsehood: reading tool payloads that were not there, it said "You have RM0
    # safe to spend today" of an account holding RM52.97.
    #
    # So the turn says the one true thing available: it does not know yet.
    if not evidence:
        if conversation_turn:
            # `just_talk` is an explicit decision, not a missing lookup. It
            # earns a normal composing call, with no financial facts in scope.
            model = _model(runtime, None, state.get("history_block", ""))
            answer = _clean(await _stream(runtime, model, conversation))
            if not answer.strip():
                offline = OfflineChatModel()
                answer = _clean(await _stream(runtime, offline, conversation))
            if not answer.strip():
                answer = CHAT_FALLBACK
            events.emit(runtime, events.TOKEN, text=answer)
            return {"answer": answer, "messages": [AIMessage(content=answer)]}
        # One turn runs no tool and is still not a guess. "I bought lunch at the
        # mamak" is spending with the amount left out, and the honest reply is to
        # ask for the figure — which is the one thing the rule above protects,
        # since a question states no number at all. Let through by route name
        # rather than by inspecting the prose, so nothing else widens with it.
        route = route_for(
            _last_human(state.get("messages", [])),
            state.get("attachment"),
            state.get("history_block", ""),
        )
        if route.name == "log_ask" and route.compose is not None:
            asked = route.compose(state.get("messages", []), _last_human(state.get("messages", [])))
            return {"answer": asked, "messages": [AIMessage(content=asked)]}
        return {"answer": NOTHING_RAN, "messages": [AIMessage(content=NOTHING_RAN)]}

    # The history the model is *given* is withheld above when nothing ran. The
    # history it *routes* on is a different thing and is never withheld: it is
    # what tells the offline composer that "what about korean then" is the
    # answer to a request for food, and writing about the balance instead would
    # be quietly answering a question nobody asked.
    history = state.get("history_block", "")
    model = _model(runtime, state.get("attachment"), history)
    answer = _clean(await _stream(runtime, model, conversation))
    if not answer.strip():
        offline = OfflineChatModel(attachment=state.get("attachment"), history=history)
        answer = _clean(await _stream(runtime, offline, conversation))
    if not answer.strip():
        # A specialist's own sentence beats an apology: it was measured, and
        # the panel beneath it already backs every figure in it.
        answer = "\n\n".join(reports) if reports else FALLBACK

    events.emit(runtime, events.TOKEN, text=answer)
    return {"answer": answer, "messages": [AIMessage(content=answer)]}


async def _stream(runtime, model, conversation) -> str:
    """Emit tokens as they arrive; fall back to one shot if streaming fails."""
    collected: list[str] = []
    try:
        async for chunk in model.astream(conversation):
            piece = chunk.content
            if not isinstance(piece, str) or not piece:
                continue
            # Buffer until the complete answer can be sanitised. A model that
            # writes a tool call as prose can split its fence across arbitrary
            # chunks; emitting first and cleaning later leaks the machinery to
            # the live chat even when the stored answer is clean.
            collected.append(piece)
        return "".join(collected)
    except Exception as exc:
        events.emit(runtime, events.THINKING, text="Falling back to what is already here")
        try:
            reply = await model.ainvoke(conversation)
        except Exception:
            return ""
        text = reply.content if isinstance(reply.content, str) else ""
        if not text:  # pragma: no cover - defensive
            events.emit(runtime, events.ERROR, message=str(exc))
        return text
