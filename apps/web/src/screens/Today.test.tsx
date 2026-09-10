import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

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
  it("makes today's spending pace the lead figure", () => {
    renderToday();
    expect(screen.getByLabelText("RM0.00")).toBeInTheDocument();
    expect(screen.getByText("of RM52.97 daily budget")).toBeInTheDocument();
    expect(screen.getByText("left today")).toBeInTheDocument();
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
    await user.click(screen.getByRole("button", { name: /show how today is protected/i }));

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

  it("holds the shape of the answer while it loads, so nothing jumps", () => {
    const { container } = renderToday({ data: undefined, isLoading: true });
    expect(container.querySelector(".sk-hero")).toBeInTheDocument();
    expect(container.querySelectorAll(".sk-card")).toHaveLength(2);
  });

  it("shows an error state rather than a stale number", () => {
    renderToday({ data: undefined, isLoading: false, isError: true });
    expect(screen.getByText(/couldn't reach your numbers/i)).toBeInTheDocument();
  });

  it("offers a retry that actually retries, not a gesture that does not exist", async () => {
    const onRetry = vi.fn();
    renderToday({ data: undefined, isLoading: false, isError: true, onRetry });
    const user = userEvent.setup();

    expect(screen.queryByText(/pull down/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  describe("the plan invitation", () => {
    afterEach(() => vi.useRealTimers());

    function at(iso: string) {
      vi.useFakeTimers();
      vi.setSystemTime(new Date(iso));
    }

    it("names no place, route or appointment it has not been told about", () => {
      at("2026-09-07T03:00:00Z"); // 11:00 in KL
      renderToday();
      const card = screen.getByRole("button", { name: /plan my day/i }).closest("section");

      expect(card).not.toHaveTextContent(/KLCC/i);
      expect(card).not.toHaveTextContent(/meeting/i);
    });

    it("names the meal the planner would search for, by the KL clock", () => {
      at("2026-09-07T03:00:00Z"); // 11:00 in KL
      renderToday();
      expect(screen.getByText(/somewhere for lunch within reach/i)).toBeInTheDocument();
    });

    it("does not offer a meal at an hour when no one wants one", () => {
      at("2026-09-06T16:00:00Z"); // midnight in KL
      renderToday();
      expect(screen.queryByText(/somewhere for/i)).not.toBeInTheDocument();
      expect(screen.getByText(/what is within reach/i)).toBeInTheDocument();
    });

    it("states only the figure it holds", () => {
      at("2026-09-07T03:00:00Z");
      renderToday();
      expect(screen.getByText(/RM52\.97 is what today has room for/i)).toBeInTheDocument();
    });
  });

  it("groups what is waiting on you into one surface, not two competing cards", () => {
    const { container } = renderToday({
      briefing: {
        id: "b1",
        on_date: "2026-09-03",
        summary: "Your money check is complete.",
        proposal_count: 2,
        pending_proposal_count: 2,
      },
    });

    const group = container.querySelector(".alerts");
    expect(group).toBeInTheDocument();
    expect(group?.querySelectorAll(".alert-row")).toHaveLength(2);
    // Transient things do not float at the height of your standing commitments.
    expect(container.querySelectorAll(".card.card-row")).toHaveLength(0);
  });

  it("hides the review surface when nothing is waiting", () => {
    const { container } = renderToday({ data: { ...DATA, drafts_waiting: 0 } as DashboardToday });
    expect(container.querySelector(".group-alert")).not.toBeInTheDocument();
  });

  it("keeps every goal reachable when there are more than two", () => {
    const goals = ["Emergency top-up", "Japan trip", "New laptop", "Course fees"].map((name, i) => ({
      ...DATA.goals[0],
      id: `g${i}`,
      name,
    }));
    const { container } = renderToday({ data: { ...DATA, goals } as DashboardToday });

    goals.forEach((goal) => expect(screen.getByText(goal.name)).toBeInTheDocument());
    expect(container.querySelector(".goals")).toHaveAttribute("data-count", "4");
  });

  it("says what to do next when there are no goals at all", () => {
    renderToday({ data: { ...DATA, goals: [] } as DashboardToday });
    expect(screen.getByText(/tap to plan your first one/i)).toBeInTheDocument();
  });
});
