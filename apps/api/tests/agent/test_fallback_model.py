"""The ladder: the main model, the one behind it, then the offline stand-in.

A turn is worth more than the model that was meant to answer it. When the main
model errors -- an id this key is not served, a rate limit, a timeout -- the
same call goes to the fallback model before anything drops to scripted prose.
"""

from __future__ import annotations

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel

from kira.agent.llm import FallbackChatModel, get_chat_model


class Named(BaseChatModel):
    """Answers with its own name, so a reply says which model wrote it."""

    tag: str = "model"

    @property
    def _llm_type(self) -> str:
        return "named"

    def bind_tools(self, tools, **kwargs) -> BaseChatModel:
        return self.model_copy(update={"tag": f"{self.tag}+tools"})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.tag))])


class Dead(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "dead"

    def bind_tools(self, tools, **kwargs) -> BaseChatModel:
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise RuntimeError("model not served to this key")


ASK = [HumanMessage("what did I spend today")]


def test_main_model_answers_and_the_spare_is_never_asked() -> None:
    model = FallbackChatModel(primary=Named(tag="main"), secondary=Dead())
    assert model.invoke(ASK).content == "main"


async def test_a_failed_main_model_is_retried_on_the_fallback() -> None:
    model = FallbackChatModel(primary=Dead(), secondary=Named(tag="spare"))
    reply = await model.ainvoke(ASK)
    assert reply.content == "spare"
    # The swap is readable off the turn afterwards rather than only in the logs.
    assert "not served" in reply.response_metadata[FallbackChatModel.METADATA_KEY]


def test_tools_survive_the_swap() -> None:
    """The reasoning turn is the one that must not lose its tools mid-ladder."""
    model = FallbackChatModel(primary=Dead(), secondary=Named(tag="spare"))
    assert model.bind_tools([]).invoke(ASK).content == "spare+tools"


async def test_the_fallback_streams_when_the_main_model_cannot() -> None:
    model = FallbackChatModel(primary=Dead(), secondary=Named(tag="spare"))
    chunks = [chunk.content async for chunk in model.astream(ASK)]
    assert "".join(chunks) == "spare"


def test_both_dead_raises_so_the_node_can_go_offline() -> None:
    """The last rung is the caller's: compose and agent catch this and script it."""
    model = FallbackChatModel(primary=Dead(), secondary=Dead())
    with pytest.raises(RuntimeError):
        model.invoke(ASK)


class Schema(BaseModel):
    answer: str


def test_structured_output_falls_back_too() -> None:
    """The Plan screen's ask box wants a filled schema, not a message."""

    class Filled(Named):
        def with_structured_output(self, schema, **kwargs):
            return self | (lambda message: Schema(answer=message.content))

    class Broken(Dead):
        def with_structured_output(self, schema, **kwargs):
            return self | (lambda message: message)

    model = FallbackChatModel(primary=Broken(), secondary=Filled(tag="spare"))
    assert model.with_structured_output(Schema).invoke(ASK) == Schema(answer="spare")


def test_one_model_configured_is_left_unwrapped(monkeypatch) -> None:
    """No fallback id, or the same id twice, means no ladder to build."""
    from kira.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.setenv("BUTLER_OFFLINE", "0")
    monkeypatch.setenv("BUTLER_MODEL", "qwen3.7-flash")

    monkeypatch.setenv("BUTLER_FALLBACK_MODEL", "qwen3.6-plus")
    get_settings.cache_clear()
    laddered = get_chat_model()
    assert isinstance(laddered, FallbackChatModel)
    assert laddered.primary.model_name == "qwen3.7-flash"
    assert laddered.secondary.model_name == "qwen3.6-plus"

    monkeypatch.setenv("BUTLER_FALLBACK_MODEL", "qwen3.7-flash")
    get_settings.cache_clear()
    assert not isinstance(get_chat_model(), FallbackChatModel)

    monkeypatch.setenv("BUTLER_FALLBACK_MODEL", "")
    get_settings.cache_clear()
    assert not isinstance(get_chat_model(), FallbackChatModel)

    get_settings.cache_clear()
