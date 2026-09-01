"""The Goals specialist, behind the Butler's `start_goal_planning` handoff.

The subgraph itself is unchanged: fifteen nodes that hold the arithmetic of a
dated savings plan and raise their own approval card. What changed is what it
gives back. It used to compose the user's whole answer and end the turn; now it
reports, and the Butler writes the sentence -- unless it raised a card, in
which case the card and the child's own words are already on screen and there
is nothing left for the parent to say.
"""

from __future__ import annotations

from kira.agent.goal_graph.presentation import goal_evidence
from kira.agent.goal_graph.run import run_goal_request
from kira.agent.goal_graph.schemas import GoalIntent
from kira.agent.tools.spec import AgentContext, AgentReport, EvidenceRow


async def run_goal_agent(ctx: AgentContext, intent: GoalIntent) -> AgentReport:
    result = await run_goal_request(
        ctx.session,
        ctx.user,
        thread_id=ctx.thread_id,
        message="",
        as_of_date=ctx.today,
        request_id=ctx.request_id,
        structured_intent=intent,
        model_factory=ctx.model_factory,
        explain=True,
    )
    rows = tuple(
        EvidenceRow(label, value) for label, value in goal_evidence(result.state, ctx.currency)
    )
    return AgentReport(
        findings=_findings(result, rows),
        evidence=rows,
        answer=result.final_response,
        approval=result.approval,
        llm_calls=result.llm_calls,
    )


def _findings(result, rows: tuple[EvidenceRow, ...]) -> dict:
    """The report the Butler reads -- built from the panel and nothing else.

    Every figure here is one `goal_evidence` already formatted for the user to
    see, so a number in the Butler's answer is a number on a row underneath it.
    The subgraph's own state holds engine dataclasses that are neither JSON nor
    the parent's business, and handing those over is how a composer starts
    quoting a projection nobody displayed.
    """
    state = result.state
    definition = state.get("goal_definition")
    intent = state.get("goal_intent")
    findings: dict = {
        "specialist": "goal_planning",
        "results": {row.label: row.value for row in rows},
    }
    if definition is not None:
        findings["goal"] = definition.name
    if intent is not None:
        findings["action"] = intent.action
    if result.final_response:
        # The child's own words. The Butler may build on them; the figures it
        # may repeat are in `results`, not in here.
        findings["specialist_said"] = result.final_response
    if result.approval is not None:
        findings["awaiting_approval"] = result.approval.get("summary", "")
    quality = state.get("data_quality")
    if quality is not None and quality.status != "ready":
        findings["data_quality"] = {"status": quality.status, "issues": quality.issues}
    if state.get("errors"):
        findings["errors"] = list(state["errors"])
    return findings
