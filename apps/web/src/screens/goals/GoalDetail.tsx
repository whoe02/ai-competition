import { useEffect, useRef, useState } from "react";

import type { GoalScenario, PartTimeJobRecommendation } from "@kira/contracts";

import {
  approvalFromRun,
  useGoal,
  useGoalPlan,
  useGoalScenarios,
  usePartTimeRecommendation,
  useStoredPartTimeRecommendation,
  useSelectGoalScenario,
} from "../../api/goalHooks";
import type { GoalApproval } from "../../api/goals";
import { GoalApprovalSheet } from "../../components/GoalApprovalSheet";
import { IcCheck } from "../../components/Icons";
import { GoalPlanPreview, formatGoalDate } from "../../components/GoalPlanPreview";
import { fmt } from "../../lib/money";
import { GoalScreenHead } from "./GoalCreate";
import { goalTypeLabel, statusLabel } from "./goalUi";

export function GoalDetail({
  goalId,
  onBack,
  initialShowRecommendations = false,
  initialFocusPartTime = false,
}: {
  goalId: string;
  onBack: () => void;
  initialShowRecommendations?: boolean;
  initialFocusPartTime?: boolean;
}) {
  const goal = useGoal(goalId);
  const plan = useGoalPlan(goalId);
  const scenarioMutation = useGoalScenarios();
  const selectScenario = useSelectGoalScenario();
  const partTimeMutation = usePartTimeRecommendation();
  const storedPartTime = useStoredPartTimeRecommendation(goalId);
  const [scenarios, setScenarios] = useState<GoalScenario[] | null>(null);
  const [selected, setSelected] = useState<GoalScenario | null>(null);
  const [approval, setApproval] = useState<GoalApproval | null>(null);
  const [notice, setNotice] = useState("");
  const [partTime, setPartTime] = useState<PartTimeJobRecommendation | null>(null);
  const [availableHours, setAvailableHours] = useState("8");
  const [workMode, setWorkMode] = useState<"remote" | "on_site" | "either">("either");
  const [transportLimitations, setTransportLimitations] = useState("");
  const [showRecommendations, setShowRecommendations] = useState(initialShowRecommendations);
  const [highlightPartTime, setHighlightPartTime] = useState(false);
  const partTimeSectionRef = useRef<HTMLElement>(null);
  const focusedPartTimeRef = useRef(false);
  const shouldFocusPartTimeRef = useRef(initialFocusPartTime);

  useEffect(() => {
    // The response to the user's latest search is authoritative. A slower
    // initial GET may contain an older saved recommendation and must not
    // replace it after the POST completes.
    if (partTimeMutation.data) return;
    const stored = storedPartTime.data;
    if (stored) {
      setPartTime((current) => current ?? stored);
      setAvailableHours(String(stored.preferences.available_hours_per_week));
      setWorkMode(stored.preferences.work_mode);
      setTransportLimitations(stored.preferences.transport_limitations);
    } else if (storedPartTime.isSuccess) {
      setPartTime(null);
    }
  }, [storedPartTime.data, storedPartTime.isSuccess, partTimeMutation.data]);

  useEffect(() => {
    if (!shouldFocusPartTimeRef.current || !goal.isSuccess || !plan.isSuccess || focusedPartTimeRef.current) return;
    focusedPartTimeRef.current = true;
    setHighlightPartTime(true);
    const frame = window.requestAnimationFrame(() => {
      partTimeSectionRef.current?.scrollIntoView?.({ behavior: "smooth", block: "center" });
    });
    const timer = window.setTimeout(() => setHighlightPartTime(false), 2800);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [goal.isSuccess, plan.isSuccess]);

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
    } catch {
      // The error state keeps the approved plan untouched and visible.
    }
  };

  if (showRecommendations && partTime?.status === "available") {
    return (
      <PartTimeRecommendationPage
        goalName={detail.name}
        recommendation={partTime}
        onBack={() => setShowRecommendations(false)}
        onRecommendAgain={() => void loadPartTimeRecommendation()}
        isRefreshing={partTimeMutation.isPending}
        refreshFailed={partTimeMutation.isError}
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
          </div>
        </section>

        <GoalPlanPreview plan={currentPlan} title="Approved calculation" />

        {currentPlan.remaining_amount_sen > 0 && (
          <section
            ref={partTimeSectionRef}
            className={`goal-part-time-section ${highlightPartTime ? "goal-part-time-highlight" : ""}`}
            aria-label="Part-time work reminder"
          >
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
              <div className="goal-part-time-empty" role="status">
                <b>No suitable live match yet</b>
                <p className="goal-muted">{partTime.reason}</p>
                <button
                  className="btn btn-line btn-sm"
                  disabled={partTimeMutation.isPending}
                  onClick={() => void loadPartTimeRecommendation()}
                >
                  {partTimeMutation.isPending ? "Searching related roles…" : "Search related roles again"}
                </button>
              </div>
            ) : partTime && (
              <div className="goal-part-time-ready">
                <span className="goal-part-time-ready-mark"><IcCheck size={15} /></span>
                <div><b>Three work ideas are ready</b><p>Includes estimated pay and goal-date effects.</p></div>
                <div className="goal-part-time-ready-actions">
                  <button className="btn btn-primary btn-sm" onClick={() => setShowRecommendations(true)}>View ideas</button>
                  <button className="btn btn-line btn-sm" disabled={partTimeMutation.isPending} onClick={() => void loadPartTimeRecommendation()}>
                    {partTimeMutation.isPending ? "Searching…" : "Find different jobs"}
                  </button>
                </div>
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
                <span className={`goal-health ${scenarioHealth(scenario).tone}`}>{scenarioHealth(scenario).label}</span>
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

function scenarioHealth(scenario: GoalScenario): { tone: "healthy" | "warning" | "danger"; label: string } {
  if (scenario.risk_flags.includes("goal_contributions_high_risk")) {
    return { tone: "danger", label: "High risk" };
  }
  if (scenario.risk_flags.includes("goal_contributions_stretching")) {
    return { tone: "warning", label: "Stretching" };
  }
  return scenario.feasible
    ? { tone: "healthy", label: "Feasible" }
    : { tone: "danger", label: "At risk" };
}

function PartTimeRecommendationPage({
  goalName,
  recommendation,
  onBack,
  onRecommendAgain,
  isRefreshing,
  refreshFailed,
}: {
  goalName: string;
  recommendation: PartTimeJobRecommendation;
  onBack: () => void;
  onRecommendAgain: () => void;
  isRefreshing: boolean;
  refreshFailed: boolean;
}) {
  return (
    <div className="goal-screen goal-recommendations-page">
      <GoalScreenHead eyebrow="Goal boost" title="Work ideas for your goal" onBack={onBack} />
      <div className="goal-content">
        <section className="goal-recommendations-hero">
          <p className="eyebrow">{goalName}</p>
          <h2>Three ways to explore</h2>
          <p>{recommendation.overall_guidance ?? "Choose only an option that fits your life and commitments."}</p>
          <div className="goal-recommendations-refresh">
            <button className="btn btn-sm" disabled={isRefreshing} onClick={onRecommendAgain}>
              {isRefreshing ? "Searching live jobs…" : "Show me different jobs"}
            </button>
            <small>We’ll search the live job boards again and avoid these listings.</small>
          </div>
        </section>
        {refreshFailed && <p className="goal-inline-error" role="alert">Kira could not refresh the live jobs. Your current recommendations are still here.</p>}
        <div className="goal-part-time-options">
          {(recommendation.recommendations ?? []).map((item, index) => (
            <article className="goal-part-time-option" key={`${item.role_title}-${index}`}>
              <div className="goal-section-head">
                <span className="goal-part-time-number">{index + 1}</span>
                <span>{item.work_arrangement}</span>
              </div>
              <h3>{item.role_title}</h3>
              <p className="goal-part-time-source">{item.job_company} · {item.job_location} · via {item.job_source === "arbeitnow" ? "Arbeitnow" : "Remotive"}</p>
              <a
                className="btn btn-line btn-sm goal-part-time-apply"
                href={item.apply_url}
                target="_blank"
                rel="noreferrer"
              >
                View & apply on {item.job_source === "arbeitnow" ? "Arbeitnow" : "Remotive"}
              </a>
              <dl>
                <div><dt>Typical work</dt><dd>{item.typical_tasks}</dd></div>
                <div><dt>Why it fits</dt><dd>{item.why_relevant}</dd></div>
                <div><dt>First step</dt><dd>{item.first_step}</dd></div>
              </dl>
              <div className="goal-part-time-pay">
                <div><span>Estimated hourly</span><b>{moneyRange(item.estimated_hourly_rate_min_sen, item.estimated_hourly_rate_max_sen)}</b></div>
                <div><span>Per work day</span><b>{moneyRange(item.estimated_daily_income_min_sen, item.estimated_daily_income_max_sen)}</b></div>
                <div><span>Per week</span><b>{moneyRange(item.estimated_weekly_income_min_sen, item.estimated_weekly_income_max_sen)}</b></div>
                <div><span>Per month</span><b>{moneyRange(item.estimated_monthly_income_min_sen, item.estimated_monthly_income_max_sen)}</b></div>
              </div>
              <p className="goal-part-time-basis">
                {item.suggested_hours_per_week} hours across {item.suggested_work_days_per_week} {item.suggested_work_days_per_week === 1 ? "day" : "days"} weekly · {item.pay_estimate_basis}
              </p>
              <div className="goal-part-time-forecast">
                <p className="eyebrow">Estimated goal effect</p>
                <div className="goal-part-time-comparison">
                  <p>Monthly goal saving</p>
                  <div>
                    <span><small>Current plan</small><b>RM{fmt(item.goal_contribution_monthly_before_sen)}</b></span>
                    <span className="projected"><small>With this job</small><b>{moneyRangeWithTo(item.goal_contribution_monthly_with_job_min_sen, item.goal_contribution_monthly_with_job_max_sen)}</b></span>
                  </div>
                </div>
                <div className="goal-part-time-comparison">
                  <p>Estimated goal completion</p>
                  <div>
                    <span><small>Current plan</small><b>{formatGoalDate(recommendation.projected_completion_before ?? null)}</b></span>
                    <span className="projected"><small>With this job</small><b>{completionWindow(item.projected_completion_with_max_income, item.projected_completion_with_min_income)}</b></span>
                  </div>
                </div>
                <div className="goal-part-time-benefits">
                  <span><small>Finish your goal earlier by</small><b>{daysRange(item.days_saved_min, item.days_saved_max)}</b></span>
                  <span><small>Estimated daily capacity after goal completion</small><b>{moneyRange(item.future_daily_safe_to_spend_increase_min_sen, item.future_daily_safe_to_spend_increase_max_sen)} per day</b></span>
                </div>
                <p className="goal-part-time-capacity-note">
                  Forecast only — it combines this job’s estimated income with the RM{fmt(item.goal_contribution_monthly_before_sen)} monthly amount that is no longer reserved once this goal is complete. It does not change today’s Safe to Spend.
                </p>
              </div>
              {(item.cautions ?? []).map((caution) => <small key={caution}>{caution}</small>)}
            </article>
          ))}
        </div>
        <section className="goal-part-time-card">
          <p className="eyebrow">How to read this forecast</p>
          <p className="goal-muted">Pay is an AI estimate before costs or tax, not a guaranteed offer. Calculations assume all side income goes to this goal.</p>
          <p className="goal-muted">Daily capacity is a future estimate only: it applies after the goal finishes, if the work continues and your commitments remain unchanged. Your Safe to Spend today is not changed.</p>
        </section>
      </div>
    </div>
  );
}

function moneyRange(minimum: number, maximum: number): string {
  const low = `RM${fmt(minimum)}`;
  return minimum === maximum ? low : `${low}–RM${fmt(maximum)}`;
}

function moneyRangeWithTo(minimum: number, maximum: number): string {
  const low = `RM${fmt(minimum)}`;
  return minimum === maximum ? low : `${low} to RM${fmt(maximum)}`;
}

function completionWindow(earliest: string | null, latest: string | null): string {
  if (!earliest && !latest) return "Not available";
  if (earliest === latest || !latest) return formatGoalDate(earliest);
  if (!earliest) return formatGoalDate(latest);
  return `${formatGoalDate(earliest)} to ${formatGoalDate(latest)}`;
}

function daysRange(minimum: number | null, maximum: number | null): string {
  if (minimum == null && maximum == null) return "Not available";
  const low = minimum ?? maximum ?? 0;
  const high = maximum ?? minimum ?? 0;
  return low === high ? `${low} days` : `${low}–${high} days`;
}

function validAvailableHours(value: string): boolean {
  const hours = Number.parseInt(value, 10);
  return Number.isInteger(hours) && hours >= 1 && hours <= 40;
}

function GoalState({ title, detail }: { title: string; detail: string }) {
  return <div className="goal-content"><section className="goal-state-card"><span className="goal-loading-dot" /><h2>{title}</h2><p>{detail}</p></section></div>;
}
