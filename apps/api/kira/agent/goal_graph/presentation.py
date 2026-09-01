"""Deterministic user-facing rows and approval-resume messages for Goal runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kira.agent.goal_graph.state import GoalGraphState
from kira.money import Money

if TYPE_CHECKING:
    from kira.agent.goal_graph.run import GoalRunResult


def _money(sen: int, currency: str) -> str:
    amount = Money(sen, currency)
    return f"RM{amount.ringgit_str()}" if currency == "MYR" else str(amount)


def goal_evidence(state: GoalGraphState, currency: str) -> list[list[str]]:
    """Build the Butler evidence panel from deterministic results only."""
    rows: list[list[str]] = []
    plan = state.get("current_goal_plan")
    if plan is not None:
        rows.extend(
            [
                ["Goal target", _money(plan.target_amount_sen, currency)],
                ["Already saved", _money(plan.current_saved_sen, currency)],
                [
                    "Required each payday",
                    _money(plan.required_contribution_per_payday_sen, currency),
                ],
                ["Target date", plan.target_date.isoformat()],
                [
                    "Projected completion",
                    plan.projected_completion_date.isoformat()
                    if plan.projected_completion_date
                    else "not projected",
                ],
                ["Feasibility", "feasible" if plan.feasible else "at risk"],
            ]
        )
    reconciliation = state.get("reconciliation")
    if reconciliation is not None:
        rows.extend(
            [
                [
                    "Protected commitments",
                    _money(reconciliation.protected_commitments_sen, currency),
                ],
                ["Emergency buffer", _money(reconciliation.emergency_buffer_sen, currency)],
                [
                    "Flexible cash after reserves",
                    _money(reconciliation.flexible_cash_after_reserves_sen, currency),
                ],
            ]
        )
    impact = state.get("goal_impact")
    if impact is not None:
        rows.extend(
            [
                ["Proposed purchase", _money(impact.proposed_spend_sen, currency)],
                ["Safe for this goal", "yes" if impact.safe_to_spend else "no"],
                [
                    "Goal reserve shortfall",
                    _money(impact.goal_reserve_shortfall_sen, currency),
                ],
            ]
        )
    for scenario in state.get("goal_scenarios", ()):
        rows.append(
            [
                scenario.label,
                f"{_money(scenario.contribution_per_payday_sen, currency)} per payday · "
                f"{scenario.target_date.isoformat()}",
            ]
        )
    return rows


def goal_resume_answer(result: GoalRunResult, currency: str) -> str:
    """Say what an approval decision did without spending another LLM call."""
    approval = result.state.get("approval") or {}
    status = approval.get("status")
    definition = result.state.get("goal_definition")
    name = definition.name if definition is not None else "goal"
    plan = result.state.get("current_goal_plan")
    if result.approval is not None:
        return (
            f"I recalculated the {name} plan from the latest confirmed figures.\n"
            "Review the updated before-and-after proposal below; nothing new has been applied."
        )
    if status == "applied" and plan is not None:
        version = result.state.get("applied_plan_version")
        return (
            f"Approved — the {name} plan is now version {version}, with "
            f"{_money(plan.required_contribution_per_payday_sen, currency)} per payday.\n"
            "The previous approved version remains in the history, and protected "
            "money stays reserved."
        )
    if status == "rejected":
        return (
            f"Rejected — the {name} plan was not changed.\n"
            "The current approved version remains in place."
        )
    return result.final_response
