import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ButlerThread } from "@kira/contracts";

import { handToButler, takeButlerHandoff } from "../lib/butlerHandoff";
import { Butler } from "./Butler";

const EMPTY_THREAD: ButlerThread = {
  id: "t1",
  title: "Butler",
  messages: [],
  pending_approvals: [],
};

/** One SSE body, framed exactly as the server frames it. */
function sse(...events: object[]): string {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
}

/** A stream a test can feed frame by frame, to observe the turn mid-flight. */
function controlled(): { response: Response; push: (event: object) => void; close: () => void } {
  const encoder = new TextEncoder();
  let controller: ReadableStreamDefaultController<Uint8Array>;
  const response = {
    ok: true,
    status: 200,
    body: new ReadableStream<Uint8Array>({
      start(c) {
        controller = c;
      },
    }),
  } as unknown as Response;
  return {
    response,
    push: (event) => controller.enqueue(encoder.encode(sse(event))),
    close: () => controller.close(),
  };
}

function streamed(body: string): Response {
  const encoder = new TextEncoder();
  return {
    ok: true,
    status: 200,
    body: new ReadableStream({
      start(controller) {
        // Two chunks, split mid-frame, so the reader's buffering is exercised.
        const bytes = encoder.encode(body);
        const half = Math.floor(bytes.length / 2);
        controller.enqueue(bytes.slice(0, half));
        controller.enqueue(bytes.slice(half));
        controller.close();
      },
    }),
  } as unknown as Response;
}

const ANSWER = sse(
  { type: "message", id: "m1", role: "user" },
  { type: "thinking", text: "Reading your accounts" },
  { type: "tool", tool: "calculate_safe_to_spend", module: "dashboard", label: "Checking what today can take" },
  { type: "evidence", rows: [["Safe to spend today", "RM52.97"]] },
  { type: "token", text: "Yes — RM20 for lunch leaves you RM32.97 today.\n" },
  { type: "token", text: "Bills and your buffer were set aside first." },
  {
    type: "done",
    answer: "Yes — RM20 for lunch leaves you RM32.97 today.\nBills and your buffer were set aside first.",
    evidence: [["Safe to spend today", "RM52.97"], ["Lunch", "RM20.00"]],
    tools_used: ["calculate_safe_to_spend"],
    approval: null,
  },
);

const PROPOSAL = sse(
  { type: "message", id: "m2", role: "user" },
  {
    type: "approval",
    approval_id: "a1",
    tool: "remember",
    module: "memory",
    summary: "Remember: I split rent with Aida.",
    args: {},
  },
  {
    type: "done",
    answer: "Noted — I will hold on to that.",
    evidence: [],
    tools_used: [],
    approval: { approval_id: "a1", summary: "Remember: I split rent with Aida." },
  },
);

const GOAL_PROPOSAL = sse(
  { type: "message", id: "m3", role: "user" },
  {
    type: "approval",
    approval_id: "goal-a1",
    tool: "apply_goal_plan_change",
    module: "goal_planning",
    summary: "Goal plan change — before: no active plan; after: RM100 per payday.",
    args: {
      before: null,
      after: {
        target_amount_sen: 100000,
        current_saved_sen: 20000,
        required_contribution_per_payday_sen: 10000,
        target_date: "2026-12-31",
        feasible: true,
      },
      base_plan_version: 1,
    },
  },
  {
    type: "done",
    answer: "Set aside RM100 per payday.",
    evidence: [],
    tools_used: ["start_goal_planning"],
    approval: { approval_id: "goal-a1", summary: "Goal plan change" },
  },
);

const CATEGORIES = [
  { slug: "food", label: "Food & drink" },
  { slug: "transport", label: "Transport" },
  { slug: "groceries", label: "Groceries" },
];

function setup(thread: ButlerThread | undefined = EMPTY_THREAD) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Butler thread={thread} isLoading={false} categories={CATEGORIES} />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

describe("Butler", () => {
  beforeEach(() => {
    // A fresh Response per call: a stream can only be read once.
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(streamed(ANSWER))));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("says what it will and will not do before anything is asked", () => {
    setup();
    expect(screen.getByText(/move money/)).toBeInTheDocument();
    expect(screen.getByText(/I show you the numbers I used/)).toBeInTheDocument();
  });

  it("offers the demo questions as starting points", () => {
    setup();
    expect(screen.getByRole("button", { name: "Why did safe-to-spend drop?" })).toBeInTheDocument();
  });

  it("shows the question, then the streamed answer", async () => {
    const user = setup();
    await user.type(screen.getByLabelText("Ask Kira"), "Can I afford RM20 lunch?{Enter}");

    expect(screen.getByText("Can I afford RM20 lunch?")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/Yes — RM20 for lunch/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/Bills and your buffer were set aside first/)).toBeInTheDocument();
  });

  it("renders the evidence the tools returned", async () => {
    const user = setup();
    await user.click(screen.getByRole("button", { name: "Why did safe-to-spend drop?" }));

    await waitFor(() => expect(screen.getByText("What I used")).toBeInTheDocument());
    expect(screen.getByText("Safe to spend today")).toBeInTheDocument();
    expect(screen.getByText("RM52.97")).toBeInTheDocument();
  });

  it("names the tool it is running while it runs", async () => {
    const { response, push, close } = controlled();
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response)));
    const user = setup();

    await user.click(screen.getByRole("button", { name: "What bills are due?" }));
    push({ type: "tool", tool: "list_commitments", module: "commitments", label: "Reading your bills" });
    await waitFor(() => expect(screen.getByText("Reading your bills")).toBeInTheDocument());

    push({ type: "done", answer: "Rent is next.", evidence: [], tools_used: [], approval: null });
    close();
    await waitFor(() => expect(screen.getByText("Rent is next.")).toBeInTheDocument());
    expect(screen.queryByText("Reading your bills")).not.toBeInTheDocument();
  });

  it("does not send an empty question", async () => {
    const user = setup();
    await user.click(screen.getByLabelText("Send"));
    expect(fetch).not.toHaveBeenCalled();
  });

  it("replays the thread it was given", () => {
    setup({
      ...EMPTY_THREAD,
      messages: [
        {
          id: "m0",
          role: "user",
          content: "Where do I stand?",
          evidence: [],
          attachment: null,
          created_at: "2026-09-03T04:00:00Z",
        },
        {
          id: "m1",
          role: "kira",
          content: "You have RM52.97 safe to spend today.",
          evidence: [["Balance", "RM4,180.40"]],
          attachment: null,
          created_at: "2026-09-03T04:00:01Z",
        },
      ],
    });
    expect(screen.getByText("Where do I stand?")).toBeInTheDocument();
    expect(screen.getByText("RM4,180.40")).toBeInTheDocument();
  });

  it("shows every prepared morning approval, not just the last one", () => {
    setup({
      ...EMPTY_THREAD,
      messages: [
        {
          id: "m1",
          role: "kira",
          content: "Your overnight money check is ready.",
          evidence: [],
          attachment: null,
          created_at: "2026-09-03T04:00:00Z",
        },
      ],
      pending_approvals: [
        {
          id: "a1",
          thread_id: "t1",
          tool: "confirm_draft",
          args: { transaction_id: "d1" },
          summary: "Confirm Nasi Kandar Pelita for MYR 18.90.",
          evidence: [],
          status: "pending",
          created_at: "2026-09-03T04:00:00Z",
        },
        {
          id: "a2",
          thread_id: "t1",
          tool: "confirm_draft",
          args: { transaction_id: "d2" },
          summary: "Confirm Grab for MYR 14.00.",
          evidence: [],
          status: "pending",
          created_at: "2026-09-03T04:00:00Z",
        },
      ],
    });

    expect(screen.getAllByRole("button", { name: "Approve" })).toHaveLength(2);
  });
});

describe("Butler approvals", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(streamed(PROPOSAL))));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a proposed change as not yet applied", async () => {
    const user = setup();
    await user.type(screen.getByLabelText("Ask Kira"), "Remember that{Enter}");

    await waitFor(() =>
      expect(screen.getByText("Proposed change · not applied")).toBeInTheDocument(),
    );
    expect(screen.getByText("Remember: I split rent with Aida.")).toBeInTheDocument();
    expect(screen.getByText(/Nothing changes until you approve/)).toBeInTheDocument();
  });

  it("sends the decision when the change is approved", async () => {
    const user = setup();
    await user.type(screen.getByLabelText("Ask Kira"), "Remember that{Enter}");
    await waitFor(() => screen.getByRole("button", { name: "Approve" }));

    await user.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/v1/butler/approvals/a1/respond",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("clears the card when the change is rejected", async () => {
    const settled = sse({
      type: "done",
      answer: "Rejected. Nothing changed.",
      evidence: [],
      tools_used: [],
      approval: null,
    });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(streamed(PROPOSAL))
        .mockResolvedValue(streamed(settled)),
    );
    const user = setup();
    await user.type(screen.getByLabelText("Ask Kira"), "Remember that{Enter}");
    await waitFor(() => screen.getByRole("button", { name: "Reject" }));

    await user.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() =>
      expect(screen.getByText("Rejected. Nothing changed.")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });
});

const LOG_PROPOSAL = sse(
  { type: "message", id: "m3", role: "user" },
  {
    type: "approval",
    approval_id: "a2",
    tool: "add_transaction",
    module: "ledger",
    summary: "Add Mamak for RM12.50 on 2026-09-03 as a draft.",
    args: {
      merchant: "Mamak",
      amount_sen: 1250,
      occurred_on: "2026-09-03",
      category: "food",
      note: "grabbed lunch at the mamak, twelve fifty",
    },
  },
  {
    type: "done",
    answer: "I have written it up as a draft for you to check.",
    evidence: [],
    tools_used: [],
    approval: { approval_id: "a2", summary: "Add Mamak for RM12.50 on 2026-09-03 as a draft." },
  },
);

/** The body a fetch call was made with, parsed back out. */
function bodyOf(call: [string, RequestInit]): Record<string, unknown> {
  return JSON.parse(String(call[1].body));
}

describe("Butler goal-plan approvals", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows deterministic before and after plan figures", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(streamed(GOAL_PROPOSAL))));
    const user = setup();
    await user.type(screen.getByLabelText("Ask Kira"), "Plan my trip{Enter}");

    await waitFor(() => expect(screen.getByText("No active plan")).toBeInTheDocument());
    expect(screen.getByText("RM100.00 / payday")).toBeInTheDocument();
    expect(screen.getByText("RM1,000.00 by 2026-12-31")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit plan" })).toBeInTheDocument();
  });

  it("sends integer-sen edits back for deterministic recalculation", async () => {
    const settled = sse({
      type: "done",
      answer: "I recalculated the plan.",
      evidence: [],
      tools_used: ["start_goal_planning"],
      approval: null,
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(streamed(GOAL_PROPOSAL))
      .mockResolvedValue(streamed(settled));
    vi.stubGlobal("fetch", fetchMock);
    const user = setup();
    await user.type(screen.getByLabelText("Ask Kira"), "Plan my trip{Enter}");
    await waitFor(() => screen.getByRole("button", { name: "Edit plan" }));

    await user.click(screen.getByRole("button", { name: "Edit plan" }));
    await user.clear(screen.getByLabelText("Target amount (RM)"));
    await user.type(screen.getByLabelText("Target amount (RM)"), "1200.50");
    await user.clear(screen.getByLabelText("Per payday (RM)"));
    await user.type(screen.getByLabelText("Per payday (RM)"), "125.25");
    await user.click(screen.getByRole("button", { name: "Recalculate" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [, options] = fetchMock.mock.calls[1]!;
    expect(JSON.parse((options as RequestInit).body as string)).toEqual({
      action: "edit",
      args: {
        target_amount_sen: 120050,
        contribution_per_payday_sen: 12525,
        target_date: "2026-12-31",
      },
    });
  });
});

describe("Correcting a proposal before approving it", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(streamed(LOG_PROPOSAL))));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function propose() {
    const user = setup();
    await user.type(screen.getByLabelText("Ask Kira"), "Grabbed lunch at the mamak{Enter}");
    await waitFor(() => screen.getByRole("button", { name: "Approve" }));
    return user;
  }

  it("shows what it heard as fields the user can change", async () => {
    await propose();
    expect(screen.getByLabelText("Merchant")).toHaveValue("Mamak");
    expect(screen.getByLabelText("Total")).toHaveValue(12.5);
    expect(screen.getByLabelText("Date")).toHaveValue("2026-09-03");
  });

  it("offers the ledger's own categories rather than free text", async () => {
    await propose();
    const category = screen.getByLabelText("Category");
    expect(category.tagName).toBe("SELECT");
    expect(category).toHaveValue("food");
    expect(screen.getByRole("option", { name: "Transport" })).toBeInTheDocument();
  });

  it("sends the corrected category as a slug the ledger can file", async () => {
    const user = await propose();
    await user.selectOptions(screen.getByLabelText("Category"), "transport");
    await user.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(1));
    const args = bodyOf(vi.mocked(fetch).mock.calls[1] as never).args as Record<string, unknown>;
    expect(args.category).toBe("transport");
  });

  it("approves untouched as an acceptance, not an edit", async () => {
    const user = await propose();
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(1));
    const body = bodyOf(vi.mocked(fetch).mock.calls[1] as never);
    expect(body.action).toBe("accept");
  });

  it("sends a corrected amount in sen", async () => {
    const user = await propose();
    const total = screen.getByLabelText("Total");
    await user.clear(total);
    await user.type(total, "13");
    await user.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(1));
    const body = bodyOf(vi.mocked(fetch).mock.calls[1] as never);
    expect(body.action).toBe("edit");
    expect((body.args as Record<string, unknown>).amount_sen).toBe(1300);
  });

  it("keeps the fields it was not asked to change", async () => {
    const user = await propose();
    await user.clear(screen.getByLabelText("Merchant"));
    await user.type(screen.getByLabelText("Merchant"), "Nasi Kandar Pelita");
    await user.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(1));
    const args = bodyOf(vi.mocked(fetch).mock.calls[1] as never).args as Record<string, unknown>;
    expect(args.merchant).toBe("Nasi Kandar Pelita");
    expect(args.amount_sen).toBe(1250);
    expect(args.occurred_on).toBe("2026-09-03");
  });

  it("leaves a proposal with nothing to correct as a plain card", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(streamed(PROPOSAL))));
    const user = setup();
    await user.type(screen.getByLabelText("Ask Kira"), "Remember that{Enter}");
    await waitFor(() => screen.getByRole("button", { name: "Approve" }));
    expect(screen.queryByLabelText("Merchant")).not.toBeInTheDocument();
  });
});

describe("When the turn cannot be sent", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: false, status: 503 } as Response)));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("says so in the thread rather than failing silently", async () => {
    const user = setup();
    await user.type(screen.getByLabelText("Ask Kira"), "Can I afford RM20 lunch?{Enter}");

    expect(await screen.findByText(/Something broke/)).toBeInTheDocument();
  });

  it("stops showing itself as working", async () => {
    const user = setup();
    await user.type(screen.getByLabelText("Ask Kira"), "Can I afford RM20 lunch?{Enter}");
    await screen.findByText(/Something broke/);

    expect(screen.getByLabelText("Ask Kira")).toBeEnabled();
  });
});

describe("Butler · a question handed over from another screen", () => {
  const HANDED = "under RM15, and what's actually good tonight";

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(streamed(ANSWER))));
  });

  afterEach(() => {
    takeButlerHandoff();
    vi.unstubAllGlobals();
  });

  it("asks it word for word, without it being typed again", async () => {
    handToButler(HANDED);

    setup();

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/v1/butler/messages",
        expect.objectContaining({ body: JSON.stringify({ text: HANDED, attachment: null }) }),
      ),
    );
    // On screen as the user's own turn, because it is: they wrote it, one tab
    // ago.
    expect(screen.getByText(HANDED)).toBeInTheDocument();
  });

  it("keeps the thread it was given, and puts the question after it", async () => {
    // The history load replaces the turns wholesale, so a question asked ahead
    // of it would vanish out of the conversation the moment the thread landed.
    handToButler(HANDED);

    setup({
      ...EMPTY_THREAD,
      messages: [
        {
          id: "m0",
          role: "user",
          content: "Where do I stand?",
          evidence: [],
          attachment: null,
          created_at: "2026-09-03T04:00:00Z",
        },
      ],
    });

    await waitFor(() => expect(screen.getByText(HANDED)).toBeInTheDocument());
    expect(screen.getByText("Where do I stand?")).toBeInTheDocument();
  });

  it("asks it once, however often the tab is opened", async () => {
    handToButler(HANDED);
    setup();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

    // Leaving the tab and coming back is a fresh mount over the same slot. A
    // question that stayed in it would be re-asked here, hours after it was
    // written and against numbers that have since moved.
    cleanup();
    setup();

    await waitFor(() => expect(screen.getByText(/move money/)).toBeInTheDocument());
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("asks nothing when nothing was handed over", async () => {
    setup();

    await waitFor(() => expect(screen.getByText(/move money/)).toBeInTheDocument());
    expect(fetch).not.toHaveBeenCalled();
  });
});
