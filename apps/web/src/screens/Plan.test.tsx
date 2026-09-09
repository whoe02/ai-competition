import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { GoalSummary } from "@kira/contracts";

import { dashboardTodayKey } from "../api/hooks";
import { Plan } from "./Plan";

const GOALS: GoalSummary[] = [
  {
    id: "g1",
    name: "Emergency top-up",
    horizon: "short",
    priority: "protected",
    target_sen: 250000,
    saved_sen: 115000,
    monthly_sen: 27000,
    months_left: 5,
    note: "Three weeks of expenses.",
  },
];

function renderPlan(initialView: "daily" | "goals" = "goals") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(dashboardTodayKey, { goals: GOALS });
  return render(
    <QueryClientProvider client={client}>
      <Plan initialView={initialView} />
    </QueryClientProvider>,
  );
}

describe("Plan", () => {
  it("shows the Goal Planner without a foresight entry point", () => {
    renderPlan();

    expect(screen.getByText("What are you saving toward?")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open foresight/i })).not.toBeInTheDocument();
    expect(screen.queryByText("The road ahead")).not.toBeInTheDocument();
  });

  it("uses the shared reveal motion when Goals is selected", async () => {
    renderPlan("daily");
    const user = userEvent.setup();

    await user.click(screen.getByRole("tab", { name: "Goals" }));

    expect(screen.getByText("What are you saving toward?").closest(".rv")).not.toBeNull();
    expect(screen.getByRole("group", { name: "Filter goals" }).closest(".rv")).not.toBeNull();
  });
});
