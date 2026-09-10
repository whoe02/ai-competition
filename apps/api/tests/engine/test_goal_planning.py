from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from kira.engine import (
    AccountBalance,
    ActiveGoalReserve,
    FinancialSnapshot,
    GoalDefinition,
    GoalFundingNeed,
    IncomePayday,
    ProtectedCommitment,
    allocate_income_to_goals,
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
        active_goal_plans=(ActiveGoalReserve("other-goal", 10_000),),
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


class TestIncomeAllocation:
    def test_target_date_and_id_make_the_split_reproducible(self):
        needs = (
            GoalFundingNeed("z", "Soonest", date(2026, 9, 20), 20_000, 20_000),
            GoalFundingNeed("b", "Later", date(2026, 11, 1), 30_000, 30_000),
            GoalFundingNeed("a", "Soon", date(2026, 10, 1), 30_000, 30_000),
        )
        first = allocate_income_to_goals(
            income_transaction_id="income-1",
            income_amount_sen=50_000,
            snapshot=snapshot(cash_available_sen=100_000),
            goals=needs,
        )
        second = allocate_income_to_goals(
            income_transaction_id="income-1",
            income_amount_sen=50_000,
            snapshot=snapshot(cash_available_sen=100_000),
            goals=tuple(reversed(needs)),
        )
        assert first == second
        assert [(item.goal_id, item.amount_sen) for item in first.allocations] == [
            ("z", 20_000),
            ("a", 30_000),
        ]
        assert sum(item.amount_sen for item in first.allocations) == 50_000
        assert all(isinstance(item.income_share_bp, int) for item in first.allocations)


class TestGoalAffordability:
    def test_contribution_bands_are_deterministic_and_include_other_goals(self):
        financials = snapshot(
            cash_available_sen=1_000_000,
            next_income_payday=IncomePayday(date(2026, 9, 5), 520_000, "income:1"),
            commitments=(
                ProtectedCommitment(
                    "bill-1", "Rent", 200_000, date(2026, 9, 20), True, "commitment:1"
                ),
            ),
            active_goal_plans=(),
        )
        comfortable = calculate_goal_plan_for_contribution(
            goal(target_amount_sen=600_000, target_date=date(2026, 12, 5)),
            financials,
            150_000,
        )
        assert comfortable.affordability_status == "comfortable"
        assert comfortable.contribution_ratio_bp == 2885
        assert comfortable.monthly_disposable_for_goals_sen == 320_000
        assert comfortable.feasible is True

        unsustainable = calculate_goal_plan_for_contribution(
            goal(target_amount_sen=900_000, target_date=date(2026, 12, 5)),
            financials,
            260_001,
        )
        assert unsustainable.affordability_status == "unsustainable"
        assert unsustainable.feasible is False
        assert "goal_contributions_exceed_50_percent_of_income" in unsustainable.risk_flags

        impossible_ratio = calculate_goal_plan_for_contribution(
            goal(target_amount_sen=900_000, target_date=date(2026, 12, 5)),
            replace(financials, commitments=()),
            364_001,
        )
        assert impossible_ratio.affordability_status == "impossible"
        assert impossible_ratio.feasible is False
        assert (
            "goal_contributions_exceed_70_percent_of_income"
            in impossible_ratio.risk_flags
        )

        impossible = calculate_goal_plan_for_contribution(
            goal(target_amount_sen=900_000, target_date=date(2026, 12, 5)),
            financials,
            320_001,
        )
        assert impossible.affordability_status == "impossible"
        assert impossible.feasible is False
        assert "goal_contributions_exceed_disposable_income" in impossible.risk_flags

    def test_protected_money_caps_the_income_available_to_goals(self):
        plan = allocate_income_to_goals(
            income_transaction_id="income-2",
            income_amount_sen=80_000,
            snapshot=snapshot(cash_available_sen=55_000),
            goals=(
                GoalFundingNeed("goal", "House", date(2028, 1, 1), 80_000, 80_000),
            ),
        )
        # RM30,000 bill + RM20,000 buffer leave RM5,000; the engine cannot
        # reinterpret either protected amount as goal money.
        assert plan.available_for_goals_sen == 5_000
        assert plan.allocated_sen == 5_000


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
    def test_cash_flow_safe_reserves_a_real_cushion(self):
        financials = snapshot(
            next_income_payday=IncomePayday(date(2026, 9, 5), 100_000, "income:1"),
            commitments=(),
            active_goal_plans=(),
        )
        on_time, cash_safe, accelerated = generate_goal_scenarios(goal(), financials)

        assert on_time.contribution_per_payday_sen == 5_001
        assert cash_safe.contribution_per_payday_sen == 4_000
        assert cash_safe.contribution_per_payday_sen < on_time.contribution_per_payday_sen
        assert cash_safe.flexible_spending_delta_sen == 1_001
        assert cash_safe.goal_delay_days == 30
        assert accelerated.contribution_per_payday_sen > on_time.contribution_per_payday_sen

    def test_accelerated_never_exceeds_income_or_the_50_percent_goal_limit(self):
        financials = snapshot(
            next_income_payday=IncomePayday(date(2026, 9, 5), 520_000, "income:1"),
            commitments=(),
            active_goal_plans=(),
        )
        expensive_goal = goal(
            target_amount_sen=3_000_000,
            target_date=date(2027, 3, 27),
        )

        on_time, cash_safe, accelerated = generate_goal_scenarios(
            expensive_goal, financials
        )

        assert on_time.contribution_per_payday_sen == 428_572
        assert on_time.feasible is False
        assert cash_safe.contribution_per_payday_sen < 156_000
        assert accelerated.contribution_per_payday_sen == 260_000
        assert accelerated.contribution_per_payday_sen < 520_000
        assert cash_safe.target_date > accelerated.target_date > expensive_goal.target_date
        assert "goal_contributions_high_risk" in accelerated.risk_flags

    def test_same_inputs_return_identical_plan_and_scenarios(self):
        assert calculate_goal_feasibility(goal(), snapshot()) == calculate_goal_feasibility(
            goal(), snapshot()
        )
        assert generate_goal_scenarios(goal(), snapshot()) == generate_goal_scenarios(
            goal(), snapshot()
        )
