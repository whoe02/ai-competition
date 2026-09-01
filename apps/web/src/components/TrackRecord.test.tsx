import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it } from "vitest";

import type { HindsightResponse } from "@kira/contracts";

import { TrackRecord } from "./TrackRecord";

afterEach(cleanup);

const RECORD: HindsightResponse = {
  window_days: 90,
  days: 90,
  followed: 82,
  follow_rate_bp: 9111,
  mean_abs_deviation: { sen: 5393, currency: "MYR" },
  counterfactual_gain: { sen: 57953, currency: "MYR" },
  goal_id: "g1",
  probability_bp_now: 4240,
  probability_bp_if_followed: 6120,
  recent: [
    { on: "2026-09-01", advised: { sen: 5196, currency: "MYR" }, actual: { sen: 7350, currency: "MYR" }, followed: false },
    { on: "2026-09-02", advised: { sen: 5182, currency: "MYR" }, actual: { sen: 2870, currency: "MYR" }, followed: true },
  ],
  assumption: "Scored against your confirmed spending on each of those days.",
};

it("leads with the count a person can check, not the percentage alone", () => {
  render(<TrackRecord data={RECORD} />);
  expect(screen.getByText(/82 of 90 days/)).toBeTruthy();
  expect(screen.getByText("91%")).toBeTruthy();
});

it("keeps the detail one tap away", async () => {
  render(<TrackRecord data={RECORD} />);
  expect(screen.queryByText(/Had you followed it every day/)).toBeNull();

  await userEvent.click(screen.getByRole("button", { name: "My track record" }));

  expect(screen.getByText(/Had you followed it every day/)).toBeTruthy();
  expect(screen.getByText("RM579.53 ahead")).toBeTruthy();
  expect(screen.getByText("19 points higher")).toBeTruthy();
  expect(screen.getByText(RECORD.assumption)).toBeTruthy();
});

it("shows nothing at all before there is a record", () => {
  const { container } = render(<TrackRecord data={{ ...RECORD, days: 0, followed: 0 }} />);
  expect(container.firstChild).toBeNull();
});

it("shows nothing while the record is still loading", () => {
  const { container } = render(<TrackRecord data={undefined} />);
  expect(container.firstChild).toBeNull();
});
