"""Typed handoff from the Butler into deterministic Goal planning."""

from __future__ import annotations

from kira.agent.goal_graph.schemas import GoalIntent
from kira.agent.tools.spec import ToolContext, ToolResult, ToolSpec

MODULE = "goal_planning"


async def _never_execute(_: ToolContext, __: GoalIntent) -> ToolResult:
    """Workflow calls are consumed by the graph guard, never by the tool runner."""
    raise RuntimeError("start_goal_planning must be routed as a workflow")


SPECS = (
    ToolSpec(
        name="start_goal_planning",
        module=MODULE,
        kind="workflow",
        label="Planning your goal",
        description=(
            "Create, replan or recalculate a savings goal; evaluate whether a purchase "
            "would hurt a goal; or select a previously offered goal scenario. Extract "
            "only values the user stated. Use goal_reference for an existing goal name "
            "because users do not know database UUIDs. Never calculate a contribution. "
            "Use the goal_type enum supplied by the schema. Use list_goals instead for "
            "a simple read-only progress question."
        ),
        args_model=GoalIntent,
        handler=_never_execute,
    ),
)
