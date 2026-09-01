import type { ForesightResponse } from "@kira/contracts";

import { fmt } from "../lib/money";

type Point = ForesightResponse["p10"][number];

type FanChartProps = {
  dates: string[];
  p10: Point[];
  p50: Point[];
  p90: Point[];
};

const WIDTH = 340;
const HEIGHT = 150;
const PAD = 10;

function points(values: Point[], low: number, high: number): string {
  const span = Math.max(1, high - low);
  const last = Math.max(1, values.length - 1);
  return values
    .map((point, index) => {
      const x = PAD + (index / last) * (WIDTH - PAD * 2);
      const y = PAD + ((high - point.sen) / span) * (HEIGHT - PAD * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

/** A small, dependency-free percentile fan: uncertainty is the surface, not a footnote. */
export function FanChart({ dates, p10, p50, p90 }: FanChartProps) {
  const values = [...p10, ...p50, ...p90].map((point) => point.sen);
  if (values.length === 0) return null;

  const low = Math.min(...values);
  const high = Math.max(...values);
  const final = p50.at(-1);
  const label = `Forecast band over ${dates.length} days; median closes at RM${fmt(final?.sen ?? 0)}`;
  const upper = points(p90, low, high);
  const median = points(p50, low, high);
  const lower = points(p10, low, high);
  const band = `${upper} ${lower.split(" ").reverse().join(" ")}`;

  return (
    <figure className="fan-figure">
      <svg className="fan-chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={label}>
        <defs>
          <linearGradient id="fan-wide" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#A9853F" stopOpacity="0.24" />
            <stop offset="1" stopColor="#A9853F" stopOpacity="0.05" />
          </linearGradient>
        </defs>
        <line x1={PAD} x2={WIDTH - PAD} y1={HEIGHT - PAD} y2={HEIGHT - PAD} />
        <polygon points={band} fill="url(#fan-wide)" />
        <polyline points={upper} fill="none" className="fan-edge" />
        <polyline points={lower} fill="none" className="fan-edge" />
        <polyline points={median} fill="none" className="fan-median" />
      </svg>
      <figcaption>
        <span>{dates.at(0)}</span>
        <b>Median · RM{fmt(final?.sen ?? 0)}</b>
        <span>{dates.at(-1)}</span>
      </figcaption>
    </figure>
  );
}
