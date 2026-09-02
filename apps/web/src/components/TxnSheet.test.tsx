import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Transaction } from "@kira/contracts";

import { TxnSheet } from "./TxnSheet";

const INCOME: Transaction = {
  id: "10000000-0000-0000-0000-000000000001",
  merchant: "Salary",
  amount_sen: 500_000,
  category: "income",
  category_label: "Income",
  occurred_on: "2026-09-03",
  status: "confirmed",
  source: "manual",
  confidence: null,
  note: "",
  direction: "income",
  income_type: "salary",
  goal_allocation_applied: false,
};

const PLAN = {
  income_transaction_id: INCOME.id,
  income_amount_sen: 500_000,
  available_for_goals_sen: 150_000,
  protected_commitments_sen: 200_000,
  emergency_buffer_sen: 80_000,
  allocated_sen: 150_000,
  unallocated_income_sen: 350_000,
  allocations: [
    {
      goal_id: "20000000-0000-0000-0000-000000000001",
      name: "House",
      priority: "important",
      amount_sen: 150_000,
      income_share_bp: 3000,
      remaining_after_sen: 4_850_000,
    },
  ],
  risk_flags: [],
  assumptions: [],
  calculation_version: "goal-allocation-v1",
  evidence_refs: [],
};

afterEach(() => vi.unstubAllGlobals());

describe("TxnSheet income allocation", () => {
  it("shows the deterministic split and earmarks it only after approval", async () => {
    const fetch = vi.fn((_: RequestInfo | URL, init?: RequestInit) =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(init?.method === "POST" ? { plan: PLAN, contributions: [] } : PLAN),
        text: () => Promise.resolve(""),
      } as Response),
    );
    vi.stubGlobal("fetch", fetch);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <TxnSheet txn={INCOME} onUnconfirm={vi.fn()} onClose={vi.fn()} busy={false} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/House · important/)).toBeInTheDocument();
    expect(screen.getByText(/RM1,500.00 · 30.00%/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approve goal contributions" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      `/v1/transactions/${INCOME.id}/goal-allocation/approve`,
      expect.objectContaining({ method: "POST" }),
    ));
    expect(await screen.findByText(/already earmarked/)).toBeInTheDocument();
  });
});
