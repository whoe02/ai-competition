"""Reversible commands for the app shell.

These tools never touch persistence.  Their result is also emitted as an
``app_action`` event, allowing a money question to finish on the screen that
shows the answer instead of leaving the user in the conversation.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from kira.agent.tools.spec import ToolContext, ToolResult, ToolSpec

MODULE = "app"


class AppActionArgs(BaseModel):
    action: Literal["navigate", "open_sheet", "focus_goal", "set_plan_view"]
    tab: Literal["today", "activity", "butler", "plan", "more"] | None = None
    category: str | None = Field(default=None, max_length=40)
    sheet: Literal["entry"] | None = None
    prefill: dict[str, Any] | None = None
    goal_id: str | None = None
    plan_view: Literal["daily", "goals", "foresight"] | None = None

    @model_validator(mode="after")
    def action_has_target(self):
        if self.action == "navigate" and self.tab is None:
            raise ValueError("navigate requires tab")
        if self.action == "open_sheet" and self.sheet is None:
            raise ValueError("open_sheet requires sheet")
        if self.action == "focus_goal" and self.goal_id is None:
            raise ValueError("focus_goal requires goal_id")
        if self.action == "set_plan_view" and self.plan_view is None:
            raise ValueError("set_plan_view requires plan_view")
        return self


async def _app_action(_: ToolContext, args: AppActionArgs) -> ToolResult:
    return ToolResult({"app_action": args.model_dump(mode="json", exclude_none=True)})


SPECS = (
    ToolSpec(
        name="control_app",
        module=MODULE,
        kind="ui",
        label="Opening the right screen",
        description=(
            "Control the visible app without changing data. Navigate to a tab, show Activity "
            "with a category filter, open the entry sheet with optional prefill, switch the "
            "Plan view (including Foresight), or focus a goal. Use after answering when a "
            "screen can show the result."
        ),
        args_model=AppActionArgs,
        handler=_app_action,
    ),
)
