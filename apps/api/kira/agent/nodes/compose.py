"""compose — the answer, and the only turn that streams.

No tools are bound here, which is both what DashScope requires for streaming
and what keeps the model from reaching for one more number mid-sentence. The
evidence is already fixed by the time this runs.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage
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


async def compose(state: ButlerState, runtime: Runtime[ButlerContext]) -> dict:
    events.emit(runtime, events.THINKING, text="Putting it in words")
    evidence = state.get("evidence") or []
    conversation_turn = "just_talk" in (state.get("tools_used") or [])
    system = SystemMessage(
        prompt.composing_prompt(
            # A conversational turn must not see the snapshot it intentionally
            # chose not to read. Otherwise a greeting can repeat a balance the
            # model happened to notice in the context, which is a dashboard in
            # a friendlier voice rather than conversation.
            context="" if conversation_turn else state.get("context_block", ""),
            memory="" if conversation_turn else state.get("memory_block", ""),
            # Withheld when nothing ran. Asked the same question twice, the model
            # read the places and prices out of its own earlier reply and wrote
            # them again having called nothing — prose that looked right above a
            # panel that could vouch for none of it. Three separate instructions
            # not to do that were ignored, so the history is taken away instead:
            # with no tool result to speak from, there is now nothing to copy
            # either, and what is left is the snapshot, which is real. The
            # reasoning turn still sees the whole history, so "add the second
            # one" still knows which one that was.
            history=state.get("history_block", "") if evidence else "",
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
            model = _model(runtime, None, "")
            answer = await _stream(runtime, model, conversation)
            if not answer.strip():
                offline = OfflineChatModel()
                answer = await _stream(runtime, offline, conversation)
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
    answer = await _stream(runtime, model, conversation)
    if not answer.strip():
        offline = OfflineChatModel(attachment=state.get("attachment"), history=history)
        answer = await _stream(runtime, offline, conversation)
    if not answer.strip():
        # A specialist's own sentence beats an apology: it was measured, and
        # the panel beneath it already backs every figure in it.
        answer = "\n\n".join(reports) if reports else FALLBACK

    return {"answer": answer, "messages": [AIMessage(content=answer)]}


async def _stream(runtime, model, conversation) -> str:
    """Emit tokens as they arrive; fall back to one shot if streaming fails."""
    collected: list[str] = []
    try:
        async for chunk in model.astream(conversation):
            piece = chunk.content
            if not isinstance(piece, str) or not piece:
                continue
            collected.append(piece)
            events.emit(runtime, events.TOKEN, text=piece)
        return "".join(collected)
    except Exception as exc:
        events.emit(runtime, events.THINKING, text="Falling back to what is already here")
        try:
            reply = await model.ainvoke(conversation)
        except Exception:
            return ""
        text = reply.content if isinstance(reply.content, str) else ""
        if text:
            events.emit(runtime, events.TOKEN, text=text)
        else:  # pragma: no cover - defensive
            events.emit(runtime, events.ERROR, message=str(exc))
        return text
