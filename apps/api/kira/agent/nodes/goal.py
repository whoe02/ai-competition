"""Bridge a guarded Butler workflow call into the typed Goal subgraph."""

from __future__ import annotations

import uuid

from langgraph.runtime import Runtime

from kira.agent import events
from kira.agent.goal_graph.presentation import goal_evidence
from kira.agent.goal_graph.run import run_goal_request
from kira.agent.goal_graph.schemas import GoalIntent
from kira.agent.state import ButlerContext, ButlerState

WORKFLOW = "start_goal_planning"


async def goal_workflow(
    state: ButlerState, runtime: Runtime[ButlerContext]
) -> dict:
    call = state.get("pending_workflow")
    if not call or call.get("name") != WORKFLOW:
        return {"pending_workflow": None}
    context = runtime.context
    intent = GoalIntent.model_validate(call.get("args") or {})
    events.emit(
        runtime,
        events.TOOL,
        tool=WORKFLOW,
        module="goal_planning",
        label="Planning your goal",
    )
    request_id = context.source_message_id or uuid.uuid4()
    result = await run_goal_request(
        context.session,
        context.user,
        thread_id=context.thread_id,
        message="",
        as_of_date=context.today,
        request_id=request_id,
        structured_intent=intent,
        model_factory=context.model_factory,
        explain=True,
    )
    rows = goal_evidence(result.state, context.user.currency)
    if rows:
        events.emit(runtime, events.EVIDENCE, rows=rows)
    if result.final_response:
        events.emit(runtime, events.TOKEN, text=result.final_response)
    if result.approval is not None:
        events.emit(
            runtime,
            events.APPROVAL,
            approval_id=result.approval["approval_id"],
            tool=result.approval["tool"],
            module="goal_planning",
            summary=result.approval["summary"],
            args={
                "before": result.approval.get("before"),
                "after": result.approval.get("after"),
                "base_plan_version": result.approval.get("base_plan_version"),
            },
            before=result.approval.get("before"),
            after=result.approval.get("after"),
            base_plan_version=result.approval.get("base_plan_version"),
        )
    return {
        "answer": result.final_response,
        "evidence": (state.get("evidence") or []) + rows,
        "tools_used": (state.get("tools_used") or []) + [WORKFLOW],
        "pending_workflow": None,
        "pending_approval": result.approval,
        # Butler performed structured intake; the child count contains only
        # its explanation call because structured_intent skips child intake.
        "goal_llm_calls": state.get("iterations", 0) + result.llm_calls,
    }
