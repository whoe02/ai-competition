"""Is the Butler talking to a model, or to its offline stand-in?

Run from apps/api:  .venv/bin/python ../../scripts/check-butler-model.py
"""

from __future__ import annotations

import asyncio
import sys

from kira.agent.llm import get_chat_model, offline_reason
from kira.config import get_settings


async def main() -> int:
    settings = get_settings()
    reason = offline_reason()
    print(f"model    : {settings.butler_model}")
    print(f"endpoint : {settings.dashscope_base_url}")
    print(f"key      : {'set (' + settings.dashscope_api_key[:6] + '…)' if settings.dashscope_api_key else 'NOT SET'}")

    if reason is not None:
        print(f"\nOFFLINE — {reason}.")
        print("The Butler will answer from its scripted routes, not from a model.")
        return 1

    print("\nOnline. Asking the model one question…")

    try:
        reply = await get_chat_model().ainvoke(
            "Reply with exactly: kira online"
        )
    except Exception as exc:
        print(f"\nFAILED — {type(exc).__name__}: {exc}")
        print("The Butler would fall back to its offline model on every turn.")
        await _list_models(settings)
        return 2

    print(f"model said: {str(reply.content).strip()!r}")
    print("\nOK — the Butler is on the model.")
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
    except Exception as exc:
        print(f"\n(could not list models: {type(exc).__name__}: {exc})")
        return

    print(f"\nModels this key can call ({len(ids)}):")
    for model_id in ids:
        marker = "  ← set BUTLER_MODEL to this" if "plus" in model_id else ""
        print(f"  {model_id}{marker}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
