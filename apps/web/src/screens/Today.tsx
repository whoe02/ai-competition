import { useState } from "react";

import type { BriefingInboxResponse, DashboardToday } from "@kira/contracts";

import type { Tab } from "../App";
import type { PlanView } from "./Plan";
import { IcArrow, IcChev, IcInbox, IcLock, IcSpark } from "../components/Icons";
import { Odometer } from "../components/Odometer";
import { Reveal } from "../components/Reveal";
import { greeting, mealNow } from "../lib/klTime";
import { fmt } from "../lib/money";

const HORIZON_INK: Record<string, string> = { short: "#2F6B55", long: "#B08C3E" };
const HORIZON_WASH: Record<string, string> = { short: "#7FC0A4", long: "#E3C071" };

const LONG_DATE = new Intl.DateTimeFormat("en-MY", {
  weekday: "long",
  day: "numeric",
  month: "long",
});

const DAY_MONTH = new Intl.DateTimeFormat("en-MY", { day: "numeric", month: "long" });
const MONTH_ABBR = new Intl.DateTimeFormat("en-MY", { month: "short" });

type TodayProps = {
  data: DashboardToday | undefined;
  isLoading: boolean;
  isError: boolean;
  briefing?: BriefingInboxResponse | null;
  go: (tab: Tab, planView?: PlanView) => void;
  onRetry?: () => void;
};

export function Today({ data, isLoading, isError, briefing, go, onRetry }: TodayProps) {
  const [maths, setMaths] = useState(false);

  // A wrong number is worse than no number, so neither state guesses.
  if (isError && !data) {
    return (
      <div className="pad failure">
        <p className="voice" style={{ fontSize: "var(--fs-7)" }}>
          I couldn&apos;t reach your numbers just now.
        </p>
        <p className="led-s">Nothing has changed on your ledger.</p>
        {onRetry && (
          <button className="btn btn-line btn-sm" style={{ marginTop: "var(--s-6)" }} onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    );
  }

  // The shape of the answer, held while it is still being worked out — so the
  // page does not jump when the real figure lands on top of it.
  if (isLoading || !data) {
    return (
      <div className="pad" style={{ paddingTop: "var(--s-11)" }} aria-busy="true">
        <p className="sr-only">Working out your day…</p>
        <div className="sk sk-hero" />
        <div className="sk sk-card" />
        <div className="sk sk-card" />
      </div>
    );
  }

  const next = data.next_commitment;
  const meal = mealNow();
  // Today's share is what one day of the runway is worth; the pace strip says
  // how much of that share has already gone, which the figure alone cannot.
  const share = Math.max(data.per_day_sen, 0);
  const spent = Math.max(data.spent_today_sen, 0);
  const paceOver = spent > share;
  const pacePct = share > 0 ? Math.min(1, spent / share) : 0;
  const waiting = (briefing?.pending_proposal_count ?? 0) + data.drafts_waiting;
  const due = next ? new Date(`${next.due_date}T00:00:00`) : null;
  const rows: [string, string, boolean?][] = [
    ["In hand", fmt(data.balance_sen)],
    ["Bills due before payday", `−${fmt(data.reserved_sen)}`],
    ["Emergency buffer", `−${fmt(data.buffer_sen)}`],
    ["Goals, accrued this cycle", `−${fmt(data.goal_reserve_sen)}`],
    ["Unclaimed until payday", fmt(data.unclaimed_sen), true],
    [`÷ ${data.days_to_payday} days`, `${fmt(data.per_day_sen)}/day`],
    ...(data.spent_today_sen > 0
      ? ([["Confirmed today", `−${fmt(data.spent_today_sen)}`]] as [string, string][])
      : []),
    ["Safe to spend today", fmt(data.safe_today_sen), true],
  ];

  return (
    <>
      <header className="today-head">
        <p className="today-date">{LONG_DATE.format(new Date(`${data.date}T00:00:00`))}</p>
        <h1 className="today-greet">
          {greeting()}, {data.display_name}
        </h1>
      </header>

      <main className="pad">
        <Reveal>
          <section className="figure hero-parallax">
            <p className="figure-label">Today&apos;s pace</p>
            <div className="hero-pace-head">
              <div>
                <Odometer sen={spent} size={52} />
                <p className="hero-pace-limit">of RM{fmt(share)} daily budget</p>
              </div>
              <p className="hero-pace-left" aria-label={`RM${fmt(data.safe_today_sen)}`}>
                <b>RM{fmt(data.safe_today_sen)}</b>
                <span>left today</span>
              </p>
            </div>
            <span className="hero-pace-bar" aria-label={`${Math.round(pacePct * 100)}% of today's budget used`}>
              <i className={paceOver ? "over" : ""} style={{ width: `${Math.max(pacePct * 100, 1.5)}%` }} />
            </span>
            <p className="figure-note">
              {paceOver
                ? `RM${fmt(spent - share)} past today’s share. The days ahead now absorb it.`
                : "Bills, your emergency buffer and goal savings are already protected."}
            </p>

            <button
              className="hero-toggle"
              aria-expanded={maths}
              onClick={() => setMaths((visible) => !visible)}
            >
              {maths ? "Hide the calculation" : "Show how today is protected"}
            </button>

            {maths && (
              <div className="maths">
                {rows.map(([label, value, total], index) => (
                  <div
                    className={`maths-row ${total ? "total" : ""}`}
                    key={label}
                    style={{ animationDelay: `${index * 55}ms` }}
                  >
                    <span>{label}</span>
                    <b>{value}</b>
                  </div>
                ))}
              </div>
            )}
          </section>
        </Reveal>

        <Reveal delay={30}>
          <div className="ledger">
            {waiting > 0 && (
              <section className="led-group group-alert">
                <p className="led-cap-row">
                  <span className="led-cap">Waiting on you</span>
                  <span className="led-tally">{waiting} to review</span>
                </p>
                <div className="alerts">
                {briefing && (
                  <button
                    className="alert-row"
                    onClick={() => go("butler")}
                    aria-label="Open Kira's morning briefing"
                  >
                    <span className="alert-ic spark">
                      <IcSpark size={16} />
                    </span>
                    <span className="led-body">
                      <b className="led-t">
                        Kira did {briefing.proposal_count + 1} thing
                        {briefing.proposal_count === 0 ? "" : "s"} last night
                      </b>
                      <span className="led-s">
                        {briefing.pending_proposal_count > 0
                          ? `${briefing.pending_proposal_count} decision${briefing.pending_proposal_count === 1 ? "" : "s"} ready for you.`
                          : briefing.summary}
                      </span>
                    </span>
                    <IcChev size={17} className="led-chev" />
                  </button>
                )}

                {data.drafts_waiting > 0 && (
                  <button
                    className="alert-row"
                    onClick={() => go("activity")}
                    aria-label={`Review ${data.drafts_waiting} captures waiting on you`}
                  >
                    <span className="alert-ic inbox">
                      <IcInbox size={16} />
                    </span>
                    <span className="led-body">
                      <b className="led-t">
                        {data.drafts_waiting} capture{data.drafts_waiting === 1 ? "" : "s"} waiting on you
                      </b>
                      <span className="led-s">Nothing enters your ledger until you confirm it.</span>
                    </span>
                    <IcChev size={17} className="led-chev" />
                  </button>
                )}

                </div>
              </section>
            )}

            <section className="invite">
              <p className="voice">
                {meal
                  ? `RM${fmt(data.safe_today_sen)} is what today has room for. Shall I find you somewhere for ${meal.toLowerCase()} within reach?`
                  : `RM${fmt(data.safe_today_sen)} is what today has room for. Shall I show you what is within reach?`}
              </p>
              <button className="btn btn-accent invite-go" onClick={() => go("plan")}>
                Plan my day
                <IcArrow size={17} />
              </button>
            </section>

            {next && (
              <section className="led-group group-next">
                <p className="led-cap-row">
                  <span className="led-cap">Coming up</span>
                  <span className="led-cap-v">
                    {data.commitment_count} bill{data.commitment_count === 1 ? "" : "s"} before payday
                  </span>
                </p>
                <div className="led">
                  <span className={`due-chip ${next.days_until <= 3 ? "urgent" : ""}`} aria-hidden="true">
                    <em>{due ? MONTH_ABBR.format(due) : ""}</em>
                    <b>{due ? due.getDate() : ""}</b>
                  </span>
                  <span className="led-body">
                    <b className="led-t">{next.name}</b>
                    <span className="led-s">
                      Due in {next.days_until} day{next.days_until === 1 ? "" : "s"}, on{" "}
                      {DAY_MONTH.format(new Date(`${next.due_date}T00:00:00`))}
                    </span>
                  </span>
                  {next.protected && (
                    <span className="led-lock">
                      <IcLock size={12} />
                      <span className="sr-only">Reserved</span>
                    </span>
                  )}
                  <span className="led-v">{fmt(next.amount_sen)}</span>
                </div>
              </section>
            )}

            <button className="led-group group-goals" onClick={() => go("plan", "goals")} aria-label="Your goals">
              <span className="led-cap-row">
                <span className="led-cap">Goals</span>
                <span className="led-cap-v">RM{fmt(data.goal_reserve_sen)} held</span>
              </span>
              {data.goals.length === 0 ? (
                <span className="led-s" style={{ marginTop: "var(--s-5)" }}>
                  No goals set yet. Tap to plan your first one.
                </span>
              ) : (
                <span className="goals" data-count={data.goals.length}>
                  {data.goals.map((goal) => {
                    const progress = goal.target_sen > 0 ? Math.min(1, goal.saved_sen / goal.target_sen) : 0;
                    return (
                      <span key={goal.id} className="goal">
                        <span className="goal-top">
                          <b className="goal-name">
                            <i
                              className="goal-dot"
                              aria-hidden="true"
                              style={{ background: HORIZON_INK[goal.horizon] ?? HORIZON_INK.long }}
                            />
                            {goal.name}
                          </b>
                          <span className="goal-pct">{Math.round(progress * 100)}%</span>
                        </span>
                        <span className="goal-bar">
                          <i
                            style={{
                              width: `${Math.max(progress * 100, 1.5)}%`,
                              background: `linear-gradient(90deg, ${
                                HORIZON_WASH[goal.horizon] ?? HORIZON_WASH.long
                              }, ${HORIZON_INK[goal.horizon] ?? HORIZON_INK.long})`,
                            }}
                          />
                        </span>
                        <span className="goal-meta">
                          {goal.months_left} month{goal.months_left === 1 ? "" : "s"} to go
                        </span>
                      </span>
                    );
                  })}
                </span>
              )}
            </button>
          </div>
        </Reveal>
      </main>
    </>
  );
}
