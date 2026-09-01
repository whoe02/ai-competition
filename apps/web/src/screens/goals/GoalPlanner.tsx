import { useState } from "react";

import type { GoalSummary } from "@kira/contracts";

import { useGoal, useGoalPlan } from "../../api/goalHooks";
import { useDashboardToday } from "../../api/hooks";
import { formatGoalDate } from "../../components/GoalPlanPreview";
import { fmt } from "../../lib/money";
import { GoalCreate } from "./GoalCreate";
import { GoalDetail } from "./GoalDetail";
import { goalTypeLabel, statusLabel } from "./goalUi";

type GoalFilter = "all" | "short" | "long";
type GoalPage = { name: "home" } | { name: "create" } | { name: "detail"; goalId: string };

export function GoalPlanner({ onOpenForesight }: { onOpenForesight?: () => void }) {
  const [page, setPage] = useState<GoalPage>({ name: "home" });

  if (page.name === "create") {
    return (
      <GoalCreate
        onBack={() => setPage({ name: "home" })}
        onActivated={(goalId) => setPage({ name: "detail", goalId })}
      />
    );
  }
  if (page.name === "detail") {
    return <GoalDetail goalId={page.goalId} onBack={() => setPage({ name: "home" })} />;
  }
  return (
    <GoalsHome
      onCreate={() => setPage({ name: "create" })}
      onView={(goalId) => setPage({ name: "detail", goalId })}
      onOpenForesight={onOpenForesight}
    />
  );
}

function GoalsHome({
  onCreate,
  onView,
  onOpenForesight,
}: {
  onCreate: () => void;
  onView: (goalId: string) => void;
  onOpenForesight?: () => void;
}) {
  const dashboard = useDashboardToday(true);
  const [filter, setFilter] = useState<GoalFilter>("all");
  const goals = dashboard.data?.goals ?? [];
  const filtered = goals.filter((goal) => filter === "all" || goal.horizon === filter);

  return (
    <div className="goal-screen">
      <div className="goal-home-head">
        <div><p className="eyebrow">Goals</p><h1>What are you saving toward?</h1></div>
        <button className="goal-add" onClick={onCreate} aria-label="Create goal">+</button>
      </div>
      <div className="goal-content">
        <div className="goal-filter" role="group" aria-label="Filter goals">
          {(["all", "short", "long"] as GoalFilter[]).map((value) => (
            <button className={filter === value ? "selected" : ""} aria-pressed={filter === value} key={value} onClick={() => setFilter(value)}>
              {value === "all" ? "All" : value === "short" ? "Short-term" : "Long-term"}
            </button>
          ))}
        </div>

        {onOpenForesight && (
          <button className="btn btn-line goal-full-button" onClick={onOpenForesight}>
            Open Foresight
          </button>
        )}

        {dashboard.isLoading && (
          <section className="goal-state-card"><span className="goal-loading-dot" /><h2>Loading your goals…</h2><p>Reading the latest confirmed plans.</p></section>
        )}
        {dashboard.isError && (
          <section className="goal-state-card error">
            <h2>Your goals couldn’t be loaded</h2><p>Nothing has changed. Check your connection and try again.</p>
            <button className="btn btn-primary" onClick={() => void dashboard.refetch()}>Try again</button>
          </section>
        )}
        {!dashboard.isLoading && !dashboard.isError && goals.length === 0 && (
          <section className="goal-empty">
            <span className="goal-empty-mark">◎</span>
            <p className="eyebrow">A destination for your money</p>
            <h2>Start with one goal that matters</h2>
            <p>KIRA will calculate what it takes per payday while keeping protected bills and your emergency buffer untouched.</p>
            <button className="btn btn-primary" onClick={onCreate}>Create your first goal</button>
          </section>
        )}
        {!dashboard.isLoading && !dashboard.isError && goals.length > 0 && filtered.length === 0 && (
          <section className="goal-state-card"><h2>No {filter}-term goals</h2><p>Try another filter or create a new goal.</p><button className="btn btn-line" onClick={onCreate}>Create goal</button></section>
        )}
        {filtered.length > 0 && (
          <div className="goal-list">
            {filtered.map((goal, index) => (
              <GoalCard goal={goal} primary={index === 0} key={goal.id} onView={() => onView(goal.id)} />
            ))}
          </div>
        )}
        {goals.length > 0 && <button className="btn btn-primary goal-full-button" onClick={onCreate}>Create another goal</button>}
      </div>
    </div>
  );
}

function GoalCard({ goal, primary, onView }: { goal: GoalSummary; primary: boolean; onView: () => void }) {
  const detail = useGoal(goal.id);
  const plan = useGoalPlan(goal.id);
  const target = plan.data?.target_amount_sen ?? goal.target_sen;
  const saved = plan.data?.current_saved_sen ?? goal.saved_sen;
  const progress = target > 0 ? Math.min(100, Math.round((saved / target) * 100)) : 0;
  const health = detail.data ? statusLabel(detail.data.status, plan.data?.feasible) : "Loading plan";
  const danger = detail.data?.status === "at_risk" || detail.data?.status === "needs_replan" || plan.data?.feasible === false;

  return (
    <article className={`goal-card ${primary ? "primary" : "compact"}`}>
      <div className="goal-section-head">
        <span className="goal-horizon">{goal.horizon === "short" ? "Short-term" : "Long-term"}</span>
        <span className={`goal-health ${danger ? "danger" : "healthy"}`}>{health}</span>
      </div>
      <div className="goal-card-title"><div><p>{detail.data ? goalTypeLabel(detail.data.goal_type) : "Goal"}</p><h2>{goal.name}</h2></div><b>{progress}%</b></div>
      <div className="goal-progress" role="progressbar" aria-label={`${goal.name} progress`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><i style={{ width: `${progress}%` }} /></div>
      <div className="goal-card-money"><div><span>Saved</span><strong>RM{fmt(saved)}</strong></div><div><span>Target</span><strong>RM{fmt(target)}</strong></div></div>
      {primary && (
        <div className="goal-card-plan">
          <span>Remaining <b>{plan.data ? `RM${fmt(plan.data.remaining_amount_sen)}` : "Loading…"}</b></span>
          <span>Per payday <b>{plan.data ? `RM${fmt(plan.data.required_contribution_per_payday_sen)}` : "Loading…"}</b></span>
          <span>Target date <b>{formatGoalDate(detail.data?.target_date ?? null)}</b></span>
        </div>
      )}
      {(detail.isError || plan.isError) && <p className="goal-card-warning">Some plan details are temporarily unavailable.</p>}
      <button className={`btn ${primary ? "btn-brass" : "btn-line"} goal-full-button`} onClick={onView}>View plan</button>
    </article>
  );
}

export { goalTypeLabel, statusLabel } from "./goalUi";
