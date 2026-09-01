import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DashboardToday, GoalDetail, GoalPlan, GoalScenario } from "@kira/contracts";

import { GoalPlanner } from "./GoalPlanner";

const SHORT_ID = "11111111-1111-4111-8111-111111111111";
const LONG_ID = "22222222-2222-4222-8222-222222222222";
const APPROVAL_ID = "33333333-3333-4333-8333-333333333333";

const DASHBOARD: DashboardToday = {
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
  drafts_waiting: 0,
  next_commitment: null,
  goals: [],
};

const DETAIL: GoalDetail = {
  goal_id: LONG_ID,
  user_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  goal_type: "house_down_payment",
  name: "First home",
  currency: "MYR",
  target_amount_sen: 5000000,
  current_saved_sen: 800000,
  target_date: "2028-12-31",
  horizon: "long",
  priority: "important",
  status: "active",
  funding_account_ids: [],
  current_plan_version: 1,
};

const PLAN: GoalPlan = {
  plan_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  goal_id: LONG_ID,
  version: 1,
  approval_status: "approved",
  feasible: true,
  target_amount_sen: 5000000,
  current_saved_sen: 800000,
  remaining_amount_sen: 4200000,
  target_date: "2028-12-31",
  required_contribution_per_payday_sen: 150000,
  next_required_reserve_sen: 150000,
  projected_completion_date: "2028-12-15",
  milestones: [{ percentage: 50, amount_sen: 2500000, projected_date: "2027-11-30" }],
  risk_flags: [],
  assumptions: ["confirmed income schedule"],
  calculation_version: "goal-v1",
  evidence_refs: ["income:1"],
};

const DRAFT = {
  ...PLAN,
  plan_id: undefined,
  version: undefined,
  approval_status: undefined,
};

const SCENARIO: GoalScenario = {
  scenario_id: "44444444-4444-4444-8444-444444444444",
  goal_id: LONG_ID,
  label: "Extend the target date",
  feasible: true,
  contribution_per_payday_sen: 120000,
  target_date: "2029-06-30",
  goal_delay_days: 181,
  flexible_spending_delta_sen: 30000,
  tradeoffs: ["The goal completes later."],
  risk_flags: [],
  calculation_version: "goal-v1",
  evidence_refs: ["income:1"],
};

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function stream(...events: unknown[]) {
  return new Response(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""), {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

function renderGoals() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><GoalPlanner /></QueryClientProvider>);
}

function detailFor(id: string, horizon: "short" | "long" = "long"): GoalDetail {
  return {
    ...DETAIL,
    goal_id: id,
    name: id === SHORT_ID ? "Japan trip" : "First home",
    goal_type: id === SHORT_ID ? "travel" : "house_down_payment",
    horizon,
    target_date: horizon === "short" ? "2027-03-01" : "2028-12-31",
  };
}

function planFor(id: string): GoalPlan {
  return { ...PLAN, goal_id: id, plan_id: id.replace(/1|2/g, "b") };
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => vi.unstubAllGlobals());

describe("Goal Planner", () => {
  it("shows an empty state and validates the create form before calling the backend", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      if (String(input).endsWith("/v1/dashboard/today")) return json(DASHBOARD);
      return json({}, 404);
    });
    const user = userEvent.setup();
    renderGoals();

    expect(await screen.findByText("Start with one goal that matters")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Create your first goal" }));
    await user.click(screen.getByRole("button", { name: "Calculate plan" }));

    expect(screen.getByText("Enter a target greater than RM0.00.")).toBeVisible();
    expect(screen.getByText("Choose a future target date.")).toBeVisible();
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  });

  it("sends integer sen, renders the backend plan, and applies only after approval", async () => {
    let runBody: Record<string, unknown> | null = null;
    let approvalBody: Record<string, unknown> | null = null;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/v1/dashboard/today")) return json(DASHBOARD);
      if (url.endsWith("/v1/goals/runs")) {
        runBody = JSON.parse(String(init?.body));
        return json({
          request_id: "55555555-5555-4555-8555-555555555555",
          thread_id: "66666666-6666-4666-8666-666666666666",
          final_response: "Set aside the calculated amount.",
          llm_calls: 0,
          goal_id: LONG_ID,
          feasible: true,
          approval: {
            approval_id: APPROVAL_ID,
            tool: "apply_goal_plan_change",
            summary: "Create and activate this goal plan.",
            base_plan_version: 1,
            before: null,
            after: DRAFT,
          },
          errors: [],
        });
      }
      if (url.endsWith(`/v1/butler/approvals/${APPROVAL_ID}/respond`)) {
        approvalBody = JSON.parse(String(init?.body));
        return stream({ type: "done", answer: "Plan approved.", approval: null, applied: { tool: "apply_goal_plan_change", summary: "saved" } });
      }
      if (url.endsWith(`/v1/goals/${LONG_ID}`)) return json(DETAIL);
      if (url.endsWith(`/v1/goals/${LONG_ID}/plan`)) return json(PLAN);
      if (url.endsWith("/v1/butler/thread")) return json({ id: "t", title: "KIRA", messages: [], pending_approvals: [] });
      return json({}, 404);
    });
    const user = userEvent.setup();
    renderGoals();

    await user.click(await screen.findByRole("button", { name: "Create your first goal" }));
    await user.clear(screen.getByLabelText("Goal name"));
    await user.type(screen.getByLabelText("Goal name"), "First home");
    await user.type(screen.getByLabelText("Target amount"), "50,000.00");
    await user.clear(screen.getByLabelText("Amount already saved"));
    await user.type(screen.getByLabelText("Amount already saved"), "8,000.00");
    await user.type(screen.getByLabelText("Target date"), "2028-12-31");
    await user.click(screen.getByRole("button", { name: "Calculate plan" }));

    expect(await screen.findByText("On track with this backend-calculated reserve")).toBeVisible();
    expect(screen.getAllByText("RM1,500.00").length).toBeGreaterThan(0);
    expect(runBody).toMatchObject({
      text: "",
      explain: false,
      intent: {
        action: "create",
        target_amount_sen: 5_000_000,
        current_saved_sen: 800_000,
      },
    });
    expect(approvalBody).toBeNull();

    await user.click(screen.getByRole("button", { name: "Review & activate" }));
    expect(screen.getByRole("dialog", { name: "Review goal plan change" })).toBeVisible();
    expect(approvalBody).toBeNull();
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(approvalBody).toEqual({ action: "accept", args: null }));
    expect(await screen.findByText("First home")).toBeVisible();
  });

  it("filters real backend goals by horizon", async () => {
    const dashboard = {
      ...DASHBOARD,
      goals: [
        { id: SHORT_ID, name: "Japan trip", horizon: "short", target_sen: 500000, saved_sen: 100000, monthly_sen: 50000, months_left: 8, note: "" },
        { id: LONG_ID, name: "First home", horizon: "long", target_sen: 5000000, saved_sen: 800000, monthly_sen: 150000, months_left: 28, note: "" },
      ],
    } satisfies DashboardToday;
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/v1/dashboard/today")) return json(dashboard);
      if (url.endsWith(`/v1/goals/${SHORT_ID}`)) return json(detailFor(SHORT_ID, "short"));
      if (url.endsWith(`/v1/goals/${LONG_ID}`)) return json(detailFor(LONG_ID));
      if (url.endsWith(`/v1/goals/${SHORT_ID}/plan`)) return json(planFor(SHORT_ID));
      if (url.endsWith(`/v1/goals/${LONG_ID}/plan`)) return json(planFor(LONG_ID));
      return json({}, 404);
    });
    const user = userEvent.setup();
    renderGoals();

    expect(await screen.findByText("Japan trip")).toBeVisible();
    expect(await screen.findByText("First home")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Short-term" }));
    expect(screen.getByText("Japan trip")).toBeVisible();
    expect(screen.queryByText("First home")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Long-term" }));
    expect(screen.queryByText("Japan trip")).not.toBeInTheDocument();
    expect(screen.getByText("First home")).toBeVisible();
  });

  it("renders backend scenarios when a newly calculated target is infeasible", async () => {
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/v1/dashboard/today")) return json(DASHBOARD);
      if (url.endsWith("/v1/goals/runs")) {
        expect(JSON.parse(String(init?.body))).toMatchObject({ intent: { target_amount_sen: 9_000_000 } });
        return json({
          request_id: "55555555-5555-4555-8555-555555555555",
          thread_id: "66666666-6666-4666-8666-666666666666",
          final_response: "The target needs adjustment.", llm_calls: 0, goal_id: LONG_ID, feasible: false, errors: [],
          approval: { approval_id: APPROVAL_ID, tool: "apply_goal_plan_change", summary: "Create goal.", base_plan_version: 1, before: null, after: { ...DRAFT, feasible: false, target_amount_sen: 9_000_000, remaining_amount_sen: 8_200_000, risk_flags: ["insufficient_surplus"] } },
        });
      }
      if (url.endsWith(`/v1/goals/${LONG_ID}/scenarios`)) return json({ scenarios: [SCENARIO] });
      return json({}, 404);
    });
    const user = userEvent.setup();
    renderGoals();
    await user.click(await screen.findByRole("button", { name: "Create your first goal" }));
    await user.type(screen.getByLabelText("Target amount"), "90,000.00");
    await user.type(screen.getByLabelText("Target date"), "2028-12-31");
    await user.click(screen.getByRole("button", { name: "Calculate plan" }));

    expect(await screen.findByText("This target needs adjustment")).toBeVisible();
    expect(await screen.findByText("Extend the target date")).toBeVisible();
    expect(screen.getByText("Insufficient surplus")).toBeVisible();
  });

  it("keeps scenario selection local and rejects through the approval endpoint", async () => {
    const dashboard = { ...DASHBOARD, goals: [{ id: LONG_ID, name: "First home", horizon: "long", target_sen: 5000000, saved_sen: 800000, monthly_sen: 150000, months_left: 28, note: "" }] } satisfies DashboardToday;
    let runCalls = 0;
    let decision: Record<string, unknown> | null = null;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/v1/dashboard/today")) return json(dashboard);
      if (url.endsWith(`/v1/goals/${LONG_ID}`)) return json(DETAIL);
      if (url.endsWith(`/v1/goals/${LONG_ID}/plan`)) return json(PLAN);
      if (url.endsWith(`/v1/goals/${LONG_ID}/scenarios`)) return json({ scenarios: [SCENARIO] });
      if (url.endsWith("/v1/goals/runs")) {
        runCalls += 1;
        return json({
          request_id: "55555555-5555-4555-8555-555555555555",
          thread_id: "66666666-6666-4666-8666-666666666666",
          final_response: "Alternative calculated.", llm_calls: 0, goal_id: LONG_ID, feasible: true, errors: [],
          approval: { approval_id: APPROVAL_ID, tool: "apply_goal_plan_change", summary: "Change active plan.", base_plan_version: 1, before: DRAFT, after: { ...DRAFT, target_date: SCENARIO.target_date, required_contribution_per_payday_sen: SCENARIO.contribution_per_payday_sen } },
        });
      }
      if (url.endsWith(`/v1/butler/approvals/${APPROVAL_ID}/respond`)) {
        decision = JSON.parse(String(init?.body));
        return stream({ type: "done", answer: "Change rejected.", approval: { id: APPROVAL_ID, status: "rejected" }, applied: null });
      }
      if (url.endsWith("/v1/butler/thread")) return json({ id: "t", title: "KIRA", messages: [], pending_approvals: [] });
      return json({}, 404);
    });
    const user = userEvent.setup();
    renderGoals();
    await user.click((await screen.findAllByRole("button", { name: "View plan" }))[0]!);
    expect(await screen.findByRole("progressbar", { name: "First home progress" })).toHaveAttribute("aria-valuenow", "16");
    await user.click(screen.getByRole("button", { name: "View scenarios" }));
    const scenario = await screen.findByRole("button", { name: /Extend the target date/ });
    await user.click(scenario);
    expect(runCalls).toBe(0);
    expect(screen.getByText("Selected only — your active plan has not changed.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Review this change" }));
    expect(await screen.findByRole("dialog", { name: "Review goal plan change" })).toBeVisible();
    expect(runCalls).toBe(1);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(decision).toEqual({ action: "reject", args: null }));
    expect(await screen.findByText("Change rejected. Your current plan is unchanged.")).toBeVisible();
  });

  it("sends edits back for recalculation and requires approval again", async () => {
    const replacementId = "77777777-7777-4777-8777-777777777777";
    const dashboard = { ...DASHBOARD, goals: [{ id: LONG_ID, name: "First home", horizon: "long", target_sen: 5000000, saved_sen: 800000, monthly_sen: 150000, months_left: 28, note: "" }] } satisfies DashboardToday;
    const decisions: { id: string; body: Record<string, unknown> }[] = [];
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/v1/dashboard/today")) return json(dashboard);
      if (url.endsWith(`/v1/goals/${LONG_ID}`)) return json(DETAIL);
      if (url.endsWith(`/v1/goals/${LONG_ID}/plan`)) return json(PLAN);
      if (url.endsWith(`/v1/goals/${LONG_ID}/scenarios`)) return json({ scenarios: [SCENARIO] });
      if (url.endsWith("/v1/goals/runs")) return json({
        request_id: "55555555-5555-4555-8555-555555555555", thread_id: "66666666-6666-4666-8666-666666666666",
        final_response: "Alternative calculated.", llm_calls: 0, goal_id: LONG_ID, feasible: true, errors: [],
        approval: { approval_id: APPROVAL_ID, tool: "apply_goal_plan_change", summary: "Change plan.", base_plan_version: 1, before: DRAFT, after: { ...DRAFT, required_contribution_per_payday_sen: 120000 } },
      });
      if (url.endsWith(`/v1/butler/approvals/${APPROVAL_ID}/respond`)) {
        decisions.push({ id: APPROVAL_ID, body: JSON.parse(String(init?.body)) });
        return stream(
          { type: "approval", approval_id: replacementId, tool: "apply_goal_plan_change", module: "goal_planning", summary: "Edited plan.", args: {}, base_plan_version: 1, before: DRAFT, after: { ...DRAFT, target_amount_sen: 6_000_000, remaining_amount_sen: 5_200_000, required_contribution_per_payday_sen: 100000 } },
          { type: "done", answer: "Edited plan calculated.", approval: { approval_id: replacementId }, applied: null },
        );
      }
      if (url.endsWith(`/v1/butler/approvals/${replacementId}/respond`)) {
        decisions.push({ id: replacementId, body: JSON.parse(String(init?.body)) });
        return stream({ type: "done", answer: "Updated.", approval: null, applied: { tool: "apply_goal_plan_change", summary: "saved" } });
      }
      if (url.endsWith("/v1/butler/thread")) return json({ id: "t", title: "KIRA", messages: [], pending_approvals: [] });
      return json({}, 404);
    });
    const user = userEvent.setup();
    renderGoals();
    await user.click((await screen.findAllByRole("button", { name: "View plan" }))[0]!);
    await user.click(await screen.findByRole("button", { name: "View scenarios" }));
    await user.click(await screen.findByRole("button", { name: /Extend the target date/ }));
    await user.click(screen.getByRole("button", { name: "Review this change" }));
    const dialog = await screen.findByRole("dialog", { name: "Review goal plan change" });
    await user.click(within(dialog).getByRole("button", { name: "Edit" }));
    await user.clear(within(dialog).getByLabelText("Edited target amount"));
    await user.type(within(dialog).getByLabelText("Edited target amount"), "60,000.00");
    await user.clear(within(dialog).getByLabelText("Edited contribution per payday"));
    await user.type(within(dialog).getByLabelText("Edited contribution per payday"), "1,000.00");
    await user.click(within(dialog).getByRole("button", { name: "Recalculate" }));

    await waitFor(() => expect(decisions[0]).toEqual({
      id: APPROVAL_ID,
      body: { action: "edit", args: { target_amount_sen: 6_000_000, contribution_per_payday_sen: 100_000, target_date: "2028-12-31" } },
    }));
    expect(await within(dialog).findByText("RM1,000.00")).toBeVisible();
    expect(decisions).toHaveLength(1);
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(decisions[1]).toEqual({ id: replacementId, body: { action: "accept", args: null } }));
    expect(await screen.findByText("Your approved plan is now updated.")).toBeVisible();
  });

  it("shows a retryable goal-home error", async () => {
    vi.mocked(fetch).mockResolvedValue(json({ detail: "offline" }, 503));
    renderGoals();
    expect(await screen.findByText("Your goals couldn’t be loaded")).toBeVisible();
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });
});
