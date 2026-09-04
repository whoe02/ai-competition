import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Memory, UserResponse } from "@kira/contracts";

import { More } from "./More";

const MEMORIES: Memory[] = [
  {
    id: "m1",
    kind: "constraint",
    subject: "standing rule",
    fact: "Never suggest cutting the wedding goal.",
    confidence: 90,
    source_message_id: null,
    created_at: "2026-09-01T04:00:00Z",
    last_used_at: null,
  },
  {
    id: "m2",
    kind: "person",
    subject: "housemate",
    fact: "Splits rent with a housemate.",
    confidence: 75,
    source_message_id: null,
    created_at: "2026-09-02T04:00:00Z",
    last_used_at: null,
  },
];

const PROFILE: UserResponse = {
  id: "u1",
  email: "aina@example.com",
  display_name: "Aina Rahman",
  currency: "MYR",
  buffer_sen: 30_000,
  next_payday: "2026-09-25",
  cycle_start: "2026-08-25",
  cycle_days: 31,
  monthly_income_sen: 650_000,
};

function setup(memories: Memory[] | undefined = MEMORIES, profile?: UserResponse) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <More memories={memories} isLoading={false} profile={profile} />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

/** The memory list lives under Settings now, which is a disclosure, not a page. */
async function withSettingsOpen(memories?: Memory[]) {
  const user = setup(memories);
  await user.click(screen.getByRole("button", { name: /Settings/ }));
  return user;
}

describe("More", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ ...MEMORIES[0], fact: "Never cut the wedding goal." }),
          text: () => Promise.resolve(""),
        } as unknown as Response),
      ),
    );
  });

  afterEach(() => vi.unstubAllGlobals());

  it("offers the choice before any of the settings themselves", () => {
    setup();
    expect(screen.getByRole("button", { name: /My profile/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Settings/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByText("Never suggest cutting the wedding goal.")).not.toBeInTheDocument();
  });

  it("lists every fact with what kind it is, once the settings are open", async () => {
    await withSettingsOpen();
    expect(screen.getByText("Never suggest cutting the wedding goal.")).toBeInTheDocument();
    expect(screen.getByText("constraint")).toBeInTheDocument();
    expect(screen.getByText(/someone in your money/)).toBeInTheDocument();
  });

  it("closes the settings again without leaving the menu", async () => {
    const user = await withSettingsOpen();
    await user.click(screen.getByRole("button", { name: /Settings/ }));

    expect(screen.queryByText("Never suggest cutting the wedding goal.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /My profile/ })).toBeInTheDocument();
  });

  it("says how sure it is, so a shaky fact reads as shaky", async () => {
    await withSettingsOpen();
    expect(screen.getByText("75% sure")).toBeInTheDocument();
  });

  it("says so plainly when it has learned nothing", async () => {
    await withSettingsOpen([]);
    expect(screen.getByText(/Nothing yet/)).toBeInTheDocument();
  });

  it("corrects a fact in place", async () => {
    const user = await withSettingsOpen();
    await user.click(screen.getAllByRole("button", { name: "Correct" })[0]!);

    const field = screen.getByLabelText("Correct this memory");
    await user.clear(field);
    await user.type(field, "Never cut the wedding goal.");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/v1/butler/memories/m1",
        expect.objectContaining({ method: "PATCH" }),
      ),
    );
  });

  it("abandons a correction without sending it", async () => {
    const user = await withSettingsOpen();
    await user.click(screen.getAllByRole("button", { name: "Correct" })[0]!);
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByLabelText("Correct this memory")).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("forgets a fact", async () => {
    const user = await withSettingsOpen();
    await user.click(
      screen.getByRole("button", { name: "Forget: Splits rent with a housemate." }),
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/v1/butler/memories/m2",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
  });
});

describe("My profile", () => {
  it("shows who you are and the dates the forecasts are measured from", async () => {
    const user = setup(MEMORIES, PROFILE);
    await user.click(screen.getByRole("button", { name: /My profile/ }));

    expect(screen.getByRole("heading", { name: "Aina Rahman" })).toBeInTheDocument();
    expect(screen.getByText("aina@example.com")).toBeInTheDocument();
    expect(screen.getByText("25 September 2026")).toBeInTheDocument();
    expect(screen.getByText("RM6,500.00")).toBeInTheDocument();
    expect(screen.getByText(/31 days long/)).toBeInTheDocument();
  });

  it("says the recurring income is a forecast, not money in hand", async () => {
    const user = setup(MEMORIES, PROFILE);
    await user.click(screen.getByRole("button", { name: /My profile/ }));

    expect(screen.getByText("forecast, not cash")).toBeInTheDocument();
  });

  it("goes back to the menu it was opened from", async () => {
    const user = setup(MEMORIES, PROFILE);
    await user.click(screen.getByRole("button", { name: /My profile/ }));
    await user.click(screen.getByRole("button", { name: "Back to More" }));

    expect(screen.getByRole("button", { name: /Settings/ })).toBeInTheDocument();
  });

  it("holds the page together while the profile is still being read", async () => {
    const user = setup(MEMORIES, undefined);
    await user.click(screen.getByRole("button", { name: /My profile/ }));

    expect(screen.getByRole("heading", { name: "You" })).toBeInTheDocument();
    // Every date it does not have yet says so, rather than showing a wrong one.
    expect(screen.getAllByText("not set")).toHaveLength(2);
  });
});
