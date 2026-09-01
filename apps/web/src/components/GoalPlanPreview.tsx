import type { GoalPlan } from "@kira/contracts";

import type { GoalPlanDraft } from "../api/goals";
import { fmt } from "../lib/money";

type CalculatedPlan = GoalPlan | GoalPlanDraft;

const readable = (value: string) =>
  value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());

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

      {!compact && plan.risk_flags.length > 0 && (
        <div className="goal-notes risk" aria-label="Plan warnings">
          <b>Watch-outs</b>
          {plan.risk_flags.map((flag) => <span key={flag}>{readable(flag)}</span>)}
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
