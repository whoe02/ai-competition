import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GoalPlan } from "@kira/contracts";

import { GoalPlanPreview } from "./GoalPlanPreview";

const PLAN: GoalPlan = {
  plan_id: "11111111-1111-4111-8111-111111111111",
  goal_id: "22222222-2222-4222-8222-222222222222",
  version: 1,
  approval_status: "approved",
  feasible: true,
  target_amount_sen: 1_000_000,
  current_saved_sen: 100_000,
  remaining_amount_sen: 900_000,
  target_date: "2027-12-31",
  required_contribution_per_payday_sen: 50_000,
  next_required_reserve_sen: 50_000,
  projected_completion_date: "2027-12-31",
  milestones: [],
  risk_flags: ["goal_contributions_stretching"],
  assumptions: [],
  calculation_version: "goal-plan-v1",
  evidence_refs: [],
  monthly_income_sen: 520_000,
  monthly_protected_commitments_sen: 0,
  monthly_disposable_for_goals_sen: 520_000,
  monthly_goal_contributions_sen: 230_770,
  contribution_ratio_bp: 4_400,
  affordability_status: "high_risk",
};

describe("GoalPlanPreview", () => {
  it("uses the affordability status as the one visual risk signal", () => {
    render(<GoalPlanPreview plan={PLAN} />);

    expect(screen.queryByText("Watch-outs")).not.toBeInTheDocument();
    expect(screen.queryByText("Goal contributions stretching")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Monthly affordability")).toHaveClass("high-risk");
    expect(screen.getByText("Monthly affordability · High risk")).toBeVisible();
  });
});
