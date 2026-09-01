import { useState } from "react";

import type { ForesightDriver, ForesightResponse, GoalSummary } from "@kira/contracts";

import { FanChart } from "../components/FanChart";
import { Reveal } from "../components/Reveal";
import { Ring } from "../components/Ring";
import { fmt } from "../lib/money";
import { DayPlan } from "./DayPlan";
import { GoalPlanner } from "./goals/GoalPlanner";

export type PlanView = "daily" | "goals";

type PlanProps = {
  initialView?: PlanView;
  data?: ForesightResponse;
  goals?: GoalSummary[];
  isLoading?: boolean;
  isError?: boolean;
  onDriver?: (driver: ForesightDriver) => void;
};

const SHORT = "#4E8F79";
const LONG = "#A9853F";

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

/** Shared PLAN shell. Foresight belongs inside Goals, not in bottom navigation. */
export function Plan({
  initialView = "daily",
  data,
  goals = [],
  isLoading = false,
  isError = false,
  onDriver = () => undefined,
}: PlanProps) {
  const [view, setView] = useState<PlanView>(initialView);
  const [showForesight, setShowForesight] = useState(false);

  const selectView = (next: PlanView) => {
    setView(next);
    if (next === "daily") setShowForesight(false);
  };

  return (
    <>
      <div className="plan-view-switch">
        <div className="seg-toggle" role="tablist" aria-label="Plan view">
          <span
            className="seg-thumb"
            aria-hidden="true"
            style={{
              transform:
                view === "goals" ? "translateX(calc(100% + 5px))" : "translateX(0)",
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
            className={`seg-btn ${view === "goals" ? "on" : ""}`}
            type="button"
            role="tab"
            aria-selected={view === "goals"}
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
          {showForesight ? (
            <Foresight
              data={data}
              goals={goals}
              isLoading={isLoading}
              isError={isError}
              onBack={() => setShowForesight(false)}
              onDriver={onDriver}
            />
          ) : (
            <GoalPlanner onOpenForesight={() => setShowForesight(true)} />
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
  const details = new Map(goals.map((goal) => [goal.id, goal]));
  const notReady = !data || data.profile_days < 14 || data.outlooks.length === 0;

  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow" style={{ margin: 0 }}>Goals · Foresight</p>
          <h1>The road ahead</h1>
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
              <section className="plan-forecast">
                <div className="plan-card-head">
                  <div>
                    <p className="eyebrow" style={{ margin: 0 }}>Balance forecast</p>
                    <h2>There is more than one future.</h2>
                  </div>
                  <span className="plan-key"><i /> likely range</span>
                </div>
                <FanChart dates={data.dates} p10={data.p10} p50={data.p50} p90={data.p90} />
              </section>
            </Reveal>

            <Reveal delay={45} style={{ marginTop: 18 }}>
              <section className="plan-goals">
                <div className="plan-card-head">
                  <div>
                    <p className="eyebrow" style={{ margin: 0 }}>Goal outlook</p>
                    <h2>What your plan is likely to reach</h2>
                  </div>
                </div>
                <div className="plan-goal-grid">
                  {data.outlooks.map((outlook) => {
                    const goal = details.get(outlook.goal_id);
                    const name = names.get(outlook.goal_id) ?? "Your goal";
                    return (
                      <article className="plan-goal" key={outlook.goal_id}>
                        <div className="plan-ring">
                          <Ring
                            pct={outlook.probability_bp / 10000}
                            size={76}
                            stroke={goal?.horizon === "short" ? SHORT : LONG}
                          />
                          <b>{percent(outlook.probability_bp)}</b>
                        </div>
                        <div>
                          <b>{name}</b>
                          <span>by {formatDate(outlook.target_date)}</span>
                          {outlook.median_shortfall.sen > 0 && (
                            <small>Typical gap: RM{fmt(outlook.median_shortfall.sen)}</small>
                          )}
                        </div>
                      </article>
                    );
                  })}
                </div>
                <p className="plan-assumption">{data.assumption}</p>
              </section>
            </Reveal>

            <Reveal delay={85} style={{ marginTop: 18 }}>
              <section className="plan-drivers">
                <div className="plan-card-head">
                  <div>
                    <p className="eyebrow" style={{ margin: 0 }}>Changes worth considering</p>
                    <h2>What moves the first goal most</h2>
                  </div>
                </div>
                {data.drivers.length === 0 ? (
                  <p className="plan-muted">There is no useful change to suggest from this forecast yet.</p>
                ) : (
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
                )}
              </section>
            </Reveal>
          </>
        ) : null}
      </div>
    </>
  );
}
