import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ScanSheet } from "./ScanSheet";

const READ = {
  kind: "receipt",
  is_transaction: true,
  source: "receipt",
  merchant: "Nasi Kandar Pelita",
  amount_sen: 1890,
  occurred_on: "2026-09-03",
  category: "food",
  confidence: 94,
  note: "Line item total matched, tax line ignored.",
  transcript: "",
  fields: [
    { label: "Merchant", value: "Nasi Kandar Pelita", confidence: 94 },
    { label: "Total", value: "RM18.90", confidence: 94 },
    { label: "Date", value: "3 Sep 2026", confidence: 94 },
    { label: "Category", value: "Food & drink", confidence: 83 },
  ],
};

function setup(onAsk = vi.fn(), onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ScanSheet onClose={onClose} onAsk={onAsk} />
    </QueryClientProvider>,
  );
  return { user: userEvent.setup(), onAsk, onClose };
}

describe("ScanSheet", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(READ),
          text: () => Promise.resolve(""),
        } as unknown as Response),
      ),
    );
  });

  afterEach(() => vi.unstubAllGlobals());

  it("promises the photo goes no further than the reader", () => {
    setup();
    expect(screen.getByText(/Nothing reaches your ledger until you confirm it/)).toBeInTheDocument();
  });

  it("opens the rear camera on a phone rather than only the file picker", () => {
    setup();
    expect(screen.getByLabelText("Receipt photo")).toHaveAttribute("capture", "environment");
  });

  it("shows each field with how sure the reader was", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: /Use a sample/ }));

    await waitFor(() => expect(screen.getByText("Nasi Kandar Pelita")).toBeInTheDocument());
    expect(screen.getByText("RM18.90")).toBeInTheDocument();
    // The category was inferred, not read, and says so.
    expect(screen.getByText("83%")).toBeInTheDocument();
  });

  it("sends the read to the Butler as an attachment", async () => {
    const { user, onAsk } = setup();
    await user.click(screen.getByRole("button", { name: /Use a sample/ }));
    await waitFor(() => screen.getByRole("button", { name: /Ask Kira/ }));

    await user.click(screen.getByRole("button", { name: /Ask Kira/ }));
    expect(onAsk).toHaveBeenCalledWith(
      "What does this receipt do to my day?",
      expect.objectContaining({ merchant: "Nasi Kandar Pelita", amount_sen: 1890 }),
    );
  });

  it("saves it as a draft, and only as a draft", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: /Use a sample/ }));
    await waitFor(() => screen.getByRole("button", { name: "Save as draft" }));

    await user.click(screen.getByRole("button", { name: "Save as draft" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/v1/transactions",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const body = JSON.parse(vi.mocked(fetch).mock.calls.at(-1)![1]!.body as string);
    expect(body).toMatchObject({ amount_sen: 1890, source: "receipt", confidence: 94 });
    expect(body.status).toBeUndefined();
  });
});
