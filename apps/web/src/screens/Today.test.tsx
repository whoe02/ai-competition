import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DashboardToday } from "@kira/contracts";

import { Today } from "./Today";

const DATA = {
  date: "2026-09-03",
  display_name: "Floyd",
  currency: "MYR",
  balance_sen: 418040,
  reserved_sen: 200300,
  buffer_sen: 80000,
  goal_reserve_sen: 21200,
  unclaimed_sen: 116540,
  per_day_sen: 5297,
  spent_today_sen: 0,
  safe_today_sen: 5297,
  days_to_payday: 22,
  cycle_elapsed: 8,
  commitment_count: 5,
  drafts_waiting: 2,
  next_commitment: {
    id: "c1",
    name: "Rent",
    amount_sen: 120000,
    due_date: "2026-09-05",
    days_until: 2,
    protected: true,
  },
  goals: [
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
  ],
} as DashboardToday;

function renderToday(overrides: Partial<Parameters<typeof Today>[0]> = {}) {
  return render(<Today data={DATA} isLoading={false} isError={false} go={vi.fn()} {...overrides} />);
}

describe("Today", () => {
  it("shows the safe-to-spend figure", () => {
    renderToday();
    expect(screen.getByLabelText("RM52.97")).toBeInTheDocument();
  });

  it("greets the user by name", () => {
    renderToday();
    expect(screen.getByText(/Floyd/)).toBeInTheDocument();
  });

  it("names the next commitment with its amount and countdown", () => {
    renderToday();
    expect(screen.getByText("Rent")).toBeInTheDocument();
    expect(screen.getByText("1,200.00")).toBeInTheDocument();
    expect(screen.getByText(/in 2 days/i)).toBeInTheDocument();
  });

  it("surfaces waiting drafts and says they are not counted", () => {
    renderToday();
    expect(screen.getByText(/2 captures waiting on you/i)).toBeInTheDocument();
    expect(screen.getByText(/Nothing enters your ledger until you confirm it/i)).toBeInTheDocument();
  });

  it("opens Kira's prepared morning briefing when one exists", async () => {
    const go = vi.fn();
    renderToday({
      go,
      briefing: {
        id: "b1",
        on_date: "2026-09-03",
        summary: "Your money check is complete.",
        proposal_count: 2,
        pending_proposal_count: 2,
      },
    });
    const user = userEvent.setup();

    expect(screen.getByText(/Kira did 3 things last night/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /open Kira's morning briefing/i }));
    expect(go).toHaveBeenCalledWith("butler");
  });

  it("shows the working on request, and it reconciles", async () => {
    renderToday();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /show the working/i }));

    expect(screen.getByText("4,180.40")).toBeInTheDocument();
    expect(screen.getByText("−2,003.00")).toBeInTheDocument();
    expect(screen.getByText("−800.00")).toBeInTheDocument();
    expect(screen.getByText("−212.00")).toBeInTheDocument();
    expect(screen.getAllByText("1,165.40").length).toBeGreaterThan(0);
    expect(screen.getByText("52.97/day")).toBeInTheDocument();
  });

  it("names the goal and its projection", () => {
    renderToday();
    expect(screen.getByText("Emergency top-up")).toBeInTheDocument();
    expect(screen.getByText("46%")).toBeInTheDocument();
  });

  it("shows a loading state rather than a wrong number", () => {
    renderToday({ data: undefined, isLoading: true });
    expect(screen.getByText(/working out your day/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("RM52.97")).not.toBeInTheDocument();
  });

  it("shows an error state rather than a stale number", () => {
    renderToday({ data: undefined, isLoading: false, isError: true });
    expect(screen.getByText(/couldn't reach your numbers/i)).toBeInTheDocument();
  });
});
