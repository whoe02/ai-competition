from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from kira.engine import (
    AccountBalance,
    ActiveGoalReserve,
    FinancialSnapshot,
    GoalDefinition,
    IncomePayday,
    ProtectedCommitment,
    build_goal_contribution_schedule,
    calculate_goal_feasibility,
    calculate_goal_plan_for_contribution,
    calculate_required_contribution,
    evaluate_goal_impact,
    generate_goal_scenarios,
    reconcile_goal_with_short_term_cashflow,
)

USER_ID = "8ab994ff-b0d7-4d89-8687-b40d9b3534cc"
GOAL_ID = "09c5643f-4430-49bd-abf9-94d435fac6c9"


def goal(**changes) -> GoalDefinition:
    base = GoalDefinition(
        goal_id=GOAL_ID,
        user_id=USER_ID,
        goal_type="travel",
        name="Family trip",
        currency="MYR",
        target_amount_sen=10_001,
        current_saved_sen=0,
        target_date=date(2026, 10, 5),
        priority="important",
        status="active",
    )
    return replace(base, **changes)


def snapshot(**changes) -> FinancialSnapshot:
    base = FinancialSnapshot(
        user_id=USER_ID,
        as_of_utc=datetime(2026, 9, 1, tzinfo=UTC),
        currency="MYR",
        cash_available_sen=100_000,
        accounts=(AccountBalance("account-1", 100_000, "account:1"),),
        next_income_payday=IncomePayday(date(2026, 9, 5), 20_000, "income:1"),
        commitments=(
            ProtectedCommitment("bill-1", "Rent", 30_000, date(2026, 9, 4), True, "commitment:1"),
        ),
        emergency_buffer_sen=20_000,
        active_goal_plans=(ActiveGoalReserve("other-goal", 10_000, "protected"),),
        data_confidence="high",
        evidence_refs=("account:1", "income:1", "commitment:1"),
        pay_cycle_days=30,
    )
    return replace(base, **changes)


class TestIntegerSen:
    def test_money_inputs_reject_float_sen(self):
        with pytest.raises(TypeError, match="integer sen"):
            snapshot(cash_available_sen=100_000.0)

    def test_required_contribution_rounds_up_in_integer_sen(self):
        assert calculate_required_contribution(goal(), snapshot()) == 5_001
        schedule = build_goal_contribution_schedule(goal(), snapshot())
        assert [item.amount_sen for item in schedule] == [5_001, 5_000]
        assert sum(item.amount_sen for item in schedule) == 10_001


class TestSafetyBoundaries:
    def test_protected_bills_and_buffer_are_preserved(self):
        plan = calculate_goal_feasibility(goal(), snapshot())
        cashflow = reconcile_goal_with_short_term_cashflow(snapshot(), plan)
        assert cashflow.protected_commitments_sen == 30_000
        assert cashflow.emergency_buffer_sen == 20_000
        assert cashflow.other_goal_reserves_sen == 10_000
        assert cashflow.flexible_cash_after_reserves_sen == 34_999
        assert cashflow.safe_for_next_payday is True

    def test_goal_is_infeasible_when_protected_cash_is_short(self):
        constrained = snapshot(
            cash_available_sen=45_000, next_income_payday=IncomePayday(date(2026, 9, 5), 0)
        )
        plan = calculate_goal_feasibility(goal(), constrained)
        cashflow = reconcile_goal_with_short_term_cashflow(constrained, plan)
        assert plan.feasible is False
        assert cashflow.safe_for_next_payday is False
        assert "protected_commitments_underfunded" in cashflow.risk_flags


class TestDatesAndImpact:
    def test_later_target_date_reduces_required_contribution(self):
        original = calculate_required_contribution(goal(), snapshot())
        later = calculate_required_contribution(goal(target_date=date(2026, 11, 4)), snapshot())
        assert original == 5_001
        assert later == 3_334

    def test_selected_contribution_that_misses_target_is_infeasible(self):
        plan = calculate_goal_plan_for_contribution(goal(), snapshot(), 2_000)
        assert plan.required_contribution_per_payday_sen == 2_000
        assert plan.projected_completion_date > plan.target_date
        assert plan.feasible is False
        assert "projected_after_target" in plan.risk_flags

    def test_purchase_can_delay_goal_without_touching_protected_money(self):
        plan = calculate_goal_feasibility(goal(), snapshot())
        impact = evaluate_goal_impact(35_001, snapshot(), plan)
        assert impact.protected_money_touched is False
        assert impact.safe_to_spend is False
        assert impact.goal_reserve_shortfall_sen == 2
        assert impact.goal_delay_days == 30

    def test_purchase_that_crosses_floor_is_explicitly_unsafe(self):
        plan = calculate_goal_feasibility(goal(), snapshot())
        impact = evaluate_goal_impact(50_000, snapshot(), plan)
        assert impact.protected_money_touched is True
        assert "protected_money_would_be_used" in impact.risk_flags


class TestReproducibility:
    def test_same_inputs_return_identical_plan_and_scenarios(self):
        assert calculate_goal_feasibility(goal(), snapshot()) == calculate_goal_feasibility(
            goal(), snapshot()
        )
        assert generate_goal_scenarios(goal(), snapshot()) == generate_goal_scenarios(
            goal(), snapshot()
        )
