import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VoiceSheet } from "./VoiceSheet";

const READ = {
  kind: "voice",
  is_transaction: true,
  source: "voice",
  merchant: "Grab — office to KLCC",
  amount_sen: 1400,
  occurred_on: "2026-09-03",
  category: "transport",
  confidence: 71,
  note: "Heard 'fourteen ringgit'. Amount is worth a second look.",
  transcript: "Grab from the office to KLCC, fourteen ringgit",
  fields: [
    { label: "Merchant", value: "Grab — office to KLCC", confidence: 71 },
    { label: "Total", value: "RM14.00", confidence: 71 },
    { label: "Date", value: "3 Sep 2026", confidence: 71 },
    { label: "Category", value: "Transport", confidence: 60 },
  ],
};

const QUESTION = {
  kind: "voice",
  is_transaction: false,
  source: "voice",
  merchant: null,
  amount_sen: null,
  occurred_on: "2026-09-03",
  category: "uncategorised",
  confidence: 92,
  note: "Transcribed locally with Whisper; no transaction was inferred.",
  transcript: "Can I afford RM60 dinner tonight?",
  fields: [],
};

function setup(onAsk = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <VoiceSheet onClose={vi.fn()} onAsk={onAsk} />
    </QueryClientProvider>,
  );
  return { user: userEvent.setup(), onAsk };
}

describe("VoiceSheet", () => {
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

  it("offers to record", () => {
    setup();
    expect(screen.getByRole("button", { name: /Record/ })).toBeInTheDocument();
  });

  it("says so rather than pretending when the microphone is refused", async () => {
    vi.stubGlobal("navigator", {
      ...navigator,
      mediaDevices: { getUserMedia: () => Promise.reject(new Error("denied")) },
    });
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: /Record/ }));
    await waitFor(() =>
      expect(screen.getByText(/will not give me the microphone/)).toBeInTheDocument(),
    );
  });

  it("shows the transcript and flags how sure it was", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Use a sample" }));

    await waitFor(() =>
      expect(screen.getByText(/Grab from the office to KLCC/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/71% confidence/)).toBeInTheDocument();
    expect(screen.getByText(/worth a second look/)).toBeInTheDocument();
  });

  it("sends the transcript as the question, not the guessed amount", async () => {
    const { user, onAsk } = setup();
    await user.click(screen.getByRole("button", { name: "Use a sample" }));
    await waitFor(() => screen.getByRole("button", { name: /Ask Kira/ }));

    await user.click(screen.getByRole("button", { name: /Ask Kira/ }));
    expect(onAsk).toHaveBeenCalledWith(READ.transcript, expect.objectContaining({ kind: "voice" }));
  });

  it("sends a spoken question to Kira without offering a ledger draft", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve(QUESTION),
      text: () => Promise.resolve(""),
    } as unknown as Response);
    const { user, onAsk } = setup();
    await user.click(screen.getByRole("button", { name: "Use a sample" }));

    await waitFor(() => expect(screen.getByText(QUESTION.transcript)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Save as draft" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Ask Kira about this/ }));
    expect(onAsk).toHaveBeenCalledWith(
      QUESTION.transcript,
      expect.objectContaining({ is_transaction: false, merchant: null, amount_sen: null }),
    );
  });
});
