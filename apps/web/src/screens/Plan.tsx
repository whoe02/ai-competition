import { useEffect, useState } from "react";

import type { ForesightDriver, ForesightResponse, GoalSummary } from "@kira/contracts";

import { FanChart } from "../components/FanChart";
import { Reveal } from "../components/Reveal";
import { fmt } from "../lib/money";
import { DayPlan } from "./DayPlan";
import { GoalPlanner } from "./goals/GoalPlanner";

export type PlanView = "daily" | "goals" | "foresight";

type PlanProps = {
  initialView?: PlanView;
  data?: ForesightResponse;
  goals?: GoalSummary[];
  isLoading?: boolean;
  isError?: boolean;
  onDriver?: (driver: ForesightDriver) => void;
  recommendationGoalId?: string;
  onRecommendationOpened?: () => void;
};

function percent(basisPoints: number): string {
  return `${Math.round(basisPoints / 100)}%`;
}

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("en-MY", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(`${iso}T00:00:00`));
}

function driverCopy(driver: ForesightDriver, goalNames: Map<string, string>): string {
  const amount = `RM${fmt(Math.abs(driver.lever.delta.sen))}`;
  if (driver.lever.kind === "goal_monthly") {
    const name = goalNames.get(driver.lever.target_id) ?? "this goal";
    return `${driver.lever.delta.sen >= 0 ? "Put" : "Take"} ${amount} ${driver.lever.delta.sen >= 0 ? "more into" : "out of"} ${name} each month`;
  }
  if (driver.lever.kind === "daily_spend") {
    return `Spend ${amount} ${driver.lever.delta.sen < 0 ? "less" : "more"} each day`;
  }
  return `${driver.lever.delta.sen < 0 ? "Reduce" : "Raise"} a commitment by ${amount}`;
}

function outlookLabel(probabilityBp: number): string {
  if (probabilityBp >= 7_000) return "On track";
  if (probabilityBp >= 4_000) return "Needs attention";
  return "Unlikely at this pace";
}

/** Shared PLAN shell. Foresight belongs inside Goals, not in bottom navigation. */
export function Plan({
  initialView = "daily",
  data,
  goals = [],
  isLoading = false,
  isError = false,
  onDriver = () => undefined,
  recommendationGoalId,
  onRecommendationOpened,
}: PlanProps) {
  const [view, setView] = useState<PlanView>(initialView);

  useEffect(() => {
    setView(initialView);
  }, [initialView]);

  const selectView = (next: PlanView) => setView(next);

  return (
    <>
      <div className="plan-view-switch">
        <div className="seg-toggle" role="tablist" aria-label="Plan view">
          <span
            className="seg-thumb"
            aria-hidden="true"
            style={{
              transform:
                view !== "daily" ? "translateX(calc(100% + 5px))" : "translateX(0)",
            }}
          />
          <button
            id="plan-daily-tab"
            className={`seg-btn ${view === "daily" ? "on" : ""}`}
            type="button"
            role="tab"
            aria-selected={view === "daily"}
            aria-controls="plan-daily-panel"
            onClick={() => selectView("daily")}
          >
            Daily
          </button>
          <button
            id="plan-goals-tab"
            className={`seg-btn ${view !== "daily" ? "on" : ""}`}
            type="button"
            role="tab"
            aria-selected={view !== "daily"}
            aria-controls="plan-goals-panel"
            onClick={() => selectView("goals")}
          >
            Goals
          </button>
        </div>
      </div>

      {view === "daily" ? (
        <div id="plan-daily-panel" role="tabpanel" aria-labelledby="plan-daily-tab">
          <DayPlan />
        </div>
      ) : (
        <div id="plan-goals-panel" role="tabpanel" aria-labelledby="plan-goals-tab">
          {view === "foresight" ? (
            <Foresight
              data={data}
              goals={goals}
              isLoading={isLoading}
              isError={isError}
              onBack={() => setView("goals")}
              onDriver={onDriver}
            />
          ) : (
            <GoalPlanner
              onOpenForesight={() => setView("foresight")}
              recommendationGoalId={recommendationGoalId}
              onRecommendationOpened={onRecommendationOpened}
            />
          )}
        </div>
      )}
    </>
  );
}

function Foresight({
  data,
  goals,
  isLoading,
  isError,
  onBack,
  onDriver,
}: {
  data?: ForesightResponse;
  goals: GoalSummary[];
  isLoading: boolean;
  isError: boolean;
  onBack: () => void;
  onDriver: (driver: ForesightDriver) => void;
}) {
  const names = new Map(goals.map((goal) => [goal.id, goal.name]));
  const notReady = !data || data.profile_days < 14 || data.outlooks.length === 0;
  const onTrack = data?.outlooks.filter((outlook) => outlook.probability_bp >= 7_000).length ?? 0;
  const focus = data ? [...data.outlooks].sort((a, b) => a.probability_bp - b.probability_bp)[0] : null;

  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow" style={{ margin: 0 }}>Goals</p>
          <h1>Can you reach your goals?</h1>
        </div>
        {data && <span className="plan-horizon">{data.horizon_days} days</span>}
      </div>
      <div className="pad">
        <button className="btn btn-ghost btn-sm" onClick={onBack}>Back to goals</button>

        {isLoading || (!data && !isError) ? (
          <p className="voice" style={{ fontSize: 17, marginTop: 24 }}>Looking ahead…</p>
        ) : isError ? (
          <section className="plan-empty" style={{ marginTop: 18 }}>
            <h2>I couldn’t reach your forecast just now.</h2>
            <p>Nothing has changed. Try again in a moment.</p>
          </section>
        ) : notReady ? (
          <Reveal style={{ marginTop: 18 }}>
            <section className="plan-empty">
              <p className="eyebrow" style={{ margin: 0 }}>Still learning</p>
              <h2>Not enough history to forecast yet.</h2>
              <p>
                Confirmed spending gives Kira a pattern to learn. Once there is enough of it,
                this will show a range of plausible futures — not a made-up certainty.
              </p>
            </section>
          </Reveal>
        ) : data ? (
          <>
            <Reveal style={{ marginTop: 18 }}>
              <section className={`plan-summary ${onTrack === data.outlooks.length ? "good" : "watch"}`}>
                <p className="eyebrow" style={{ margin: 0 }}>Your check-in</p>
                <h2>
                  {onTrack === data.outlooks.length
                    ? "Your goals look on track."
                    : onTrack === 0
                      ? "Your plan needs attention."
                      : "Some goals need attention."}
                </h2>
                <p>
                  You&apos;re likely to reach {onTrack} of {data.outlooks.length} goal{data.outlooks.length === 1 ? "" : "s"} by their target date{data.outlooks.length === 1 ? "" : "s"}.
                </p>
                {focus && (
                  <div className="plan-summary-focus">
                    <span>Focus first</span>
                    <b>{names.get(focus.goal_id) ?? "Your goal"}</b>
                    <small>{percent(focus.probability_bp)} likely by {formatDate(focus.target_date)}</small>
                  </div>
                )}
              </section>
            </Reveal>

            <Reveal delay={45} style={{ marginTop: 18 }}>
              <section className="plan-goals">
                <div className="plan-card-head">
                  <div>
                    <p className="eyebrow" style={{ margin: 0 }}>Your goals</p>
                    <h2>What to expect</h2>
                  </div>
                </div>
                <div className="plan-goal-grid">
                  {data.outlooks.map((outlook) => {
                    const name = names.get(outlook.goal_id) ?? "Your goal";
                    return (
                      <article className="plan-goal" key={outlook.goal_id}>
                        <div>
                          <b>{name}</b>
                          <span>{outlookLabel(outlook.probability_bp)} · {percent(outlook.probability_bp)} likely by {formatDate(outlook.target_date)}</span>
                          {outlook.median_shortfall.sen > 0 && (
                            <small>You may be short RM{fmt(outlook.median_shortfall.sen)}</small>
                          )}
                        </div>
                      </article>
                    );
                  })}
                </div>
                <p className="plan-assumption">{data.assumption}</p>
              </section>
            </Reveal>

            {data.drivers.length > 0 && (
              <Reveal delay={85} style={{ marginTop: 18 }}>
                <section className="plan-next-step">
                  <p className="eyebrow" style={{ margin: 0 }}>Best next step</p>
                  <h2>{driverCopy(data.drivers[0]!, names)}</h2>
                  <p>It improves the chance of reaching your goal from {percent(data.drivers[0]!.probability_bp_before)} to {percent(data.drivers[0]!.probability_bp_after)}.</p>
                  <button className="btn btn-accent" onClick={() => onDriver(data.drivers[0]!)}>
                    Review this change
                  </button>
                </section>
              </Reveal>
            )}

            <Reveal delay={115} style={{ marginTop: 18 }}>
              <details className="plan-details">
                <summary>See forecast details</summary>
                <section className="plan-forecast">
                  <div className="plan-card-head">
                    <div>
                      <p className="eyebrow" style={{ margin: 0 }}>Balance forecast</p>
                      <h2>How your balance may change</h2>
                    </div>
                    <span className="plan-key"><i /> possible range</span>
                  </div>
                  <FanChart dates={data.dates} p10={data.p10} p50={data.p50} p90={data.p90} />
                </section>
                <section className="plan-drivers">
                <div className="plan-card-head">
                  <div>
                      <p className="eyebrow" style={{ margin: 0 }}>Other options</p>
                      <h2>More changes you could review</h2>
                  </div>
                </div>
                <div className="driver-list">
                  {data.drivers.map((driver) => (
                    <article className="driver" key={`${driver.lever.kind}-${driver.lever.target_id}-${driver.lever.delta.sen}`}>
                      <div>
                        <b>{driverCopy(driver, names)}</b>
                        <span>{percent(driver.probability_bp_before)} → {percent(driver.probability_bp_after)}</span>
                      </div>
                      <button className="btn btn-line btn-sm" onClick={() => onDriver(driver)}>
                        Let Kira do it
                      </button>
                    </article>
                  ))}
                </div>
                </section>
              </details>
            </Reveal>
          </>
        ) : null}
      </div>
    </>
  );
}
