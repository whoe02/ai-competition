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

FALLBACK = (
    "I could not reach my language model just now.\n"
    "The numbers above are still live and correct — they come from your ledger, not from it."
)

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
    return get_chat_model(streaming=True, attachment=attachment, history=history)


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
    system = SystemMessage(
        prompt.system_prompt(
            context=state.get("context_block", ""),
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
            history=state.get("history_block", "") if evidence else "",
            attachment=state.get("attachment_block", ""),
        )
        + "\n\n"
        + _evidence_block(evidence)
        + "\n\n"
        + prompt.COMPOSE_INSTRUCTION
    )
    # The instruction goes in the system block rather than as a trailing turn:
    # the last human message must stay the user's question, not ours.
    conversation = [system, *state.get("messages", [])]

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
        answer = FALLBACK

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
