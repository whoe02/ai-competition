import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Activity as ActivityData } from "@kira/contracts";

import { Activity } from "./Activity";

const DATA = {
  drafts: [
    {
      id: "d1",
      merchant: "Grab — office to KLCC",
      amount_sen: 1400,
      category: "transport",
      category_label: "Transport",
      occurred_on: "2026-09-03",
      status: "draft",
      source: "voice",
      confidence: 71,
      note: "Heard 'fourteen ringgit'.",
    },
    {
      id: "d2",
      merchant: "Nasi Kandar Pelita",
      amount_sen: 1890,
      category: "food",
      category_label: "Food & drink",
      occurred_on: "2026-09-03",
      status: "draft",
      source: "receipt",
      confidence: 94,
      note: "Line item total matched.",
    },
  ],
  draft_total_sen: 3290,
  days: [
    {
      date: "2026-09-02",
      total_sen: 2870,
      transactions: [
        {
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
        },
        {
          id: "t2",
          merchant: "Family Mart",
          amount_sen: 1250,
          category: "groceries",
          category_label: "Groceries",
          occurred_on: "2026-09-02",
          status: "confirmed",
          source: "receipt",
          confidence: null,
          note: "",
        },
      ],
    },
  ],
  spent_this_cycle_sen: 42025,
  categories: [
    { slug: "transport", label: "Transport", spent_this_cycle_sen: 1620, count: 1 },
    { slug: "groceries", label: "Groceries", spent_this_cycle_sen: 1250, count: 1 },
    { slug: "food", label: "Food & drink", spent_this_cycle_sen: 890, count: 1 },
  ],
} as ActivityData;

function renderActivity(overrides: Partial<Parameters<typeof Activity>[0]> = {}) {
  const props = {
    data: DATA as ActivityData | undefined,
    isLoading: false,
    isError: false,
    onConfirm: vi.fn(),
    onDiscard: vi.fn(),
    onUnconfirm: vi.fn(),
    onCorrect: vi.fn(),
    settlingId: null,
    correctingId: null,
    category: null,
    onCategory: vi.fn(),
    go: vi.fn(),
    ...overrides,
  };
  return { ...render(<Activity {...props} />), props };
}

function draftCard(merchant: string): HTMLElement {
  return screen.getByText(merchant).closest(".draft") as HTMLElement;
}

describe("Activity", () => {
  it("sends capture to Butler rather than repeating it here", async () => {
    const { props } = renderActivity();
    expect(screen.queryByRole("button", { name: "Receipt" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Voice" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Tell Butler/ }));
    expect(props.go).toHaveBeenCalledWith("butler");
  });

  it("offers a chip for each category present, dearest first", () => {
    renderActivity();
    const chips = screen.getAllByRole("radio").map((chip) => chip.textContent);
    expect(chips?.[0]).toMatch(/All/);
    expect(chips?.[1]).toMatch(/Transport/);
    expect(chips?.[3]).toMatch(/Food & drink/);
  });

  it("asks for the category that was tapped", async () => {
    const { props } = renderActivity();
    await userEvent.click(screen.getByRole("radio", { name: /Food & drink/ }));
    expect(props.onCategory).toHaveBeenCalledWith("food");
  });

  it("clears the filter when All is tapped", async () => {
    const { props } = renderActivity({ category: "food" });
    await userEvent.click(screen.getByRole("radio", { name: /All/ }));
    expect(props.onCategory).toHaveBeenCalledWith(null);
  });

  it("marks the active chip for a screen reader", () => {
    renderActivity({ category: "food" });
    expect(screen.getByRole("radio", { name: /Food & drink/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /All/ })).not.toBeChecked();
  });

  it("names the filter in the cycle heading", () => {
    renderActivity({ category: "food" });
    expect(screen.getByText(/Food & drink this cycle/)).toBeInTheDocument();
  });

  it("says which filter came up empty", () => {
    renderActivity({ category: "food", data: { ...DATA, days: [], spent_this_cycle_sen: 0 } });
    expect(screen.getByText(/Nothing under Food & drink this cycle/)).toBeInTheDocument();
  });

  it("counts the drafts waiting for a decision", () => {
    renderActivity();
    expect(screen.getByText(/Waiting for you · 2/)).toBeInTheDocument();
  });

  it("shows a draft with the confidence it was read with", () => {
    renderActivity();
    expect(screen.getByText("Nasi Kandar Pelita")).toBeInTheDocument();
    expect(within(draftCard("Nasi Kandar Pelita")).getByText("Food & drink")).toBeInTheDocument();
    expect(screen.getByText(/94% sure/)).toBeInTheDocument();
  });

  it("confirms the draft that was tapped", async () => {
    const { props } = renderActivity();
    await userEvent.click(
      within(draftCard("Nasi Kandar Pelita")).getByRole("button", { name: "Confirm" }),
    );
    expect(props.onConfirm).toHaveBeenCalledWith("d2");
  });

  it("discards the draft that was tapped", async () => {
    const { props } = renderActivity();
    await userEvent.click(
      within(draftCard("Nasi Kandar Pelita")).getByRole("button", { name: "Discard" }),
    );
    expect(props.onDiscard).toHaveBeenCalledWith("d2");
  });

  it("lists confirmed spending under the day it happened", () => {
    renderActivity();
    expect(screen.getByText("Wednesday, 2 September")).toBeInTheDocument();
    expect(screen.getByText("Family Mart")).toBeInTheDocument();
    expect(screen.getByText("Groceries · Receipt")).toBeInTheDocument();
  });

  it("totals each day and the cycle so far", () => {
    renderActivity();
    expect(screen.getByText("RM28.70")).toBeInTheDocument();
    expect(screen.getByText("RM420.25")).toBeInTheDocument();
  });

  it("says nothing is waiting when no drafts remain", () => {
    renderActivity({ data: { ...DATA, drafts: [], draft_total_sen: 0 } });
    expect(screen.getByText(/Nothing waiting/)).toBeInTheDocument();
  });

  it("invites a first entry when the ledger is empty", () => {
    renderActivity({
      data: { ...DATA, drafts: [], draft_total_sen: 0, days: [], spent_this_cycle_sen: 0 },
    });
    expect(screen.getByText(/Nothing on your ledger yet/)).toBeInTheDocument();
  });

  it("waits rather than guessing while the ledger loads", () => {
    renderActivity({ data: undefined, isLoading: true });
    expect(screen.getByText(/Fetching your ledger/)).toBeInTheDocument();
  });

  it("admits when it cannot reach the ledger", () => {
    renderActivity({ data: undefined, isLoading: false, isError: true });
    expect(screen.getByText(/couldn't reach your ledger/i)).toBeInTheDocument();
  });

  it("opens a detail sheet for the confirmed row that was tapped", async () => {
    renderActivity();
    await userEvent.click(screen.getByRole("button", { name: /Family Mart/ }));
    const sheet = screen.getByRole("dialog", { name: "Family Mart" });
    expect(within(sheet).getByText("RM12.50")).toBeInTheDocument();
    expect(within(sheet).getByText("Groceries")).toBeInTheDocument();
    expect(within(sheet).getByText("Wednesday, 2 September")).toBeInTheDocument();
    expect(within(sheet).getByText("Receipt")).toBeInTheDocument();
  });

  it("takes a transaction back off the ledger from its sheet", async () => {
    const { props } = renderActivity();
    await userEvent.click(screen.getByRole("button", { name: /Family Mart/ }));
    await userEvent.click(screen.getByRole("button", { name: /Move back to drafts/ }));
    expect(props.onUnconfirm).toHaveBeenCalledWith("t2");
  });

  it("closes the sheet once the row it showed is no longer on the ledger", async () => {
    const { rerender, props } = renderActivity();
    await userEvent.click(screen.getByRole("button", { name: /Family Mart/ }));
    expect(screen.getByRole("dialog", { name: "Family Mart" })).toBeInTheDocument();

    const [day] = DATA.days;
    const [firstTxn] = day!.transactions;
    rerender(
      <Activity
        {...props}
        data={{ ...DATA, days: [{ ...day!, transactions: [firstTxn!], total_sen: 1620 }] }}
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("leaves drafts to their own inline details", async () => {
    renderActivity();
    await userEvent.click(
      within(draftCard("Nasi Kandar Pelita")).getByRole("button", { name: "Details" }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("offers to correct the amount in the draft's details", async () => {
    renderActivity();
    const card = draftCard("Grab — office to KLCC");
    expect(within(card).queryByLabelText("Amount in ringgit")).not.toBeInTheDocument();

    await userEvent.click(within(card).getByRole("button", { name: "Details" }));
    await userEvent.click(within(card).getByRole("button", { name: "Correct" }));

    // Seeded with the figure that was read, in plain ringgit for typing over.
    expect(within(card).getByLabelText("Amount in ringgit")).toHaveValue("14.00");
  });

  it("corrects the misheard amount in sen, not ringgit", async () => {
    const { props } = renderActivity();
    const card = draftCard("Grab — office to KLCC");
    await userEvent.click(within(card).getByRole("button", { name: "Details" }));
    await userEvent.click(within(card).getByRole("button", { name: "Correct" }));

    const field = within(card).getByLabelText("Amount in ringgit");
    await userEvent.clear(field);
    await userEvent.type(field, "19.90");
    await userEvent.click(within(card).getByRole("button", { name: "Save" }));

    expect(props.onCorrect).toHaveBeenCalledWith("d1", 1990);
  });

  it("will not submit a half-typed amount", async () => {
    const { props } = renderActivity();
    const card = draftCard("Grab — office to KLCC");
    await userEvent.click(within(card).getByRole("button", { name: "Details" }));
    await userEvent.click(within(card).getByRole("button", { name: "Correct" }));

    const field = within(card).getByLabelText("Amount in ringgit");
    await userEvent.clear(field);
    await userEvent.type(field, "19.");

    const save = within(card).getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    await userEvent.click(save);
    expect(props.onCorrect).not.toHaveBeenCalled();
    // And the entry stays open on what was typed, rather than closing on a guess.
    expect(within(card).getByLabelText("Amount in ringgit")).toHaveValue("19.");
  });

  it("will not submit nothing, or less than nothing", async () => {
    const { props } = renderActivity();
    const card = draftCard("Grab — office to KLCC");
    await userEvent.click(within(card).getByRole("button", { name: "Details" }));
    await userEvent.click(within(card).getByRole("button", { name: "Correct" }));
    const field = within(card).getByLabelText("Amount in ringgit");

    await userEvent.clear(field);
    expect(within(card).getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(field, "0");
    expect(within(card).getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.clear(field);
    await userEvent.type(field, "-5");
    expect(within(card).getByRole("button", { name: "Save" })).toBeDisabled();
    expect(props.onCorrect).not.toHaveBeenCalled();
  });

  it("leaves the read alone when the correction is cancelled", async () => {
    const { props } = renderActivity();
    const card = draftCard("Grab — office to KLCC");
    await userEvent.click(within(card).getByRole("button", { name: "Details" }));
    await userEvent.click(within(card).getByRole("button", { name: "Correct" }));
    await userEvent.type(within(card).getByLabelText("Amount in ringgit"), "9");
    await userEvent.click(within(card).getByRole("button", { name: "Cancel" }));

    expect(props.onCorrect).not.toHaveBeenCalled();
    expect(within(card).queryByLabelText("Amount in ringgit")).not.toBeInTheDocument();
    // Once in the card's head, once in the details row it was cancelled from.
    expect(within(card).getAllByText("RM14.00")).toHaveLength(2);
  });

  it("keeps the entry open and says so when the correction does not save", async () => {
    // The whole point of the path: the user has just told Kira the reader was
    // wrong. Closing on the tap would put RM14.00 back on a card they believe
    // says RM19.90, and the next Confirm would spend the misheard figure.
    const onCorrect = vi.fn().mockRejectedValue(new Error("network down"));
    renderActivity({ onCorrect });
    const card = draftCard("Grab — office to KLCC");
    await userEvent.click(within(card).getByRole("button", { name: "Details" }));
    await userEvent.click(within(card).getByRole("button", { name: "Correct" }));
    const field = within(card).getByLabelText("Amount in ringgit");
    await userEvent.clear(field);
    await userEvent.type(field, "19.90");
    await userEvent.click(within(card).getByRole("button", { name: "Save" }));

    expect(onCorrect).toHaveBeenCalledWith("d1", 1990);
    // Said, not swallowed — and it names the figure the draft still carries
    // rather than only that a request failed.
    expect(await within(card).findByText(/didn't save, so this draft still says RM14\.00/))
      .toBeInTheDocument();
    // The typed figure is still there to retry, not thrown away.
    expect(within(card).getByLabelText("Amount in ringgit")).toHaveValue("19.90");
    expect(within(card).getByRole("button", { name: "Try again" })).toBeEnabled();
  });

  it("clears a failed correction when the entry is cancelled and reopened", async () => {
    const onCorrect = vi.fn().mockRejectedValue(new Error("network down"));
    renderActivity({ onCorrect });
    const card = draftCard("Grab — office to KLCC");
    await userEvent.click(within(card).getByRole("button", { name: "Details" }));
    await userEvent.click(within(card).getByRole("button", { name: "Correct" }));
    await userEvent.click(within(card).getByRole("button", { name: "Save" }));
    await within(card).findByText(/didn't save/);

    await userEvent.click(within(card).getByRole("button", { name: "Cancel" }));
    await userEvent.click(within(card).getByRole("button", { name: "Correct" }));

    // A complaint about the last attempt must not greet the next one.
    expect(within(card).queryByText(/didn't save/)).not.toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Save" })).toBeInTheDocument();
  });

  it("stops claiming a corrected amount was read with any confidence", () => {
    const [voice, ...rest] = DATA.drafts;
    renderActivity({
      data: { ...DATA, drafts: [{ ...voice!, amount_sen: 1990, confidence: null }, ...rest] },
    });
    const card = draftCard("Grab — office to KLCC");
    expect(within(card).queryByText(/% sure/)).not.toBeInTheDocument();
    expect(within(card).getByText(/Your figure, not a read/)).toBeInTheDocument();
  });

  it("holds the draft still while its correction is in flight", () => {
    renderActivity({ correctingId: "d1" });
    const card = draftCard("Grab — office to KLCC");
    expect(within(card).getByRole("button", { name: "Confirm" })).toBeDisabled();
    expect(within(card).getByRole("button", { name: "Discard" })).toBeDisabled();
  });

  it("disables both choices on the draft being settled", () => {
    renderActivity({ settlingId: "d2" });
    const card = draftCard("Nasi Kandar Pelita");
    expect(within(card).getByRole("button", { name: "Confirm" })).toBeDisabled();
    expect(within(card).getByRole("button", { name: "Discard" })).toBeDisabled();
    expect(
      within(draftCard("Grab — office to KLCC")).getByRole("button", { name: "Confirm" }),
    ).toBeEnabled();
  });
});

/** A draft the day planner made. Nothing was built here to receive it — drafts
 *  already surface in Activity — so these check that it arrives readable. */
const PLAN: ActivityData["drafts"][number] = {
  id: "d3",
  merchant: "Kopi Kaki",
  amount_sen: 1750,
  category: "food",
  category_label: "Food & drink",
  occurred_on: "2026-09-03",
  status: "draft",
  source: "plan",
  confidence: 70,
  note: "Planned, not spent — this is an estimate from your day plan. "
    + "Nothing counts against today until you confirm it.",
  direction: "expense",
  goal_allocation_applied: false,
};

function withPlan(overrides: Partial<typeof PLAN> = {}) {
  return {
    data: { ...DATA, drafts: [{ ...PLAN, ...overrides }, ...DATA.drafts], draft_total_sen: 5040 },
  };
}

describe("Activity · a draft the day planner made", () => {
  it("arrives among the waiting drafts, with nothing new built to hold it", () => {
    renderActivity(withPlan());
    expect(screen.getByText(/Waiting for you · 3 · RM50.40/)).toBeInTheDocument();
    const card = draftCard("Kopi Kaki");
    expect(within(card).getByText("RM17.50")).toBeInTheDocument();
    expect(within(card).getByText("Food & drink")).toBeInTheDocument();
  });

  it("names the source as a plan rather than the unknown-source fallback", () => {
    // The label map's fallback is "Imported": a place the user picked on the
    // planner two minutes ago, described as an import from their bank.
    renderActivity(withPlan());
    const card = draftCard("Kopi Kaki");
    expect(within(card).getByText("Plan")).toBeInTheDocument();
    expect(within(card).queryByText("Imported")).not.toBeInTheDocument();
  });

  it("is sure of a price rather than sure of a read", () => {
    // A scan is sure of what a slip said. Nothing read this at all.
    renderActivity(withPlan());
    expect(within(draftCard("Kopi Kaki")).getByText(/70% sure of the price/)).toBeInTheDocument();
    // The other drafts were read, and still say so.
    expect(within(draftCard("Nasi Kandar Pelita")).getByText(/94% sure\./)).toBeInTheDocument();
  });

  it("says on the row itself that nothing has been counted", () => {
    // The toast that announced it is long gone by the time Activity is opened,
    // so the row has to carry the invariant on its own.
    renderActivity(withPlan());
    const card = draftCard("Kopi Kaki");
    expect(
      within(card).getByText(/Nothing counts against today until you confirm it/),
    ).toBeInTheDocument();
    expect(within(card).queryByText(/pencilled/i)).not.toBeInTheDocument();
  });

  it("can be confirmed, discarded and corrected like any other draft", async () => {
    const { props } = renderActivity(withPlan());
    const card = draftCard("Kopi Kaki");

    await userEvent.click(within(card).getByRole("button", { name: "Details" }));
    await userEvent.click(within(card).getByRole("button", { name: "Correct" }));
    const field = within(card).getByLabelText("Amount in ringgit");
    await userEvent.clear(field);
    // The bill came to more than the estimate, which is the ordinary case.
    await userEvent.type(field, "20.10");
    await userEvent.click(within(card).getByRole("button", { name: "Save" }));
    expect(props.onCorrect).toHaveBeenCalledWith("d3", 2010);

    await userEvent.click(within(card).getByRole("button", { name: "Confirm" }));
    expect(props.onConfirm).toHaveBeenCalledWith("d3");
  });
});
