import { useState } from "react";

import type { BriefingInboxResponse, DashboardToday } from "@kira/contracts";

import type { Tab } from "../App";
import type { PlanView } from "./Plan";
import { ClaimLine, type Band } from "../components/ClaimLine";
import { IcArrow, IcBell, IcChev, IcLock } from "../components/Icons";
import { Odometer } from "../components/Odometer";
import { Reveal } from "../components/Reveal";
import { Ring } from "../components/Ring";
import { fmt } from "../lib/money";

const HORIZON_STROKE: Record<string, string> = { short: "#4E8F79", long: "#A9853F" };

const LONG_DATE = new Intl.DateTimeFormat("en-MY", {
  weekday: "long",
  day: "numeric",
  month: "long",
});

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

type TodayProps = {
  data: DashboardToday | undefined;
  isLoading: boolean;
  isError: boolean;
  briefing?: BriefingInboxResponse | null;
  go: (tab: Tab, planView?: PlanView) => void;
};

export function Today({ data, isLoading, isError, briefing, go }: TodayProps) {
  const [picked, setPicked] = useState<Band | null>(null);
  const [maths, setMaths] = useState(false);

  // A wrong number is worse than no number, so neither state guesses.
  if (isLoading || !data) {
    return (
      <div className="pad" style={{ paddingTop: 90 }}>
        <p className="voice" style={{ fontSize: 17 }}>
          {isError ? "I couldn't reach your numbers just now." : "Working out your day…"}
        </p>
        {isError && (
          <p style={{ fontSize: 13, color: "var(--muted)" }}>
            Nothing has changed on your ledger. Pull down to try again.
          </p>
        )}
      </div>
    );
  }

  const next = data.next_commitment;
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
      <div className="topbar">
        <div>
          <p className="eyebrow" style={{ margin: 0 }}>
            {LONG_DATE.format(new Date(`${data.date}T00:00:00`))}
          </p>
          <h1>{greeting()}, {data.display_name}</h1>
        </div>
      </div>

      <div className="pad">
        <Reveal>
          <div className="hero-parallax">
            <section className="hero">
              <p className="eyebrow on-ink" style={{ margin: 0 }}>Safe to spend today</p>
              <div style={{ marginTop: 11 }}>
                <Odometer sen={data.safe_today_sen} size={52} />
              </div>
              <p
                className="voice"
                style={{ margin: "12px 0 0", fontSize: 15, color: "rgba(233,237,233,.78)" }}
              >
                Your bills and the RM{fmt(data.buffer_sen)} buffer are already set aside. This is
                {" "}what&apos;s left over, spread evenly across the {data.days_to_payday} days to payday.
              </p>

              <div style={{ marginTop: 20 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "baseline",
                    marginBottom: 10,
                  }}
                >
                  <span className="eyebrow on-ink">Where your RM{fmt(data.balance_sen)} stands</span>
                  <span style={{ fontSize: 11.5, color: "rgba(233,237,233,.5)", fontWeight: 600 }}>
                    tap a band
                  </span>
                </div>
                <ClaimLine data={data} picked={picked} onPick={setPicked} />
              </div>

              <button
                className="btn btn-sm"
                style={{
                  marginTop: 16,
                  background: "rgba(233,237,233,.17)",
                  color: "#F4F7F3",
                  border: "1px solid rgba(233,237,233,.26)",
                  width: "100%",
                }}
                onClick={() => setMaths((visible) => !visible)}
              >
                {maths ? "Hide the working" : "Show the working"}
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
          </div>
        </Reveal>

        {briefing && (
          <Reveal delay={30} style={{ marginTop: 16 }}>
            <button
              className="card tapp"
              style={{ display: "flex", gap: 13, alignItems: "center", width: "100%", textAlign: "left" }}
              onClick={() => go("butler")}
              aria-label="Open Kira's morning briefing"
            >
              <span
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: 13,
                  background: "rgba(78,143,121,.14)",
                  color: "var(--sage)",
                  display: "grid",
                  placeItems: "center",
                  flex: "none",
                }}
              >
                <IcBell size={19} />
              </span>
              <span style={{ flex: 1, minWidth: 0 }}>
                <b style={{ fontSize: 14.5, display: "block", letterSpacing: "-.01em" }}>
                  Kira did {briefing.proposal_count + 1} thing{briefing.proposal_count === 0 ? "" : "s"} last night
                </b>
                <span
                  style={{
                    display: "block",
                    fontSize: 12.5,
                    color: "var(--muted)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {briefing.pending_proposal_count > 0
                    ? `${briefing.pending_proposal_count} decision${briefing.pending_proposal_count === 1 ? "" : "s"} ready for you.`
                    : briefing.summary}
                </span>
              </span>
              <IcChev size={17} />
            </button>
          </Reveal>
        )}

        {data.drafts_waiting > 0 && (
          <Reveal delay={40} style={{ marginTop: 16 }}>
            <button
              className="card tapp"
              style={{ display: "flex", gap: 13, alignItems: "center", width: "100%", textAlign: "left" }}
              onClick={() => go("activity")}
            >
              <span
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: 13,
                  background: "rgba(169,133,63,.14)",
                  color: "var(--brass)",
                  display: "grid",
                  placeItems: "center",
                  flex: "none",
                }}
              >
                <IcBell size={19} />
              </span>
              <span style={{ flex: 1 }}>
                <b style={{ fontSize: 14.5, display: "block", letterSpacing: "-.01em" }}>
                  {data.drafts_waiting} capture{data.drafts_waiting === 1 ? "" : "s"} waiting on you
                </b>
                <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
                  Nothing enters your ledger until you confirm it.
                </span>
              </span>
              <IcChev size={17} />
            </button>
          </Reveal>
        )}

        {next && (
          <Reveal delay={60} style={{ marginTop: 16 }}>
            <section className="card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <p className="eyebrow" style={{ margin: "0 0 6px" }}>Next commitment</p>
                  <b style={{ fontSize: 17, letterSpacing: "-.02em" }}>{next.name}</b>
                  <p style={{ margin: "3px 0 0", fontSize: 12.5, color: "var(--muted)" }}>
                    Due {LONG_DATE.format(new Date(`${next.due_date}T00:00:00`))} · in {next.days_until} day
                    {next.days_until === 1 ? "" : "s"}
                  </p>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div className="money" style={{ fontSize: 21 }}>{fmt(next.amount_sen)}</div>
                  {next.protected && (
                    <span className="pill" style={{ marginTop: 7, fontSize: 9.5, padding: "4px 9px" }}>
                      <IcLock size={11} /> Reserved
                    </span>
                  )}
                </div>
              </div>
            </section>
          </Reveal>
        )}

        <Reveal delay={40} style={{ marginTop: 16 }}>
          <button className="card tapp" style={{ width: "100%", textAlign: "left" }} onClick={() => go("plan", "goals")}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                marginBottom: 14,
              }}
            >
              <p className="eyebrow" style={{ margin: 0 }}>Your goals</p>
              <span className="tag" style={{ color: "var(--brass)" }}>RM{fmt(data.goal_reserve_sen)} held</span>
            </div>
            <div style={{ display: "flex", gap: 14 }}>
              {data.goals.map((goal) => {
                const progress = goal.target_sen > 0 ? Math.min(1, goal.saved_sen / goal.target_sen) : 0;
                return (
                  <span key={goal.id} style={{ flex: 1, display: "flex", gap: 11, alignItems: "center", minWidth: 0 }}>
                    <span className="ringwrap" style={{ width: 46, height: 46, flex: "none" }}>
                      <Ring pct={progress} size={46} stroke={HORIZON_STROKE[goal.horizon] ?? "#A9853F"} />
                      <figcaption>
                        <b style={{ fontSize: 11, letterSpacing: "-.03em" }}>{Math.round(progress * 100)}%</b>
                      </figcaption>
                    </span>
                    <span style={{ minWidth: 0 }}>
                      <b
                        style={{
                          fontSize: 12.5,
                          letterSpacing: "-.01em",
                          display: "block",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {goal.name}
                      </b>
                      <span style={{ fontSize: 11, color: "var(--muted)" }}>
                        {goal.months_left} month{goal.months_left === 1 ? "" : "s"} to go
                      </span>
                    </span>
                  </span>
                );
              })}
              {data.goals.length === 0 && (
                <span style={{ fontSize: 13, color: "var(--muted)" }}>No goals set. Tap to add one.</span>
              )}
            </div>
          </button>
        </Reveal>

        <Reveal delay={40} style={{ marginTop: 16 }}>
          <section
            className="card"
            style={{
              background: "linear-gradient(150deg,#F6F3EA,#EFEFE7)",
              border: "1px solid rgba(169,133,63,.24)",
            }}
          >
            <p className="eyebrow" style={{ margin: "0 0 7px", color: "var(--brass)" }}>Lunch</p>
            <p className="voice" style={{ margin: 0, fontSize: 17, lineHeight: 1.4 }}>
              Shall I plan lunch and the trip to KLCC before your next meeting?
            </p>
            <button className="btn btn-primary btn-sm" style={{ marginTop: 14 }} onClick={() => go("plan")}>
              Plan my day <IcArrow size={15} />
            </button>
          </section>
        </Reveal>
      </div>
    </>
  );
}
