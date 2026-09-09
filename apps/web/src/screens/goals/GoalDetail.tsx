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
import { IcCheck, IcChev } from "../../components/Icons";
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
  const [recommendationsReady, setRecommendationsReady] = useState(false);
  const [showRecommendations, setShowRecommendations] = useState(false);

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
      const result = await partTimeMutation.mutateAsync({
        goalId,
        availableHoursPerWeek: parsedHours,
        workMode,
        transportLimitations: transportLimitations.trim(),
      });
      setPartTime(result);
      setRecommendationsReady(result.status === "available");
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

  if (showRecommendations && partTime?.status === "available") {
    return (
      <PartTimeRecommendationPage
        goalName={detail.name}
        recommendation={partTime}
        expectedIncome={expectedIncome}
        onExpectedIncomeChange={setExpectedIncome}
        impactPending={partTimeImpact.isPending}
        impactError={partTimeImpact.isError}
        onPreview={() => void previewPartTimeImpact()}
        onBack={() => setShowRecommendations(false)}
      />
    );
  }

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
              <div className="goal-part-time-ready">
                <span className="goal-part-time-ready-mark"><IcCheck size={15} /></span>
                <div><b>Three work ideas are ready</b><p>Built around your availability and work preferences.</p></div>
                <button className="btn btn-primary btn-sm" onClick={() => setShowRecommendations(true)}>View ideas</button>
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
      {recommendationsReady && partTime?.status === "available" && (
        <button
          className="goal-recommendations-toast"
          type="button"
          onClick={() => {
            setRecommendationsReady(false);
            setShowRecommendations(true);
          }}
        >
          <span className="goal-recommendations-toast-mark"><IcCheck size={16} /></span>
          <span><b>Recommendations ready</b><small>Tap to view 3 work ideas for {detail.name}</small></span>
          <IcChev size={18} />
        </button>
      )}
    </div>
  );
}

function PartTimeRecommendationPage({
  goalName,
  recommendation,
  expectedIncome,
  onExpectedIncomeChange,
  impactPending,
  impactError,
  onPreview,
  onBack,
}: {
  goalName: string;
  recommendation: PartTimeJobRecommendation;
  expectedIncome: string;
  onExpectedIncomeChange: (value: string) => void;
  impactPending: boolean;
  impactError: boolean;
  onPreview: () => void;
  onBack: () => void;
}) {
  return (
    <div className="goal-screen goal-recommendations-page">
      <GoalScreenHead eyebrow="Goal boost" title="Work ideas for your goal" onBack={onBack} />
      <div className="goal-content">
        <section className="goal-recommendations-hero">
          <p className="eyebrow">{goalName}</p>
          <h2>Three ways to explore</h2>
          <p>{recommendation.overall_guidance ?? "Choose only an option that fits your life and commitments."}</p>
        </section>
        <div className="goal-part-time-options">
          {(recommendation.recommendations ?? []).map((item, index) => (
            <article className="goal-part-time-option" key={`${item.role_title}-${index}`}>
              <div className="goal-section-head">
                <span className="goal-part-time-number">{index + 1}</span>
                <span>{item.work_arrangement}</span>
              </div>
              <h3>{item.role_title}</h3>
              <dl>
                <div><dt>Typical work</dt><dd>{item.typical_tasks}</dd></div>
                <div><dt>Why it fits</dt><dd>{item.why_relevant}</dd></div>
                <div><dt>First step</dt><dd>{item.first_step}</dd></div>
              </dl>
              {(item.cautions ?? []).map((caution) => <small key={caution}>{caution}</small>)}
            </article>
          ))}
        </div>
        <section className="goal-part-time-card">
          <p className="eyebrow">Optional scenario</p>
          <label className="goal-part-time-input">Your realistic monthly side-income estimate (RM)
            <input inputMode="decimal" placeholder="e.g. 800.00" value={expectedIncome} onChange={(event) => onExpectedIncomeChange(event.target.value)} />
          </label>
          {recommendation.monthly_income_after_sen !== undefined && recommendation.monthly_income_after_sen !== null && <div className="goal-part-time-impact">
            <span>Income scenario <b>RM{fmt(recommendation.monthly_income_before_sen ?? 0)} → RM{fmt(recommendation.monthly_income_after_sen)}</b></span>
            <span>Goal contribution share <b>{formatRatio(recommendation.contribution_ratio_before_bp)} → {formatRatio(recommendation.contribution_ratio_after_bp)}</b></span>
            <span>Plan with this estimate <b>{recommendation.feasible_after ? "Feasible" : "Still needs adjustment"}</b></span>
          </div>}
          <button className="btn btn-primary btn-sm" disabled={impactPending || parseSen(expectedIncome) === null} onClick={onPreview}>{impactPending ? "Checking…" : "Show scenario effect"}</button>
          <p className="goal-muted">This is a recommendation only. It does not create income or change your plan.</p>
          {impactError && <p className="goal-inline-error" role="alert">Kira could not preview that amount. Your plan is unchanged.</p>}
        </section>
      </div>
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
