import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EntrySheet } from "./EntrySheet";

function setup(onAsk = vi.fn(), onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <EntrySheet onClose={onClose} onAsk={onAsk} />
    </QueryClientProvider>,
  );
  return { user: userEvent.setup(), onAsk, onClose };
}

describe("EntrySheet", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, status: 200 } as Response)));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
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
});
