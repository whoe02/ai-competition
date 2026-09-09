import type { DashboardToday } from "@kira/contracts";

import { fmt } from "../lib/money";

export type Band = "free" | "goal" | "commit" | "buffer";

type ClaimLineProps = {
  data: DashboardToday;
  picked: Band | null;
  onPick: (band: Band | null) => void;
};

export function ClaimLine({ data, picked, onPick }: ClaimLineProps) {
  const goalCount = data.goals.length;
  const segments: { k: Band; v: number; cls: string; label: string; sub: string }[] = [
    { k: "free", v: data.unclaimed_sen, cls: "seg-free", label: "Unclaimed", sub: "Yours to decide" },
    {
      k: "goal",
      v: data.goal_reserve_sen,
      cls: "seg-goal",
      label: "Goal reserve",
      sub: `${goalCount} goal${goalCount === 1 ? "" : "s"}, accrued this cycle`,
    },
    {
      k: "commit",
      v: data.reserved_sen,
      cls: "seg-commit",
      label: "Committed",
      sub: `${data.commitment_count} bills before payday`,
    },
    { k: "buffer", v: data.buffer_sen, cls: "seg-buffer", label: "Buffer", sub: "Protected, not spendable" },
  ];

  // Nothing picked reads as the headline claim; a pick swaps in that band's own
  // figure. One line either way — the 2x2 legend it replaces only repeated what
  // "Show the working" already lists in full.
  const shown = segments.find((segment) => segment.k === picked) ?? segments[0]!;
  const total = segments.reduce((sum, segment) => sum + Math.max(segment.v, 0), 0) || 1;

  return (
    <div>
      <div className="claim">
        {segments.map((segment, index) => {
          const share = Math.max(segment.v, 0) / total;
          return (
            <button
              key={segment.k}
              className={`claim-seg ${segment.cls} ${picked === segment.k ? "is-picked" : ""}`}
              style={{
                flexGrow: Math.max(segment.v, 0),
                animationDelay: `${0.35 + index * 0.09}s`,
                opacity: picked && picked !== segment.k ? 0.32 : 1,
              }}
              onClick={() => onPick(picked === segment.k ? null : segment.k)}
              aria-pressed={picked === segment.k}
              aria-label={`${segment.label} RM${fmt(segment.v)}`}
            >
              {/* The share only reads inside a band wide enough to hold it; the
                  rest stay bare rather than crowding a 2-character label. */}
              {share >= 0.15 && <i className="claim-pct">{Math.round(share * 100)}%</i>}
            </button>
          );
        })}
      </div>
      <p className="claim-cap">
        <span>
          <i className={`claim-dot ${shown.cls}`} aria-hidden="true" />
          {shown.label} <b>{fmt(shown.v)}</b> of {fmt(data.balance_sen)}
        </span>
        <span className="claim-cap-r">{picked ? shown.sub : "tap a band"}</span>
      </p>
    </div>
  );
}
