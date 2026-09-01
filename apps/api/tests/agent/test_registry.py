"""The registry's promises, checked structurally rather than by inspection."""

from __future__ import annotations

import inspect
import json
import re

import pytest
from pydantic import BaseModel, ValidationError

from kira.agent.tools import MODULES, REGISTRY, ToolSpec, ToolSpecError, build_registry


class Args(BaseModel):
    pass


async def _handler(ctx, args):  # pragma: no cover - never called
    raise AssertionError("not invoked")


def _spec(**overrides) -> ToolSpec:
    fields = {
        "name": "do_something",
        "module": "test",
        "kind": "read",
        "description": "Does something.",
        "args_model": Args,
        "handler": _handler,
    }
    fields.update(overrides)
    return ToolSpec(**fields)


def test_a_write_without_a_summary_cannot_be_registered():
    """A write the user cannot read before approving must not exist."""
    with pytest.raises(ToolSpecError, match="summarise"):
        _spec(kind="write")


def test_a_write_with_a_summary_is_fine():
    spec = _spec(kind="write", summarise=lambda args: "Does something.")
    assert spec.is_write


def test_every_registered_write_has_a_summary():
    for spec in REGISTRY.writes():
        assert spec.summarise is not None, spec.name


def test_every_spec_round_trips_through_json_schema():
    for spec in REGISTRY:
        schema = spec.json_schema()
        assert json.loads(json.dumps(schema)) == schema
        assert schema["function"]["name"] == spec.name
        assert schema["function"]["description"].strip()


def test_no_tool_can_reach_money_movement():
    """There is no ToolSpec for moving money, and no handler that reaches one.

    Structural incapacity, not instruction: the absence is the control.
    """
    forbidden = (
        "apply_plan_change",
        "move_money",
        "transfer_funds",
        "make_payment",
        "pay_commitment",
    )
    for name in forbidden:
        assert REGISTRY.get(name) is None
    pattern = re.compile(r"\b(" + "|".join(forbidden) + r")\b")
    seen: set[str] = set()
    for spec in REGISTRY:
        module = inspect.getmodule(spec.handler)
        for source in _reachable_sources(module, seen):
            assert not pattern.search(source), f"{spec.name} reaches money movement"


def _reachable_sources(module, seen: set[str]) -> list[str]:
    """Source of the handler's module and every kira module it pulls in."""
    if module is None or module.__name__ in seen:
        return []
    seen.add(module.__name__)
    sources = [inspect.getsource(module)]
    for value in vars(module).values():
        child = value if inspect.ismodule(value) else inspect.getmodule(value)
        if child is not None and child.__name__.startswith("kira."):
            sources.extend(_reachable_sources(child, seen))
    return sources


def test_names_are_unique_and_a_duplicate_is_refused():
    registry = build_registry()
    with pytest.raises(ToolSpecError, match="already registered"):
        registry.register(REGISTRY.get("list_goals"))


def test_bad_names_are_refused():
    with pytest.raises(ToolSpecError, match="lower_snake_case"):
        _spec(name="Do-Something")


def test_a_description_is_required():
    with pytest.raises(ToolSpecError, match="description"):
        _spec(description="   ")


def test_every_module_contributes_at_least_one_spec():
    modules = REGISTRY.modules()
    assert len(modules) == len(MODULES)
    for spec in REGISTRY:
        assert spec.module in modules


def test_reads_writes_and_workflows_partition_the_registry():
    assert (
        len(REGISTRY.reads()) + len(REGISTRY.writes()) + len(REGISTRY.workflows())
        == len(REGISTRY)
    )
    assert {spec.name for spec in REGISTRY.workflows()} == {"start_goal_planning"}


class TestAddTransactionCategory:
    """An edited approval is user input, so the category cannot be free text."""

    def test_it_accepts_a_known_category(self):
        spec = REGISTRY.get("add_transaction")
        args = spec.args_model.model_validate(
            {"merchant": "Mamak", "amount_sen": 1250, "occurred_on": "2026-09-03",
             "category": "food"}
        )
        assert args.category == "food"

    def test_it_refuses_one_the_ledger_cannot_file(self):
        spec = REGISTRY.get("add_transaction")
        with pytest.raises(ValidationError):
            spec.args_model.model_validate(
                {"merchant": "Mamak", "amount_sen": 1250, "occurred_on": "2026-09-03",
                 "category": "makan"}
            )
