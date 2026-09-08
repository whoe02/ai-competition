import { useState } from "react";

import type { GoalScenario, PartTimeJobRecommendation } from "@kira/contracts";

import {
  approvalFromRun,
  useGoal,
  useGoalPlan,
  useGoalScenarios,
  useApprovePartTimeRecommendation,
  usePartTimeRecommendation,
  useSelectGoalScenario,
} from "../../api/goalHooks";
import type { GoalApproval } from "../../api/goals";
import { GoalApprovalSheet } from "../../components/GoalApprovalSheet";
import { GoalPlanPreview, formatGoalDate } from "../../components/GoalPlanPreview";
import { fmt } from "../../lib/money";
import { GoalScreenHead } from "./GoalCreate";
import { goalTypeLabel, statusLabel } from "./goalUi";

export function GoalDetail({ goalId, onBack }: { goalId: string; onBack: () => void }) {
  const goal = useGoal(goalId);
  const plan = useGoalPlan(goalId);
  const scenarioMutation = useGoalScenarios();
  const selectScenario = useSelectGoalScenario();
  const partTimeMutation = usePartTimeRecommendation();
  const approvePartTime = useApprovePartTimeRecommendation();
  const [scenarios, setScenarios] = useState<GoalScenario[] | null>(null);
  const [selected, setSelected] = useState<GoalScenario | null>(null);
  const [approval, setApproval] = useState<GoalApproval | null>(null);
  const [notice, setNotice] = useState("");
  const [partTime, setPartTime] = useState<PartTimeJobRecommendation | null>(null);

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

  const loadPartTimeRecommendation = async () => {
    try {
      setPartTime(await partTimeMutation.mutateAsync(goalId));
    } catch {
      // The error state keeps the approved plan untouched and visible.
    }
  };

  const approvePartTimeRecommendation = async () => {
    try {
      const approved = await approvePartTime.mutateAsync(goalId);
      setPartTime(approved);
      setNotice("Part-time income is now included in future goal forecasts. Today’s cash is unchanged.");
    } catch {
      // The error state explains that no forecast change was made.
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

        {shouldOfferPartTime(currentPlan) && (
          <section className="goal-part-time-section" aria-label="Part-time work reminder">
            <div className="goal-section-head">
              <div><p className="eyebrow">Goal boost</p><h3>Could part-time work help?</h3></div>
              <span className="goal-health danger">Optional</span>
            </div>
            {partTime === null && (
              <>
                <p className="goal-muted">Kira can suggest one flexible work type and show the forecast effect before you decide.</p>
                <button className="btn btn-line btn-sm" disabled={partTimeMutation.isPending} onClick={() => void loadPartTimeRecommendation()}>
                  {partTimeMutation.isPending ? "Preparing…" : "See a work idea"}
                </button>
              </>
            )}
            {partTimeMutation.isError && <p className="goal-inline-error" role="alert">Kira could not prepare a recommendation. Your plan is unchanged.</p>}
            {partTime?.status === "not_needed" || partTime?.status === "not_available" ? (
              <p className="goal-muted">{partTime.reason}</p>
            ) : partTime && (
              <div className="goal-part-time-card">
                <p className="eyebrow">{partTime.source === "llm" ? "AI work idea" : "Work idea"}</p>
                <h4>{partTime.role_title}</h4>
                <p>{partTime.summary}</p>
                <p className="goal-part-time-step"><b>First step</b>{partTime.first_step}</p>
                <div className="goal-part-time-impact">
                  <span>Income forecast <b>RM{fmt(partTime.monthly_income_before_sen ?? 0)} → RM{fmt(partTime.monthly_income_after_sen ?? 0)}</b></span>
                  <span>Goal contribution share <b>{formatRatio(partTime.contribution_ratio_before_bp)} → {formatRatio(partTime.contribution_ratio_after_bp)}</b></span>
                  <span>Plan after approval <b>{partTime.feasible_after ? "Feasible" : "Still needs adjustment"}</b></span>
                </div>
                {(partTime.cautions ?? []).map((caution) => <small key={caution}>{caution}</small>)}
                {partTime.status === "available" ? (
                  <div className="goal-part-time-actions">
                    <button className="btn btn-primary btn-sm" disabled={approvePartTime.isPending} onClick={() => void approvePartTimeRecommendation()}>
                      {approvePartTime.isPending ? "Approving…" : "Approve this forecast"}
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setPartTime(null)}>Not now</button>
                  </div>
                ) : (
                  <p className="goal-success" role="status">Approved for future forecasts. Safe to Spend stays unchanged until income is confirmed.</p>
                )}
                {approvePartTime.isError && <p className="goal-inline-error" role="alert">This recommendation could not be approved. Your forecast is unchanged.</p>}
              </div>
            )}
          </section>
        )}

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

function shouldOfferPartTime(plan: { feasible: boolean; affordability_status: string; projected_completion_date: string | null; target_date: string }) {
  return !plan.feasible
    || ["high_risk", "unsustainable", "impossible"].includes(plan.affordability_status)
    || (plan.projected_completion_date !== null && plan.projected_completion_date > plan.target_date);
}

function formatRatio(value: number | null | undefined): string {
  return value == null ? "—" : `${(value / 100).toFixed(0)}%`;
}

function GoalState({ title, detail }: { title: string; detail: string }) {
  return <div className="goal-content"><section className="goal-state-card"><span className="goal-loading-dot" /><h2>{title}</h2><p>{detail}</p></section></div>;
}
