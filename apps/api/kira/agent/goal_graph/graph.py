"""Conditional LangGraph definition for goal planning and approval."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from kira.agent.goal_graph.nodes import (
    apply_goal_plan,
    approval_interrupt,
    audit_goal_run,
    clarification_response,
    compose_goal_response,
    create_plan_change_draft,
    evaluate_goal_impact,
    generate_goal_scenarios,
    goal_data_quality_gate,
    goal_intake,
    goal_policy_guard,
    load_financial_snapshot,
    reconcile_short_term_cashflow,
    resolve_goal_target,
    route_after_apply,
    route_after_approval,
    route_after_compose,
    route_after_guard,
    route_after_impact,
    route_after_intake,
    route_after_quality,
    route_after_reconciliation,
    route_after_resolve,
    route_after_scenarios,
    solve_goal_baseline,
)
from kira.agent.goal_graph.state import GoalGraphContext, GoalGraphState


def checkpoint_serializer() -> JsonPlusSerializer:
    """Allow only KIRA's typed goal-state modules beyond LangGraph's safe defaults."""
    return JsonPlusSerializer(
        allowed_msgpack_modules=(
            ("kira.agent.goal_graph.schemas", "GoalIntent"),
            ("kira.agent.goal_graph.schemas", "GoalDataQuality"),
            ("kira.agent.goal_graph.state", "PlanChangeDraft"),
            ("kira.engine.goal_planning", "GoalDefinition"),
            ("kira.engine.goal_planning", "AccountBalance"),
            ("kira.engine.goal_planning", "IncomePayday"),
            ("kira.engine.goal_planning", "ProtectedCommitment"),
            ("kira.engine.goal_planning", "ActiveGoalReserve"),
            ("kira.engine.goal_planning", "FinancialSnapshot"),
            ("kira.engine.goal_planning", "GoalMilestone"),
            ("kira.engine.goal_planning", "GoalPlan"),
            ("kira.engine.goal_planning", "GoalScenario"),
            ("kira.engine.goal_planning", "CashflowReconciliation"),
            ("kira.engine.goal_planning", "GoalImpact"),
        )
    )


def build_goal_graph(checkpointer: BaseCheckpointSaver | None = None):
    builder = StateGraph(GoalGraphState, context_schema=GoalGraphContext)
    builder.add_node("goal_intake", goal_intake)
    builder.add_node("resolve_goal_target", resolve_goal_target)
    builder.add_node("goal_policy_guard", goal_policy_guard)
    builder.add_node("load_financial_snapshot", load_financial_snapshot)
    builder.add_node("goal_data_quality_gate", goal_data_quality_gate)
    builder.add_node("solve_goal_baseline", solve_goal_baseline)
    builder.add_node("reconcile_short_term_cashflow", reconcile_short_term_cashflow)
    builder.add_node("evaluate_goal_impact", evaluate_goal_impact)
    builder.add_node("generate_goal_scenarios", generate_goal_scenarios)
    builder.add_node("compose_goal_response", compose_goal_response)
    builder.add_node("clarification_response", clarification_response)
    builder.add_node("create_plan_change_draft", create_plan_change_draft)
    builder.add_node("approval_interrupt", approval_interrupt)
    builder.add_node("apply_goal_plan", apply_goal_plan)
    builder.add_node("audit_goal_run", audit_goal_run)

    builder.add_edge(START, "goal_intake")
    builder.add_conditional_edges(
        "goal_intake",
        route_after_intake,
        {"clarify": "clarification_response", "resolve": "resolve_goal_target"},
    )
    builder.add_conditional_edges(
        "resolve_goal_target",
        route_after_resolve,
        {"clarify": "clarification_response", "guard": "goal_policy_guard"},
    )
    builder.add_conditional_edges(
        "goal_policy_guard",
        route_after_guard,
        {"clarify": "clarification_response", "snapshot": "load_financial_snapshot"},
    )
    builder.add_edge("load_financial_snapshot", "goal_data_quality_gate")
    builder.add_conditional_edges(
        "goal_data_quality_gate",
        route_after_quality,
        {"clarify": "clarification_response", "solve": "solve_goal_baseline"},
    )
    builder.add_edge("solve_goal_baseline", "reconcile_short_term_cashflow")
    builder.add_conditional_edges(
        "reconcile_short_term_cashflow",
        route_after_reconciliation,
        {
            "impact": "evaluate_goal_impact",
            "scenarios": "generate_goal_scenarios",
            "compose": "compose_goal_response",
            "draft": "create_plan_change_draft",
        },
    )
    builder.add_conditional_edges(
        "evaluate_goal_impact",
        route_after_impact,
        {"scenarios": "generate_goal_scenarios", "compose": "compose_goal_response"},
    )
    builder.add_conditional_edges(
        "generate_goal_scenarios",
        route_after_scenarios,
        {"clarify": "clarification_response", "compose": "compose_goal_response"},
    )
    builder.add_conditional_edges(
        "compose_goal_response",
        route_after_compose,
        {"draft": "create_plan_change_draft", "audit": "audit_goal_run"},
    )
    builder.add_edge("clarification_response", "audit_goal_run")
    builder.add_edge("create_plan_change_draft", "approval_interrupt")
    builder.add_conditional_edges(
        "approval_interrupt",
        route_after_approval,
        {
            "apply": "apply_goal_plan",
            "snapshot": "load_financial_snapshot",
            "audit": "audit_goal_run",
        },
    )
    builder.add_conditional_edges(
        "apply_goal_plan",
        route_after_apply,
        {"snapshot": "load_financial_snapshot", "audit": "audit_goal_run"},
    )
    builder.add_edge("audit_goal_run", END)
    return builder.compile(
        checkpointer=checkpointer or InMemorySaver(serde=checkpoint_serializer())
    )


@lru_cache
def _memory_goal_graph():
    return build_goal_graph()


_goal_graph: Any = None


def configure_goal_graph(checkpointer: BaseCheckpointSaver | None) -> None:
    global _goal_graph
    _goal_graph = build_goal_graph(checkpointer) if checkpointer is not None else None
    if checkpointer is None:
        _memory_goal_graph.cache_clear()


def get_goal_graph():
    return _goal_graph if _goal_graph is not None else _memory_goal_graph()
