import type { GoalPlan } from "@kira/contracts";

import type { GoalPlanDraft } from "../api/goals";
import { fmt } from "../lib/money";

type CalculatedPlan = GoalPlan | GoalPlanDraft;

const readable = (value: string) =>
  value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());

const affordabilityLabel = (value: string) => {
  const labels: Record<string, string> = {
    comfortable: "Comfortable",
    stretching: "Stretching",
    high_risk: "High risk",
    unsustainable: "Unsustainable",
    impossible: "Not possible",
    income_unavailable: "Income needed",
  };
  return labels[value] ?? readable(value);
};

const affordabilityTone = (value: string) => {
  const tones: Record<string, string> = {
    comfortable: "comfortable",
    stretching: "stretching",
    high_risk: "high-risk",
    unsustainable: "unsustainable",
    impossible: "unsustainable",
    income_unavailable: "income-unavailable",
  };
  return tones[value] ?? "income-unavailable";
};

export function formatGoalDate(value: string | null): string {
  if (!value) return "Not available";
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return value;
  return new Intl.DateTimeFormat("en-MY", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(year, month - 1, day));
}

export function GoalPlanPreview({
  plan,
  title = "Calculated plan",
  compact = false,
}: {
  plan: CalculatedPlan;
  title?: string;
  compact?: boolean;
}) {
  return (
    <section className={`goal-plan-preview ${compact ? "compact" : ""}`}>
      <div className="goal-section-head">
        <p className="eyebrow">{title}</p>
        <span className={`goal-health ${plan.feasible ? "healthy" : "danger"}`}>
          {plan.feasible ? "Feasible" : "Needs adjustment"}
        </span>
      </div>

      <div className="goal-plan-lead">
        <span>{plan.feasible ? "Per payday" : "Current requirement"}</span>
        <strong>RM{fmt(plan.required_contribution_per_payday_sen)}</strong>
        <small>
          {plan.feasible ? "On track with this backend-calculated reserve" : "This target needs adjustment"}
        </small>
      </div>

      <dl className="goal-metrics">
        <div><dt>Target</dt><dd>RM{fmt(plan.target_amount_sen)}</dd></div>
        <div><dt>Already saved</dt><dd>RM{fmt(plan.current_saved_sen)}</dd></div>
        <div><dt>Remaining</dt><dd>RM{fmt(plan.remaining_amount_sen)}</dd></div>
        <div><dt>Next reserve</dt><dd>RM{fmt(plan.next_required_reserve_sen)}</dd></div>
        <div><dt>Target date</dt><dd>{formatGoalDate(plan.target_date)}</dd></div>
        <div><dt>Projected</dt><dd>{formatGoalDate(plan.projected_completion_date)}</dd></div>
      </dl>

      {!compact && plan.monthly_income_sen !== null && (
        <section
          className={`goal-notes affordability ${affordabilityTone(plan.affordability_status)}`}
          aria-label="Monthly affordability"
        >
          <b>Monthly affordability · {affordabilityLabel(plan.affordability_status)}</b>
          <span>Income: RM{fmt(plan.monthly_income_sen)}</span>
          <span>Protected commitments: RM{fmt(plan.monthly_protected_commitments_sen)}</span>
          <span>Goal contributions: RM{fmt(plan.monthly_goal_contributions_sen)}{plan.contribution_ratio_bp !== null ? ` (${(plan.contribution_ratio_bp / 100).toFixed(0)}%)` : ""}</span>
          <span>Disposable for goals: RM{fmt(plan.monthly_disposable_for_goals_sen)}</span>
        </section>
      )}
      {!compact && plan.monthly_income_sen === null && (
        <div className="goal-notes risk" aria-label="Income needed for affordability">
          <b>Income needed</b>
          <span>Add confirmed recurring income to calculate affordability.</span>
        </div>
      )}

      {!compact && plan.assumptions.length > 0 && (
        <div className="goal-notes" aria-label="Plan assumptions">
          <b>Assumptions</b>
          {plan.assumptions.map((assumption) => <span key={assumption}>{readable(assumption)}</span>)}
        </div>
      )}
    </section>
  );
}
