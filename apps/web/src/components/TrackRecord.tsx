import { useState } from "react";

import type { HindsightResponse } from "@kira/contracts";

import { fmt } from "../lib/money";

function percent(basisPoints: number): string {
  return `${Math.round(basisPoints / 100)}%`;
}

function day(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-MY", {
    day: "numeric",
    month: "short",
  });
}

/**
 * Kira's own record, at the top of her screen: how often her number was taken,
 * how far off it was, and what following it would have been worth.
 *
 * The headline is the count, not the percentage, because "82 of 90 days" is a
 * claim a person can check against their own week and a percentage is not. The
 * detail is one tap away rather than always open — an advisor who leads with
 * her scorecard is answering a question nobody asked.
 */
export function TrackRecord({ data }: { data: HindsightResponse | undefined }) {
  const [open, setOpen] = useState(false);
  if (!data || data.days === 0) return null;

  const lift =
    data.probability_bp_now !== null && data.probability_bp_if_followed !== null
      ? Math.round((data.probability_bp_if_followed - data.probability_bp_now) / 100)
      : null;

  return (
    <section className="record">
      <button
        className="record-head"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-label="My track record"
      >
        <div>
          <p className="eyebrow on-ink" style={{ margin: 0 }}>
            My track record
          </p>
          <b>
            You stayed under my number on {data.followed} of {data.days} days
          </b>
        </div>
        <span>{percent(data.follow_rate_bp)}</span>
      </button>

      {open && (
        <div className="record-detail">
          <div className="ev-row">
            <span>Average distance from my number</span>
            <b>RM{fmt(data.mean_abs_deviation.sen)}</b>
          </div>
          <div className="ev-row">
            <span>Had you followed it every day</span>
            <b>RM{fmt(data.counterfactual_gain.sen)} ahead</b>
          </div>
          {lift !== null && (
            <div className="ev-row">
              <span>Your first goal would sit</span>
              <b>{lift} points higher</b>
            </div>
          )}

          <div className="record-strip" aria-label="Recent days">
            {data.recent.map((entry) => (
              <i
                key={entry.on}
                className={entry.followed ? "under" : "over"}
                title={`${day(entry.on)}: RM${fmt(entry.actual.sen)} against RM${fmt(
                  entry.advised.sen,
                )}`}
              />
            ))}
          </div>

          <p className="record-note">{data.assumption}</p>
        </div>
      )}
    </section>
  );
}
