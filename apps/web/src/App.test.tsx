import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DayPlan, Transaction } from "@kira/contracts";

import { App } from "./App";

const DASHBOARD = {
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
  next_commitment: null,
  goals: [],
};

const DRAFT: Transaction = {
  id: "d1",
  merchant: "Nasi Kandar Pelita",
  amount_sen: 1890,
  category: "food",
  category_label: "Food & drink",
  occurred_on: "2026-09-03",
  status: "draft",
  source: "receipt",
  confidence: 94,
  note: "Line item total matched.",
};

const LEDGER_TXN: Transaction = {
  id: "t1",
  merchant: "Grab — KLCC to home",
  amount_sen: 1620,
  category: "transport",
  category_label: "Transport",
  occurred_on: "2026-09-02",
  status: "confirmed",
  source: "manual",
  confidence: null,
  note: "",
};

const ACTIVITY = {
  drafts: [DRAFT],
  draft_total_sen: 1890,
  days: [
    {
      date: "2026-09-02",
      total_sen: 1620,
      transactions: [LEDGER_TXN],
    },
  ],
  spent_this_cycle_sen: 1620,
  categories: [{ slug: "transport", label: "Transport", spent_this_cycle_sen: 1620, count: 1 }],
};

const FORESIGHT = {
  horizon_days: 180,
  dates: ["2026-09-04", "2027-03-02"],
  p10: [{ sen: 400000, currency: "MYR" }, { sen: 170000, currency: "MYR" }],
  p50: [{ sen: 425000, currency: "MYR" }, { sen: 350000, currency: "MYR" }],
  p90: [{ sen: 440000, currency: "MYR" }, { sen: 560000, currency: "MYR" }],
  outlooks: [
    {
      goal_id: "g1",
      target_date: "2027-02-15",
      probability_bp: 6200,
      median_shortfall: { sen: 30000, currency: "MYR" },
    },
  ],
  drivers: [],
  profile_days: 90,
  assumption: "Based on your last 90 days of confirmed spending. It is a projection, not a promise.",
};

/** Typed against the contract on purpose: an untyped literal here would go on
 *  compiling after the API grew a field, and the shell would be exercised
 *  against a response the API cannot send. The counts are what tell the three
 *  empty lists apart, so they are stated too. */
const DAY_PLAN: DayPlan = {
  room_sen: 5297,
  cap_sen: 5297,
  kind: null,
  nearby_count: 1,
  matching_count: 1,
  kind_count: 1,
  places: [
    {
      id: "p1",
      name: "Nasi Kandar Pelita",
      kind: "Mamak",
      address: "166 Jalan Ampang, 50450 Kuala Lumpur",
      lat: 3.1591,
      lng: 101.7132,
      km: 0.65,
      road_km: 0.65,
      distance_basis: "road",
      travel_sen: 0,
      minutes: 14,
      total_sen: 1250,
      share: 0.24,
      band: "ok",
      confidence: "high",
      note: "Fast counter service, open late.",
      halal: true,
    },
  ],
  nearest_over_cap: [],
};

/** Mutable so a test can prove the screens re-read after a confirm. */
let activity = ACTIVITY;
let dashboard = DASHBOARD;
let asked: (string | null)[] = [];
/** What a correction actually put on the wire, and how often Today re-read. */
let corrected: unknown = null;
let dashboardReads = 0;

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  activity = ACTIVITY;
  dashboard = DASHBOARD;
  asked = [];
  corrected = null;
  dashboardReads = 0;
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/v1/auth/refresh")) return new Response("", { status: 401 });
      if (url.endsWith("/v1/auth/login")) {
        return new Response(JSON.stringify({ access_token: "t", token_type: "bearer" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith("/v1/butler/thread")) {
        return new Response(
          JSON.stringify({ id: "t1", title: "Butler", messages: [], pending_approvals: [] }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      if (url.endsWith("/v1/briefings/today")) {
        return new Response(JSON.stringify(null), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith("/v1/categories")) {
        return new Response(JSON.stringify([{ slug: "food", label: "Food & drink" }]), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith("/v1/butler/messages")) {
        const done = {
          type: "done",
          answer: "I have written it up as a draft for you to check.",
          evidence: [],
          tools_used: [],
          approval: null,
        };
        return new Response(`data: ${JSON.stringify(done)}\n\n`, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        });
      }
      if (url.endsWith("/v1/dashboard/today")) {
        dashboardReads += 1;
        return new Response(JSON.stringify(dashboard), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith("/v1/foresight")) {
        return new Response(JSON.stringify(FORESIGHT), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith(`/v1/transactions/${DRAFT.id}`) && init?.method === "PATCH") {
        corrected = JSON.parse(String(init.body));
        // The API clears the confidence on any amount it did not read itself.
        const draft = { ...DRAFT, ...(corrected as object), confidence: null };
        activity = { ...ACTIVITY, drafts: [draft], draft_total_sen: draft.amount_sen };
        return new Response(JSON.stringify(draft), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.includes("/v1/transactions?category=")) {
        asked.push(new URL(url, "http://test").searchParams.get("category"));
        return new Response(JSON.stringify({ ...activity, days: [], spent_this_cycle_sen: 0 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith("/v1/transactions")) {
        return new Response(JSON.stringify(activity), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith(`/v1/transactions/${LEDGER_TXN.id}/unconfirm`)) {
        activity = { ...ACTIVITY, days: [] , spent_this_cycle_sen: 0 };
        return new Response(JSON.stringify({ ...LEDGER_TXN, status: "draft" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith(`/v1/transactions/${DRAFT.id}/confirm`)) {
        activity = { ...ACTIVITY, drafts: [], draft_total_sen: 0 };
        dashboard = { ...DASHBOARD, safe_today_sen: 3321, drafts_waiting: 0 };
        return new Response(JSON.stringify({ ...DRAFT, status: "confirmed" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.includes("/v1/day-plan/places")) {
        return new Response(JSON.stringify(DAY_PLAN), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response("", { status: 404 });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("App", () => {
  it("shows the login gate before authentication", async () => {
    renderApp();
    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("renders the five navigation tabs once signed in", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));

    for (const label of ["Today", "Activity", "Butler", "Plan", "More"]) {
      expect(await screen.findByRole("button", { name: new RegExp(`^${label}$`, "i") })).toBeInTheDocument();
    }
  });

  it("shows the ledger on the Activity tab", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));
    await user.click(await screen.findByRole("button", { name: /^Activity$/i }));

    expect(await screen.findByText("Nasi Kandar Pelita")).toBeInTheDocument();
    expect(screen.getByText("Grab — KLCC to home")).toBeInTheDocument();
  });

  it("moves today's safe-to-spend when a draft is confirmed", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));
    await user.click(await screen.findByRole("button", { name: /^Activity$/i }));
    await user.click(await screen.findByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText(/Nothing waiting/)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /^Today$/i }));
    expect(await screen.findByLabelText("RM33.21")).toBeInTheDocument();
  });

  it("corrects a misread amount in sen, and re-reads both screens", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));
    await user.click(await screen.findByRole("button", { name: /^Activity$/i }));
    await user.click(await screen.findByRole("button", { name: "Details" }));
    const readsBefore = dashboardReads;

    await user.click(screen.getByRole("button", { name: "Correct" }));
    const field = screen.getByLabelText("Amount in ringgit");
    await user.clear(field);
    await user.type(field, "19.90");
    await user.click(screen.getByRole("button", { name: "Save" }));

    // Ringgit on screen, sen on the wire.
    await waitFor(() => expect(corrected).toEqual({ amount_sen: 1990 }));
    // The ledger re-reads, so the corrected figure replaces what was heard,
    // in the card's head and in the details row it was typed into…
    await waitFor(() => expect(screen.getAllByText("RM19.90")).toHaveLength(2));
    expect(screen.getByText(/Your figure, not a read/)).toBeInTheDocument();
    // …and so does Today, which no safe-to-spend may outlive.
    await waitFor(() => expect(dashboardReads).toBeGreaterThan(readsBefore));
  });

  it("opens a ledger row and moves it back to the drafts", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));
    await user.click(await screen.findByRole("button", { name: /^Activity$/i }));
    await user.click(await screen.findByRole("button", { name: /Grab — KLCC to home/ }));

    await user.click(screen.getByRole("button", { name: /Move back to drafts/ }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText(/Nothing on your ledger yet/)).toBeInTheDocument();
  });

  it("asks the API for the category that was tapped", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));
    await user.click(await screen.findByRole("button", { name: /^Activity$/i }));
    await user.click(await screen.findByRole("radio", { name: /Transport/ }));

    await waitFor(() => expect(asked).toContain("transport"));
    expect(await screen.findByText(/Nothing under Transport this cycle/)).toBeInTheDocument();
  });

  it("switches tabs without losing the shell", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));
    await user.click(await screen.findByRole("button", { name: /^Plan$/i }));
    await user.click(await screen.findByRole("tab", { name: "Goals" }));
    await user.click(await screen.findByRole("button", { name: /open foresight/i }));

    expect(await screen.findByText("The road ahead")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Today$/i })).toBeInTheDocument();
  });

  it("keeps Daily and Goals inside the selected Plan tab", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));
    const planNav = await screen.findByRole("button", { name: /^Plan$/i });
    await user.click(planNav);

    const daily = await screen.findByRole("tab", { name: "Daily" });
    const goals = screen.getByRole("tab", { name: "Goals" });
    expect(daily).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText(/What today's money can buy/i)).toBeVisible();
    expect(planNav).toHaveClass("active");

    await user.click(goals);
    expect(goals).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("Start with one goal that matters")).toBeVisible();
    expect(screen.queryByText(/What today's money can buy/i)).not.toBeInTheDocument();
    expect(planNav).toHaveClass("active");
    expect(
      within(screen.getByRole("navigation")).queryByRole("button", { name: "Goals" }),
    ).not.toBeInTheDocument();

    await user.click(daily);
    expect(daily).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText(/What today's money can buy/i)).toBeVisible();
  });

  it("opens the existing Today goals card in PLAN's Goals mode", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));
    await user.click(await screen.findByRole("button", { name: /Your goals/i }));

    expect(await screen.findByRole("tab", { name: "Goals" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("Start with one goal that matters")).toBeVisible();
    expect(screen.getByRole("button", { name: /^Plan$/i })).toHaveClass("active");
  });
});

describe("Adding spending from anywhere", () => {
  async function signedIn() {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));
    return user;
  }

  it("offers one way in from Today", async () => {
    const user = await signedIn();
    await user.click(await screen.findByRole("button", { name: "Add spending" }));
    expect(await screen.findByRole("tab", { name: "Type" })).toBeInTheDocument();
  });

  it("offers the same way in from Activity", async () => {
    const user = await signedIn();
    await user.click(await screen.findByRole("button", { name: /^Activity$/i }));
    await user.click(await screen.findByRole("button", { name: "Add spending" }));
    expect(await screen.findByRole("tab", { name: "Show" })).toBeInTheDocument();
  });

  it("does not interrupt the Butler with a second way in", async () => {
    const user = await signedIn();
    await user.click(await screen.findByRole("button", { name: /^Butler$/i }));
    expect(screen.queryByRole("button", { name: "Add spending" })).not.toBeInTheDocument();
  });

  it("carries a typed sentence to the Butler and asks it there", async () => {
    const user = await signedIn();
    await user.click(await screen.findByRole("button", { name: "Add spending" }));
    await user.type(
      await screen.findByLabelText("What did you spend?"),
      "grabbed lunch at the mamak, twelve fifty",
    );
    await user.click(screen.getByRole("button", { name: /Tell Kira/ }));

    expect(
      await screen.findByText("grabbed lunch at the mamak, twelve fifty"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/I have written it up as a draft/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
