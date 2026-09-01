"""Every capability the Butler has, in one registry.

Adding a module to the Butler is adding a file here and one line below. The
graph, the guard, the approval flow and the API do not change — which is the
whole of the "controls all modules, present and future" requirement.
"""

from __future__ import annotations

from kira.agent.tools import (
    capture,
    chat,
    commitments,
    dashboard,
    day_plan,
    foresight,
    goal_workflow,
    goals,
    hindsight,
    ledger,
    memory,
)
from kira.agent.tools.spec import (
    AgentContext,
    AgentReport,
    EvidenceRow,
    ToolContext,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    ToolSpecError,
    money_str,
)

MODULES = (
    chat,
    dashboard,
    ledger,
    goals,
    goal_workflow,
    commitments,
    memory,
    capture,
    foresight,
    hindsight,
    day_plan,
)


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for module in MODULES:
        for spec in module.SPECS:
            registry.register(spec)
    return registry


REGISTRY = build_registry()

__all__ = [
    "AgentContext",
    "AgentReport",
    "EvidenceRow",
    "MODULES",
    "REGISTRY",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "ToolSpecError",
    "build_registry",
    "money_str",
]
