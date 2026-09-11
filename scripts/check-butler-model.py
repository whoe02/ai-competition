"""Is the Butler talking to a model, or to its offline stand-in?

Run from apps/api:  .venv/bin/python ../../scripts/check-butler-model.py
"""

from __future__ import annotations

import asyncio
import sys

from kira.agent.llm import get_chat_model, offline_reason
from kira.agent.tools import REGISTRY
from kira.config import get_settings
from langchain_core.messages import HumanMessage
from pydantic import BaseModel


class _CapabilityProbe(BaseModel):
    """Small provider-neutral schema used only by this operator check."""

    status: str


async def main() -> int:
    settings = get_settings()
    reason = offline_reason()
    print(f"model    : {settings.butler_model}")
    print(f"fallback : {settings.butler_fallback_model or 'none'}")
    print(f"endpoint : {settings.dashscope_base_url}")
    print(f"key      : {'configured' if settings.dashscope_api_key else 'NOT SET'}")

    if reason is not None:
        print(f"\nOFFLINE — {reason}.")
        print("The Butler will answer from its scripted routes, not from a model.")
        return 1

    print("\nOnline. Checking chat, tool calling, and structured output…")

    try:
        model = get_chat_model()
        reply = await model.ainvoke(
            [HumanMessage(content="Reply with exactly: kira online")]
        )
        # Binding an empty list does not put a `tools` field in every provider
        # request. Bind the real registry to test the same request Butler makes.
        tool_reply = await model.bind_tools(REGISTRY.schemas()).ainvoke(
            [
                HumanMessage(
                    content=(
                        "Reply with exactly: kira tools online. "
                        "Do not call a tool for this capability check."
                    )
                )
            ]
        )
        structured = await model.with_structured_output(_CapabilityProbe).ainvoke(
            [
                HumanMessage(
                    content=(
                        'Return one JSON object with exactly {"status":"kira structured online"}. '
                        "Do not include Markdown."
                    )
                )
            ]
        )
    except Exception as exc:  # noqa: BLE001 - reports any provider failure to the operator
        print(f"\nFAILED — {type(exc).__name__}: {exc}")
        print(
            "The configured model cannot complete every Butler capability. "
            "Choose a tool-capable primary/fallback pair before using it."
        )
        await _list_models(settings)
        return 2

    print(f"model said: {str(reply.content).strip()!r}")
    print(f"tools said: {str(tool_reply.content).strip()!r}")
    print(f"structured said: {structured.status!r}")
    print("\nOK — the Butler model supports every required request shape.")
    return 0


async def _list_models(settings) -> None:
    """What this key can actually call — the fastest way to settle a model id."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as http:
            response = await http.get(
                f"{settings.dashscope_base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {settings.dashscope_api_key}"},
            )
        response.raise_for_status()
        ids = sorted(item["id"] for item in response.json().get("data", []))
    except Exception as exc:  # noqa: BLE001 - network diagnostics must remain best effort
        print(f"\n(could not list models: {type(exc).__name__}: {exc})")
        return

    print(f"\nModels this key can call ({len(ids)}):")
    for model_id in ids:
        if model_id == settings.butler_model:
            marker = "  ← BUTLER_MODEL"
        elif model_id == settings.butler_fallback_model:
            marker = "  ← BUTLER_FALLBACK_MODEL"
        else:
            marker = ""
        print(f"  {model_id}{marker}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
