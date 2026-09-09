"""The Butler under test runs the real graph against the deterministic model."""

from __future__ import annotations

import itertools

import pytest

from kira.agent.llm import OfflineChatModel
from kira.seed.demo import DEMO_TODAY, seed_demo_user
from kira.services import day_plan as day_plan_service
from kira.services.butler_thread import ensure_thread

# The distance the fixed place world was laid out around, back when every mode
# searched a flat five kilometres of it.
WHOLE_WORLD_KM = 5.0


def offline_factory(**kwargs):
    """Every test drives the same model the venue-network fallback uses."""
    return OfflineChatModel(
        attachment=kwargs.get("attachment"), history=kwargs.get("history", "")
    )


@pytest.fixture
async def butler(session):
    user = await seed_demo_user(session)
    thread = await ensure_thread(session, user)
    return user, thread


@pytest.fixture
def today():
    return DEMO_TODAY


@pytest.fixture
def whole_world_in_range(monkeypatch):
    """Let every mode reach the five kilometres the fixed world was laid out in.

    The planner tool takes no radius and is not going to: how far a search
    reaches follows from the mode, and a model that could set it would be
    deciding how far the user walks. So a tool test that needs the whole of the
    fixed world stands the derivation aside rather than arguing with it. What
    the derivation actually derives is a question about the search and is asked
    of the search, in ``tests/services/test_day_plan.py``.
    """
    monkeypatch.setattr(day_plan_service, "radius_for", lambda mode: WHOLE_WORLD_KM)


class ScriptedModel(OfflineChatModel):
    """Emits exactly the tool calls a test names, then composes as usual.

    Subclassing the offline model rather than mocking keeps the graph, the
    guard and the approval flow on their real code paths.
    """

    calls: list = []

    def bind_tools(self, tools, **kwargs):
        bound = super().bind_tools(tools, **kwargs)
        return bound.model_copy(update={"calls": self.calls})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.messages import AIMessage, ToolMessage
        from langchain_core.outputs import ChatGeneration, ChatResult

        if not self.bound_tools:
            return super()._generate(messages, stop, run_manager, **kwargs)
        if any(isinstance(message, ToolMessage) for message in messages):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])
        tool_calls = [
            {"name": name, "args": args, "id": f"scripted-{index}", "type": "tool_call"}
            for index, (name, args) in enumerate(self.calls)
        ]
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="", tool_calls=tool_calls))]
        )


def scripted_factory(*calls):
    def factory(**kwargs):
        return ScriptedModel(
            attachment=kwargs.get("attachment"),
            history=kwargs.get("history", ""),
            calls=list(calls),
        )

    return factory


class SequencedModel(OfflineChatModel):
    """Emits one batch of tool calls per reasoning pass, in the order given.

    `ScriptedModel` answers a single pass and then falls silent, which was
    enough while a turn ended at its first write. A turn that continues after an
    approval needs a model with a second thing to say, so this one pops a batch
    per pass and proposes nothing once the script runs out — which is how a real
    turn ends too.

    The cursor lives in the factory's closure and reaches the model as a
    callable, not as a list. `agent` builds a fresh model on every pass, so the
    cursor has to outlive them — and a list field would not do it: pydantic
    validates `list` by copying, so each instance would pop from its own copy
    and every pass would propose the first batch again. A field typed `object`
    is handed through untouched.
    """

    next_batch: object = None
    counter: object = None

    def bind_tools(self, tools, **kwargs):
        bound = super().bind_tools(tools, **kwargs)
        return bound.model_copy(
            update={"next_batch": self.next_batch, "counter": self.counter}
        )

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult

        if not self.bound_tools:
            return super()._generate(messages, stop, run_manager, **kwargs)
        calls = self.next_batch()
        # Unique across the whole turn, not just within the batch. A real model
        # does not reuse a call id between passes, and the approval projection
        # keys its replay on one.
        tool_calls = [
            {
                "name": name,
                "args": args,
                "id": f"seq-{next(self.counter)}",
                "type": "tool_call",
            }
            for name, args in calls
        ]
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="", tool_calls=tool_calls))]
        )


def sequenced_factory(*batches):
    """One tuple of (name, args) pairs per reasoning pass."""
    remaining = [list(batch) for batch in batches]
    counter = itertools.count()

    def next_batch():
        return remaining.pop(0) if remaining else []

    def factory(**kwargs):
        return SequencedModel(
            attachment=kwargs.get("attachment"),
            history=kwargs.get("history", ""),
            next_batch=next_batch,
            counter=counter,
        )

    return factory


class DecliningModel(OfflineChatModel):
    """Answers the tool-calling turn with prose and no tool call at all.

    This is the live online failure, not an invented one: asked where to eat,
    Qwen wrote a fluent paragraph, called nothing, and on a second attempt named
    a restaurant that is in no data file here. Composition is left to the
    offline model underneath, so a test can tell what the graph gathered from
    what this thing made up.
    """

    prose: str = ""

    def bind_tools(self, tools, **kwargs):
        bound = super().bind_tools(tools, **kwargs)
        return bound.model_copy(update={"prose": self.prose})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult

        if not self.bound_tools:
            return super()._generate(messages, stop, run_manager, **kwargs)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.prose))])


def declining_factory(prose: str):
    def factory(**kwargs):
        return DecliningModel(
            attachment=kwargs.get("attachment"),
            history=kwargs.get("history", ""),
            prose=prose,
        )

    return factory
