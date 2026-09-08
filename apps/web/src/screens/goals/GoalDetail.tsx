import { useState } from "react";

import type { GoalScenario, PartTimeJobRecommendation } from "@kira/contracts";

import {
  approvalFromRun,
  useGoal,
  useGoalPlan,
  useGoalScenarios,
  usePartTimeRecommendationImpact,
  usePartTimeRecommendation,
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
  const partTimeMutation = usePartTimeRecommendation();
  const partTimeImpact = usePartTimeRecommendationImpact();
  const [scenarios, setScenarios] = useState<GoalScenario[] | null>(null);
  const [selected, setSelected] = useState<GoalScenario | null>(null);
  const [approval, setApproval] = useState<GoalApproval | null>(null);
  const [notice, setNotice] = useState("");
  const [partTime, setPartTime] = useState<PartTimeJobRecommendation | null>(null);
  const [expectedIncome, setExpectedIncome] = useState("");
  const [availableHours, setAvailableHours] = useState("8");
  const [workMode, setWorkMode] = useState<"remote" | "on_site" | "either">("either");
  const [transportLimitations, setTransportLimitations] = useState("");

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
    const parsedHours = Number.parseInt(availableHours, 10);
    if (!Number.isInteger(parsedHours) || parsedHours < 1 || parsedHours > 40) return;
    try {
      setPartTime(await partTimeMutation.mutateAsync({
        goalId,
        availableHoursPerWeek: parsedHours,
        workMode,
        transportLimitations: transportLimitations.trim(),
      }));
    } catch {
      // The error state keeps the approved plan untouched and visible.
    }
  };

  const previewPartTimeImpact = async () => {
    const expectedMonthlyIncomeSen = parseSen(expectedIncome);
    if (expectedMonthlyIncomeSen === null) return;
    try {
      setPartTime(await partTimeImpact.mutateAsync({ goalId, expectedMonthlyIncomeSen }));
    } catch {
      // This read-only preview never changes the active plan.
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
                <p className="goal-muted">Kira uses your job title and availability to suggest three suitable ways to earn extra income.</p>
                <div className="goal-part-time-preferences">
                  <label>Available hours each week
                    <input type="number" inputMode="numeric" min={1} max={40} value={availableHours} onChange={(event) => setAvailableHours(event.target.value)} />
                  </label>
                  <label>Work preference
                    <select value={workMode} onChange={(event) => setWorkMode(event.target.value as typeof workMode)}>
                      <option value="either">Remote or on-site</option>
                      <option value="remote">Remote only</option>
                      <option value="on_site">On-site only</option>
                    </select>
                  </label>
                  <label className="goal-part-time-wide">Transport limitations (optional)
                    <input maxLength={200} placeholder="e.g. No car; public transport only" value={transportLimitations} onChange={(event) => setTransportLimitations(event.target.value)} />
                  </label>
                </div>
                <button className="btn btn-line btn-sm" disabled={partTimeMutation.isPending || !validAvailableHours(availableHours)} onClick={() => void loadPartTimeRecommendation()}>
                  {partTimeMutation.isPending ? "Preparing…" : "See work recommendations"}
                </button>
              </>
            )}
            {partTimeMutation.isError && <p className="goal-inline-error" role="alert">Kira could not prepare a recommendation. Your plan is unchanged.</p>}
            {partTime?.status === "not_available" ? (
              <p className="goal-muted">{partTime.reason}</p>
            ) : partTime && (
              <div className="goal-part-time-card">
                <p className="eyebrow">AI work ideas</p>
                {partTime.overall_guidance && <p>{partTime.overall_guidance}</p>}
                <div className="goal-part-time-options">
                  {(partTime.recommendations ?? []).map((recommendation, index) => (
                    <article className="goal-part-time-option" key={`${recommendation.role_title}-${index}`}>
                      <div className="goal-section-head"><span className="goal-part-time-number">{index + 1}</span><span>{recommendation.work_arrangement}</span></div>
                      <h4>{recommendation.role_title}</h4>
                      <p><b>Typical work</b>{recommendation.typical_tasks}</p>
                      <p><b>Why it fits</b>{recommendation.why_relevant}</p>
                      <p><b>First step</b>{recommendation.first_step}</p>
                      {(recommendation.cautions ?? []).map((caution) => <small key={caution}>{caution}</small>)}
                    </article>
                  ))}
                </div>
                <label className="goal-part-time-input">Your realistic monthly side-income estimate (RM)
                  <input inputMode="decimal" placeholder="e.g. 800.00" value={expectedIncome} onChange={(event) => setExpectedIncome(event.target.value)} />
                </label>
                {partTime.monthly_income_after_sen !== undefined && partTime.monthly_income_after_sen !== null && <div className="goal-part-time-impact">
                  <span>Income scenario <b>RM{fmt(partTime.monthly_income_before_sen ?? 0)} → RM{fmt(partTime.monthly_income_after_sen)}</b></span>
                  <span>Goal contribution share <b>{formatRatio(partTime.contribution_ratio_before_bp)} → {formatRatio(partTime.contribution_ratio_after_bp)}</b></span>
                  <span>Plan with this estimate <b>{partTime.feasible_after ? "Feasible" : "Still needs adjustment"}</b></span>
                </div>}
                <div className="goal-part-time-actions"><button className="btn btn-primary btn-sm" disabled={partTimeImpact.isPending || parseSen(expectedIncome) === null} onClick={() => void previewPartTimeImpact()}>{partTimeImpact.isPending ? "Checking…" : "Show scenario effect"}</button><button className="btn btn-ghost btn-sm" onClick={() => setPartTime(null)}>Close</button></div>
                <p className="goal-muted">This is a recommendation only. It does not create income or change your plan.</p>
                {partTimeImpact.isError && <p className="goal-inline-error" role="alert">Kira could not preview that amount. Your plan is unchanged.</p>}
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

function shouldOfferPartTime(plan: { remaining_amount_sen: number; contribution_ratio_bp: number | null }) {
  return plan.remaining_amount_sen > 0
    && plan.contribution_ratio_bp !== null
    && plan.contribution_ratio_bp < 6_000;
}

function validAvailableHours(value: string): boolean {
  const hours = Number.parseInt(value, 10);
  return Number.isInteger(hours) && hours >= 1 && hours <= 40;
}

function formatRatio(value: number | null | undefined): string {
  return value == null ? "—" : `${(value / 100).toFixed(0)}%`;
}

function GoalState({ title, detail }: { title: string; detail: string }) {
  return <div className="goal-content"><section className="goal-state-card"><span className="goal-loading-dot" /><h2>{title}</h2><p>{detail}</p></section></div>;
}
