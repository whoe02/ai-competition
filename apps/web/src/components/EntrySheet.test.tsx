import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Category } from "@kira/contracts";

import { EntrySheet } from "./EntrySheet";

const CATEGORIES: Category[] = [
  { slug: "food", label: "Food & drink" },
  { slug: "transport", label: "Transport" },
  { slug: "uncategorised", label: "Uncategorised" },
];

function setup(onAsk = vi.fn(), onClose = vi.fn(), categories?: Category[]) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <EntrySheet onClose={onClose} onAsk={onAsk} categories={categories} />
    </QueryClientProvider>,
  );
  return { user: userEvent.setup(), onAsk, onClose };
}

/** What the last POST actually put on the wire. */
function sent(call = 0) {
  const [path, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[call]!;
  return { path, body: JSON.parse((init as RequestInit).body as string) };
}

describe("EntrySheet", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, status: 200 } as Response)));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("offers both routes, and opens on the one that reads a sentence", () => {
    setup();
    expect(screen.getByRole("tab", { name: "Ask Kira", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Manual" })).toBeInTheDocument();
  });

  it("offers the three ways of telling Kira about spending", () => {
    setup();
    expect(screen.getByRole("tab", { name: "Type" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Say" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Show" })).toBeInTheDocument();
  });

  it("opens on typing, because that is the one that always works", () => {
    setup();
    expect(screen.getByRole("tab", { name: "Type", selected: true })).toBeInTheDocument();
    expect(screen.getByLabelText("What did you spend?")).toBeInTheDocument();
  });

  it("takes a sentence in whatever shape it arrives", async () => {
    const { user, onAsk, onClose } = setup();
    await user.type(
      screen.getByLabelText("What did you spend?"),
      "grabbed lunch at the mamak, twelve fifty",
    );
    await user.click(screen.getByRole("button", { name: "Tell Kira" }));

    expect(onAsk).toHaveBeenCalledWith("grabbed lunch at the mamak, twelve fifty");
    expect(onClose).toHaveBeenCalled();
  });

  it("will not send an empty sentence", async () => {
    const { user, onAsk } = setup();
    await user.click(screen.getByRole("button", { name: "Tell Kira" }));
    expect(onAsk).not.toHaveBeenCalled();
  });

  it("shows the camera when the receipt is the easier answer", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("tab", { name: "Show" }));
    expect(screen.getByRole("button", { name: /Take a photo/ })).toBeInTheDocument();
  });

  it("shows the recorder when saying it is the easier answer", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("tab", { name: "Say" }));
    expect(screen.getByRole("button", { name: /Record/ })).toBeInTheDocument();
  });

  it("says plainly that nothing it records is on the ledger yet", () => {
    setup();
    expect(screen.getByText(/draft/i)).toBeInTheDocument();
  });

  it("keeps the reading route out of the way once the form is chosen", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("tab", { name: "Manual" }));

    expect(screen.queryByRole("tab", { name: "Type" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("What did you spend?")).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Spent", checked: true })).toBeInTheDocument();
  });
});

describe("EntrySheet: the manual form", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 201,
          json: () => Promise.resolve({ id: "t1" }),
          text: () => Promise.resolve(""),
        } as unknown as Response),
      ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function manual(categories?: Category[]) {
    const onAsk = vi.fn();
    const onClose = vi.fn();
    const { user } = setup(onAsk, onClose, categories);
    await user.click(screen.getByRole("tab", { name: "Manual" }));
    return { user, onAsk, onClose };
  }

  async function received(categories?: Category[]) {
    const handles = await manual(categories);
    await handles.user.click(screen.getByRole("radio", { name: "Received" }));
    return handles;
  }

  it("takes either direction from the one form", async () => {
    const { user } = await manual();
    expect(screen.getByLabelText("Where it went")).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Received" }));
    expect(screen.getByLabelText("Where it came from")).toBeInTheDocument();
    expect(screen.queryByLabelText("Where it went")).not.toBeInTheDocument();
  });

  it("records spending as typed, without asking a model to read it", async () => {
    const { user, onAsk, onClose } = await manual(CATEGORIES);
    await user.type(screen.getByLabelText("Where it went"), "Nasi Kandar Pelita");
    await user.selectOptions(screen.getByLabelText("Category"), "food");
    await user.type(screen.getByLabelText("How much"), "19.90");
    await user.clear(screen.getByLabelText("When"));
    await user.type(screen.getByLabelText("When"), "2026-09-03");
    await user.click(screen.getByRole("button", { name: /Add spending/ }));

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(sent().path).toBe("/v1/transactions");
    expect(sent().body).toMatchObject({
      merchant: "Nasi Kandar Pelita",
      amount_sen: 1990,
      occurred_on: "2026-09-03",
      category: "food",
      direction: "expense",
      source: "manual",
    });
    expect(sent().body).not.toHaveProperty("income_type");
    expect(onAsk).not.toHaveBeenCalled();
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("leaves spending uncategorised rather than guessing at one", async () => {
    const { user } = await manual(CATEGORIES);
    await user.type(screen.getByLabelText("Where it went"), "Some shop");
    await user.type(screen.getByLabelText("How much"), "12");
    await user.click(screen.getByRole("button", { name: /Add spending/ }));

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(sent().body).toMatchObject({ category: "uncategorised" });
  });

  it("still records spending when the category list never arrived", async () => {
    const { user } = await manual(undefined);
    expect(screen.queryByLabelText("Category")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Where it went"), "Some shop");
    await user.type(screen.getByLabelText("How much"), "12");
    await user.click(screen.getByRole("button", { name: /Add spending/ }));

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(sent().body).toMatchObject({ merchant: "Some shop", category: "uncategorised" });
  });

  it("will not put a nameless row on the ledger", async () => {
    const { user } = await manual(CATEGORIES);
    await user.type(screen.getByLabelText("How much"), "19.90");

    expect(screen.getByRole("button", { name: /Add spending/ })).toBeDisabled();
    await user.type(screen.getByLabelText("Where it went"), "Pelita");
    expect(screen.getByRole("button", { name: /Add spending/ })).toBeEnabled();
  });

  it("offers more than a salary, because not all money in is pay", async () => {
    await received();
    expect(screen.getByLabelText("Where it came from")).toHaveValue("salary");
    for (const label of [
      "Part-time job",
      "Freelance or side gig",
      "Gift or angpau",
      "Refund or reimbursement",
    ]) {
      expect(screen.getByRole("option", { name: label })).toBeInTheDocument();
    }
  });

  it("records a part-time shift as other income, under the name of the source", async () => {
    const { user, onClose } = await received();
    await user.selectOptions(screen.getByLabelText("Where it came from"), "part-time");
    await user.type(screen.getByLabelText("How much"), "480");
    await user.clear(screen.getByLabelText("When it arrived"));
    await user.type(screen.getByLabelText("When it arrived"), "2026-09-03");
    await user.click(screen.getByRole("button", { name: /Add income/ }));

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(sent().body).toMatchObject({
      merchant: "Part-time job",
      amount_sen: 48_000,
      occurred_on: "2026-09-03",
      direction: "income",
      income_type: "other",
      category: "income",
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("keeps salary as salary, which is what the forecast reads", async () => {
    const { user } = await received();
    await user.type(screen.getByLabelText("How much"), "6500");
    await user.click(screen.getByRole("button", { name: /Add income/ }));

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(sent().body).toMatchObject({
      merchant: "Salary",
      income_type: "salary",
      direction: "income",
    });
  });

  it("takes the payer's own name over the name of the source", async () => {
    const { user } = await received();
    await user.selectOptions(screen.getByLabelText("Where it came from"), "freelance");
    await user.type(screen.getByLabelText("Who paid you (optional)"), "Studio Kalsom");
    await user.type(screen.getByLabelText("How much"), "1200.50");
    await user.click(screen.getByRole("button", { name: /Add income/ }));

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(sent().body).toMatchObject({
      merchant: "Studio Kalsom",
      amount_sen: 120_050,
      income_type: "other",
    });
  });

  it("will not let something else onto the ledger unnamed", async () => {
    const { user } = await received();
    await user.selectOptions(screen.getByLabelText("Where it came from"), "other");
    await user.type(screen.getByLabelText("How much"), "50");

    expect(screen.getByRole("button", { name: /Add income/ })).toBeDisabled();
    await user.type(screen.getByLabelText("What was it?"), "Sold my old bike");
    expect(screen.getByRole("button", { name: /Add income/ })).toBeEnabled();
  });

  it("will not save an amount that is still half-typed", async () => {
    const { user } = await received();
    await user.type(screen.getByLabelText("How much"), "12.");

    expect(screen.getByRole("button", { name: /Add income/ })).toBeDisabled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("says the balance has not moved yet", async () => {
    await received();
    expect(screen.getByText(/only moves once you confirm it/)).toBeInTheDocument();
  });

  it("keeps the figures on screen when the save does not land", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status: 500,
          text: () => Promise.resolve("nope"),
        } as unknown as Response),
      ),
    );
    const { user, onClose } = await received();
    await user.type(screen.getByLabelText("How much"), "480");
    await user.click(screen.getByRole("button", { name: /Add income/ }));

    expect(await screen.findByText(/nothing was added/)).toBeInTheDocument();
    expect(screen.getByLabelText("How much")).toHaveValue("480");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("carries the amount and the day across a change of direction", async () => {
    const { user } = await manual(CATEGORIES);
    await user.type(screen.getByLabelText("How much"), "480");
    await user.clear(screen.getByLabelText("When"));
    await user.type(screen.getByLabelText("When"), "2026-09-02");
    await user.click(screen.getByRole("radio", { name: "Received" }));

    expect(screen.getByLabelText("How much")).toHaveValue("480");
    expect(screen.getByLabelText("When it arrived")).toHaveValue("2026-09-02");
  });
});
