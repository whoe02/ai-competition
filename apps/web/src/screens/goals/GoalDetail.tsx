import { useState, type FormEvent } from "react";

import type { GoalScenario } from "@kira/contracts";

import {
  approvalFromRun,
  useGoal,
  useGoalImpact,
  useGoalPlan,
  useGoalScenarios,
  useSelectGoalScenario,
} from "../../api/goalHooks";
import type { GoalApproval } from "../../api/goals";
import { GoalApprovalSheet } from "../../components/GoalApprovalSheet";
import { GoalPlanPreview, formatGoalDate } from "../../components/GoalPlanPreview";
import { fmt, parseSen } from "../../lib/money";
import { GoalScreenHead } from "./GoalCreate";
import { goalTypeLabel, statusLabel } from "./goalUi";

export function GoalDetail({ goalId, onBack }: { goalId: string; onBack: () => void }) {
  const goal = useGoal(goalId);
  const plan = useGoalPlan(goalId);
  const scenarioMutation = useGoalScenarios();
  const selectScenario = useSelectGoalScenario();
  const impact = useGoalImpact();
  const [scenarios, setScenarios] = useState<GoalScenario[] | null>(null);
  const [selected, setSelected] = useState<GoalScenario | null>(null);
  const [approval, setApproval] = useState<GoalApproval | null>(null);
  const [notice, setNotice] = useState("");
  const [spend, setSpend] = useState("");

  if (goal.isLoading || plan.isLoading) {
    return <GoalState title="Loading your goal…" detail="Reading the latest approved plan." />;
  }
  if (goal.isError || plan.isError || !goal.data || !plan.data) {
    return (
      <div className="goal-screen">
        <GoalScreenHead eyebrow="Goal detail" title="We couldn’t load this plan" onBack={onBack} />
        <div className="goal-content">
          <section className="goal-state-card error"><p>Your saved plan has not changed.</p><button className="btn btn-primary" onClick={() => void Promise.all([goal.refetch(), plan.refetch()])}>Try again</button></section>
        </div>
      </div>
    );
  }

  const detail = goal.data;
  const currentPlan = plan.data;
  const progress = currentPlan.target_amount_sen > 0
    ? Math.min(100, Math.round((currentPlan.current_saved_sen / currentPlan.target_amount_sen) * 100))
    : 0;

  const loadScenarios = async () => {
    try {
      const response = await scenarioMutation.mutateAsync(goalId);
      setScenarios(response.scenarios);
      setSelected(null);
    } catch {
      // Mutation error is rendered in place.
    }
  };

  const reviewScenario = async () => {
    if (!selected) return;
    try {
      const run = await selectScenario.mutateAsync({
        goalId,
        scenarioId: selected.scenario_id,
        label: selected.label,
      });
      const nextApproval = approvalFromRun(run);
      if (!nextApproval) throw new Error(run.errors?.join(" ") || "No approval draft returned");
      setApproval(nextApproval);
    } catch {
      // Mutation error is rendered without changing the selected active plan.
    }
  };

  const checkImpact = async (event: FormEvent) => {
    event.preventDefault();
    const proposedSpendSen = parseSen(spend);
    if (proposedSpendSen === null) return;
    try {
      await impact.mutateAsync({ goalId, proposedSpendSen });
    } catch {
      // The result area handles this and no plan mutation is possible here.
    }
  };

  return (
    <div className="goal-screen">
      <GoalScreenHead eyebrow={goalTypeLabel(detail.goal_type)} title={detail.name} onBack={onBack} />
      <div className="goal-content">
        {notice && <p className="goal-success" role="status">{notice}</p>}

        <section className="goal-detail-hero">
          <div className="goal-section-head">
            <span className={`goal-health ${detail.status === "at_risk" || detail.status === "needs_replan" ? "danger" : "healthy"}`}>
              {statusLabel(detail.status, currentPlan.feasible)}
            </span>
            <span className="goal-version">Plan v{currentPlan.version} · {currentPlan.approval_status}</span>
          </div>
          <div className="goal-progress-copy">
            <div><strong>RM{fmt(currentPlan.current_saved_sen)}</strong><span>of RM{fmt(currentPlan.target_amount_sen)}</span></div>
            <b>{progress}%</b>
          </div>
          <div className="goal-progress" role="progressbar" aria-label={`${detail.name} progress`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
            <i style={{ width: `${progress}%` }} />
          </div>
          <div className="goal-detail-dates">
            <span>Target <b>{formatGoalDate(detail.target_date)}</b></span>
            <span>Priority <b>{detail.priority}</b></span>
          </div>
        </section>

        <GoalPlanPreview plan={currentPlan} title="Approved calculation" />

        {currentPlan.milestones.length > 0 && (
          <section className="goal-milestones">
            <p className="eyebrow">Milestones</p>
            {currentPlan.milestones.map((milestone) => (
              <div key={milestone.percentage}>
                <b>{milestone.percentage}%</b>
                <span>RM{fmt(milestone.amount_sen)}</span>
                <small>{formatGoalDate(milestone.projected_date)}</small>
              </div>
            ))}
          </section>
        )}

        <section className="goal-replan-section">
          <div className="goal-section-head">
            <div><p className="eyebrow">Replan safely</p><h3>Explore backend scenarios</h3></div>
            {scenarios === null && <button className="btn btn-line btn-sm" disabled={scenarioMutation.isPending} onClick={() => void loadScenarios()}>{scenarioMutation.isPending ? "Loading…" : "View scenarios"}</button>}
          </div>
          {scenarioMutation.isError && <p className="goal-inline-error" role="alert">Alternatives could not be loaded. Your approved plan is unchanged.</p>}
          {scenarios?.length === 0 && <p className="goal-muted">No alternative scenarios were returned for this plan.</p>}
          {scenarios?.map((scenario) => (
            <button
              className={`goal-scenario-card selectable ${selected?.scenario_id === scenario.scenario_id ? "selected" : ""}`}
              type="button"
              aria-pressed={selected?.scenario_id === scenario.scenario_id}
              key={scenario.scenario_id}
              onClick={() => setSelected(scenario)}
            >
              <div className="goal-section-head">
                <b>{scenario.label}</b>
                <span className={`goal-health ${scenario.feasible ? "healthy" : "danger"}`}>{scenario.feasible ? "Feasible" : "At risk"}</span>
              </div>
              <p><strong>RM{fmt(scenario.contribution_per_payday_sen)}</strong> per payday</p>
              <small>{formatGoalDate(scenario.target_date)}{scenario.goal_delay_days > 0 ? ` · ${scenario.goal_delay_days} days later` : " · no delay"}</small>
              {scenario.tradeoffs.map((tradeoff) => <small key={tradeoff}>{tradeoff}</small>)}
            </button>
          ))}
          {selected && (
            <div className="goal-selection-review">
              <p>Selected only — your active plan has not changed.</p>
              <button className="btn btn-primary" disabled={selectScenario.isPending} onClick={() => void reviewScenario()}>
                {selectScenario.isPending ? "Recalculating…" : "Review this change"}
              </button>
            </div>
          )}
          {selectScenario.isError && <p className="goal-inline-error" role="alert">KIRA could not prepare that change. The current plan remains active.</p>}
        </section>

        <section className="goal-impact-section">
          <p className="eyebrow">Purchase impact</p>
          <h3>Would a purchase put this goal at risk?</h3>
          <form onSubmit={(event) => void checkImpact(event)}>
            <label>Purchase amount <span>RM</span><input aria-label="Purchase amount" inputMode="decimal" value={spend} onChange={(event) => setSpend(event.target.value)} /></label>
            <button className="btn btn-line" disabled={impact.isPending || parseSen(spend) === null}>{impact.isPending ? "Checking…" : "Check impact"}</button>
          </form>
          {impact.isError && <p className="goal-inline-error" role="alert">Impact could not be checked. No plan was changed.</p>}
          {impact.data && (
            <div className={`goal-impact-result ${impact.data.safe_to_spend ? "safe" : "risk"}`} role="status">
              <b>{impact.data.safe_to_spend ? "Fits safely" : "This would put the goal at risk"}</b>
              <span>Flexible spending left: RM{fmt(impact.data.flexible_spending_remaining_sen)}</span>
              {impact.data.goal_delay_days > 0 && <span>Projected delay: {impact.data.goal_delay_days} days</span>}
              {impact.data.protected_money_touched && <span>Protected money would be touched.</span>}
            </div>
          )}
        </section>
      </div>

      {approval && (
        <GoalApprovalSheet
          approval={approval}
          goalId={goalId}
          onClose={() => setApproval(null)}
          onReplacement={setApproval}
          onSettled={(result) => {
            setApproval(null);
            setSelected(null);
            setScenarios(null);
            setNotice(result === "approved" ? "Your approved plan is now updated." : "Change rejected. Your current plan is unchanged.");
          }}
        />
      )}
    </div>
  );
}

function GoalState({ title, detail }: { title: string; detail: string }) {
  return <div className="goal-content"><section className="goal-state-card"><span className="goal-loading-dot" /><h2>{title}</h2><p>{detail}</p></section></div>;
}
