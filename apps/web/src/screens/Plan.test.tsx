import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { ForesightResponse, GoalSummary } from "@kira/contracts";

import { dashboardTodayKey } from "../api/hooks";
import { Plan } from "./Plan";

export const FORECAST: ForesightResponse = {
  horizon_days: 180,
  dates: ["2026-09-04", "2026-12-02", "2027-03-02"],
  p10: [
    { sen: 410000, currency: "MYR" },
    { sen: 300000, currency: "MYR" },
    { sen: 170000, currency: "MYR" },
  ],
  p50: [
    { sen: 425000, currency: "MYR" },
    { sen: 390000, currency: "MYR" },
    { sen: 350000, currency: "MYR" },
  ],
  p90: [
    { sen: 440000, currency: "MYR" },
    { sen: 490000, currency: "MYR" },
    { sen: 560000, currency: "MYR" },
  ],
  outlooks: [
    {
      goal_id: "g1",
      target_date: "2027-02-15",
      probability_bp: 6200,
      median_shortfall: { sen: 30000, currency: "MYR" },
    },
  ],
  drivers: [
    {
      lever: { kind: "goal_monthly", target_id: "g1", delta: { sen: 4000, currency: "MYR" } },
      probability_bp_before: 6200,
      probability_bp_after: 9100,
      bp_per_ringgit: 725,
    },
    {
      lever: { kind: "daily_spend", target_id: "all", delta: { sen: -500, currency: "MYR" } },
      probability_bp_before: 6200,
      probability_bp_after: 7900,
      bp_per_ringgit: 340,
    },
  ],
  profile_days: 90,
  assumption: "Based on your last 90 days of confirmed spending. It is a projection, not a promise.",
};

const GOALS: GoalSummary[] = [
  {
    id: "g1",
    name: "Emergency top-up",
    horizon: "short",
    target_sen: 250000,
    saved_sen: 115000,
    monthly_sen: 27000,
    months_left: 5,
    note: "Three weeks of expenses.",
  },
];

function renderPlan(overrides: Partial<Parameters<typeof Plan>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(dashboardTodayKey, { goals: GOALS });
  return render(
    <QueryClientProvider client={client}>
      <Plan
        initialView="goals"
        data={FORECAST}
        goals={GOALS}
        isLoading={false}
        isError={false}
        onDriver={vi.fn()}
        {...overrides}
      />
    </QueryClientProvider>,
  );
}

describe("Plan", () => {
  async function openForesight() {
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /open foresight/i }));
    return user;
  }

  it("keeps forecasts in a dedicated Foresight section", async () => {
    renderPlan();
    expect(screen.getByText("What are you saving toward?")).toBeInTheDocument();
    expect(screen.queryByText("62%")).not.toBeInTheDocument();

    await openForesight();
    expect(screen.getByText("62%")).toBeInTheDocument();
    expect(screen.getByText("Emergency top-up")).toBeInTheDocument();
  });

  it("states the assumption next to the number, not in a tooltip", async () => {
    renderPlan();
    await openForesight();
    expect(screen.getByText(/last 90 days/i)).toBeInTheDocument();
    expect(screen.getByText(/not a promise/i)).toBeInTheDocument();
  });

  it("renders one driver card per ranked change", async () => {
    renderPlan();
    await openForesight();
    expect(screen.getAllByRole("button", { name: /let kira do it/i })).toHaveLength(
      FORECAST.drivers.length,
    );
  });

  it("shows what a driver buys, before and after", async () => {
    renderPlan();
    await openForesight();
    expect(screen.getByText("62% → 91%")).toBeInTheDocument();
  });

  it("hands a driver to the Butler instead of applying it", async () => {
    const onDriver = vi.fn();
    renderPlan({ onDriver });
    const user = await openForesight();

    await user.click(screen.getAllByRole("button", { name: /let kira do it/i })[0]!);

    expect(onDriver).toHaveBeenCalledWith(FORECAST.drivers[0]);
  });

  it("says so plainly when there is not enough history to forecast", async () => {
    renderPlan({ data: { ...FORECAST, outlooks: [], drivers: [], profile_days: 3 } });
    await openForesight();
    expect(screen.getByText(/not enough history/i)).toBeInTheDocument();
  });
});
