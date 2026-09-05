import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DayPlan as DayPlanData,
  DayPlanReading,
  Place,
  Transaction,
} from "@kira/contracts";

import { api } from "../api/client";
import { takeButlerHandoff } from "../lib/butlerHandoff";
import { DayPlan } from "./DayPlan";

vi.mock("../api/client", () => ({
  api: { get: vi.fn(), post: vi.fn() },
}));

const ROOM_SEN = 5297;

/** Routed places, stated the way the API states them: ``km`` is the road
 *  figure, ``road_km`` repeats it, and the basis says so. A fixture missing any
 *  of the three is a response the API cannot send, and the branches that read
 *  them would go untested behind it. */
const PELITA: Place = {
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
  halal: true,
  note: "Fast counter service, open late.",
  match_basis: null,
  match_strength: null,
  match_reason: "",
};

const CHEE_MENG: Place = {
  id: "p2",
  name: "Chee Meng Chicken Rice",
  kind: "Chinese",
  // A locality rather than a doorstep, which is what a quarter of the shipped
  // set actually reads like. Rendered as it stands, not dressed up.
  address: "Ampang, Kuala Lumpur",
  lat: 3.1503,
  lng: 101.7261,
  km: 1.8,
  road_km: 1.8,
  distance_basis: "road",
  travel_sen: 500,
  minutes: 22,
  total_sen: 4800,
  share: 0.92,
  band: "tight",
  confidence: "medium",
  halal: false,
  note: "Small shop, queue moves quickly.",
  match_basis: null,
  match_strength: null,
  match_reason: "",
};

const SKY_BAR: Place = {
  id: "p3",
  name: "Sky Bar Steakhouse",
  kind: "Fine dining",
  address: "Level 33, Jalan Pinang, 50450 Kuala Lumpur",
  lat: 3.1552,
  lng: 101.7118,
  km: 3.2,
  road_km: 3.2,
  distance_basis: "road",
  travel_sen: 900,
  minutes: 35,
  total_sen: 9800,
  share: 1.9,
  band: "over",
  confidence: "low",
  halal: true,
  note: "Way past today's room.",
  match_basis: null,
  match_strength: null,
  match_reason: "",
};

const PLACES: Place[] = [PELITA, CHEE_MENG, SKY_BAR];

/**
 * The list as it actually read once road distances arrived, with the tension
 * that put a two-hour walk at the top of it: the cheapest outing is 109 minutes
 * on foot, the nearest is RM7 dearer, and the one a person would pick is
 * neither of them.
 */
const KENNY_HILLS: Place = {
  id: "t1",
  name: "Kenny Hills Bakers",
  kind: "Bakery",
  address: "Jalan Kasah, Bukit Tunku, 50480 Kuala Lumpur",
  lat: 3.1633,
  lng: 101.6737,
  km: 7.9,
  road_km: 7.9,
  distance_basis: "road",
  travel_sen: 0,
  minutes: 109,
  total_sen: 1100,
  share: 1100 / ROOM_SEN,
  band: "ok",
  confidence: "medium",
  halal: false,
  note: "",
  match_basis: null,
  match_strength: null,
  match_reason: "",
};

const GERAI: Place = {
  id: "t2",
  name: "Gerai Nasi Lemak",
  kind: "Malay",
  address: "Jalan P Ramlee, 50250 Kuala Lumpur",
  lat: 3.1566,
  lng: 101.7108,
  km: 0.15,
  road_km: 0.15,
  distance_basis: "road",
  travel_sen: 0,
  minutes: 8,
  total_sen: 1800,
  share: 1800 / ROOM_SEN,
  band: "ok",
  confidence: "high",
  halal: true,
  note: "",
  match_basis: null,
  match_strength: null,
  match_reason: "",
};

const ABC_BISTRO: Place = {
  id: "t3",
  name: "ABC Bistro Cafe",
  kind: "Indian",
  address: "Jalan Ampang, 50450 Kuala Lumpur",
  lat: 3.1595,
  lng: 101.7185,
  km: 1.5,
  road_km: 1.5,
  distance_basis: "road",
  travel_sen: 0,
  minutes: 25,
  total_sen: 1300,
  share: 1300 / ROOM_SEN,
  band: "ok",
  confidence: "high",
  halal: true,
  note: "",
  match_basis: null,
  match_strength: null,
  match_reason: "",
};

const TENSION: DayPlanData = {
  room_sen: ROOM_SEN,
  cap_sen: ROOM_SEN,
  kind: null,
  nearby_count: 3,
  matching_count: 3,
  kind_count: 3,
  ranking: "deterministic",
  places: [KENNY_HILLS, GERAI, ABC_BISTRO],
  nearest_over_cap: [],
  nearest_beyond_radius: [],
};

/** The same place with the router silent: ``km`` is the great circle, there is
 *  no road figure to show beside it, and the fare below is priced on the short
 *  one. The real journey behind these numbers is 8.1 km of road. */
function fellBack(place: Place, straightLineKm: number): Place {
  return { ...place, km: straightLineKm, road_km: null, distance_basis: "straight_line" };
}

const RESPONSE: DayPlanData = {
  room_sen: ROOM_SEN,
  cap_sen: ROOM_SEN,
  kind: null,
  nearby_count: PLACES.length,
  matching_count: PLACES.length,
  kind_count: PLACES.length,
  ranking: "deterministic",
  places: PLACES,
  nearest_over_cap: [],
  nearest_beyond_radius: [],
};

/** What POST /v1/day-plan/drafts answers with: the draft the server made, with
 *  the date, the percentage and the note all decided there rather than here. */
const PLAN_DRAFT: Transaction = {
  id: "d9",
  merchant: "Nasi Kandar Pelita",
  amount_sen: 1250,
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

/**
 * What POST /v1/day-plan/interpret answers with, defaulting to a sentence read
 * whole. ``filters`` is the entire control state or it is null — a response
 * carrying some of the controls is one the API cannot send, and a screen built
 * against one would be applying half a request.
 */
function reading(over: Partial<DayPlanReading> = {}): DayPlanReading {
  return {
    applied: true,
    filters: {
      lat: 3.1577,
      lng: 101.712,
      mode: "ride",
      halal_only: false,
      cap_sen: 1500,
      kind: null,
      sort: "closest",
    },
    understood: "I read that as halal off, under RM15.00, by Grab, closest first.",
    unread: "",
    reason: "",
    ...over,
  };
}

/** A spent-out day, stated the way the API states it — including the counts,
 *  which a fixture that leaves them out would quietly stop exercising. */
const NOTHING_LEFT: DayPlanData = {
  room_sen: 0,
  cap_sen: 0,
  kind: null,
  nearby_count: PLACES.length,
  matching_count: PLACES.length,
  kind_count: PLACES.length,
  ranking: "deterministic",
  places: [],
  nearest_over_cap: [],
  nearest_beyond_radius: [],
};

function renderDayPlan() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DayPlan />
    </QueryClientProvider>,
  );
}

function lastRequestedUrl(): string {
  const calls = vi.mocked(api.get).mock.calls;
  return String(calls[calls.length - 1]?.[0]);
}

/** jsdom ships no geolocation at all, so every case installs the one it needs. */
function stubGeolocation(getCurrentPosition: Geolocation["getCurrentPosition"]) {
  Object.defineProperty(navigator, "geolocation", {
    configurable: true,
    value: { getCurrentPosition },
  });
  return getCurrentPosition;
}

function failingGeolocation(code: number) {
  return stubGeolocation(
    vi.fn((_success, error) => {
      error?.({ code, message: "", PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 });
    }),
  );
}

function geolocationAt(lat: number, lng: number) {
  return stubGeolocation(
    vi.fn((success) => {
      success({ coords: { latitude: lat, longitude: lng } } as GeolocationPosition);
    }),
  );
}

/** A locate that answers only when the test says so — the seconds a cold fix
 *  really takes, held open, so what is on screen during them can be looked at. */
function deferredGeolocationAt(lat: number, lng: number) {
  let answer = () => {};
  const getCurrentPosition = stubGeolocation(
    vi.fn((success) => {
      answer = () => success({ coords: { latitude: lat, longitude: lng } } as GeolocationPosition);
    }),
  );
  return { getCurrentPosition, land: () => act(() => answer()) };
}

/** jsdom ships no clipboard, and userEvent.setup() installs a working stub of
 *  its own — so both of these have to run *after* the setup inside openSheet,
 *  or that stub silently puts a functioning clipboard back under the test. */
function stubClipboard(writeText: (text: string) => Promise<void>) {
  const spy = vi.fn(writeText);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: spy } });
  return spy;
}

function removeClipboard() {
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
}

/** The place names down the list, in the order the rows are actually in. */
function orderedNames(): string[] {
  return Array.from(document.querySelectorAll<HTMLElement>(".place")).map(
    (row) => row.querySelector("b")?.textContent ?? "",
  );
}

/**
 * Every figure on each row, keyed by place. The rank and the badge are stripped
 * out because those *are* the ordering; what is left is the ringgit, the
 * distance, the minutes and the share, none of which a sort may touch.
 */
function figuresByPlace(): Record<string, string> {
  const rows: Record<string, string> = {};
  for (const row of document.querySelectorAll<HTMLElement>(".place")) {
    const name = row.querySelector("b")?.textContent ?? "";
    rows[name] = (row.textContent ?? "").replace(/^\d+/, "").replace("Best fit", "");
  }
  return rows;
}

async function openSheet(name: string) {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: new RegExp(name) }));
  return { user, sheet: screen.getByRole("dialog", { name }) };
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.get).mockResolvedValue(RESPONSE);
  vi.mocked(api.post).mockReset();
  vi.mocked(api.post).mockResolvedValue(PLAN_DRAFT);
  Reflect.deleteProperty(navigator, "geolocation");
  Reflect.deleteProperty(navigator, "clipboard");
});

describe("DayPlan", () => {
  it("lists ranked places with their cost and band", async () => {
    renderDayPlan();

    expect(await screen.findByText("Nasi Kandar Pelita")).toBeInTheDocument();
    expect(screen.getByText("RM12.50")).toBeInTheDocument();
    expect(screen.getByText("Chee Meng Chicken Rice")).toBeInTheDocument();
    expect(screen.getByText("RM48.00")).toBeInTheDocument();
    expect(screen.getByText("Sky Bar Steakhouse")).toBeInTheDocument();
    expect(screen.getByText("RM98.00")).toBeInTheDocument();
    expect(screen.getByText("Best fit")).toBeInTheDocument();
    expect(screen.getByText("Over")).toBeInTheDocument();
  });

  it("requests from KLCC on foot with halal on, by default", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const url = lastRequestedUrl();
    expect(url).toContain("lat=3.1577");
    expect(url).toContain("lng=101.712");
    expect(url).toContain("mode=walk");
    expect(url).toContain("halal_only=true");
    expect(url).not.toContain("cap_sen");
  });

  it("shows an empty state when nothing fits", async () => {
    vi.mocked(api.get).mockResolvedValue({ ...RESPONSE, places: [] });
    renderDayPlan();

    expect(await screen.findByText(/Nothing under RM52.97 yet/i)).toBeInTheDocument();
  });

  it("states the ceiling is nil at the ceiling, not distance", async () => {
    vi.mocked(api.get).mockResolvedValue({ ...RESPONSE, nearby_count: 3, matching_count: 3, places: [] });
    renderDayPlan();

    expect(await screen.findByText(/Nothing under RM52.97 yet/i)).toBeInTheDocument();
    expect(screen.getByText(/Raise the ceiling/i)).toBeInTheDocument();
    expect(screen.queryByText(/Nothing within range/i)).not.toBeInTheDocument();
  });

  it("blames distance rather than the ceiling when nothing was in range", async () => {
    // Raising the ceiling here could never surface a place, so the copy that
    // tells the user to raise it would send them round a loop with no exit.
    vi.mocked(api.get).mockResolvedValue({ ...RESPONSE, nearby_count: 0, matching_count: 0, places: [] });
    renderDayPlan();

    expect(await screen.findByText(/Nothing within range of here/i)).toBeInTheDocument();
    expect(screen.queryByText(/Raise the ceiling/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Nothing under RM52.97 yet/i)).not.toBeInTheDocument();
  });

  it("names the mode's own reach on foot, and the data only once nothing wider is left", async () => {
    // How far "within range" goes is decided by the mode: the server searches
    // as far as the user would travel in the time, so a Walk that found nothing
    // and a Grab that found nothing are two different sentences. Blaming the
    // demo set under a Walk would explain an empty list with the wrong thing --
    // and send the user past the one control that would have filled it.
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue({ ...RESPONSE, nearby_count: 0, matching_count: 0, places: [] });
    renderDayPlan();

    expect(await screen.findByText(/A Walk search only reaches as far as/i)).toBeInTheDocument();
    expect(screen.getByText(/Grab reaches further/i)).toBeInTheDocument();
    expect(screen.queryByText(/demo set only covers central KL/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Grab" }));

    expect(await screen.findByText(/demo set only covers central KL/i)).toBeInTheDocument();
    expect(screen.queryByText(/only reaches as far as/i)).not.toBeInTheDocument();
  });

  it("blames the halal filter rather than the ceiling when it is what emptied the list", async () => {
    // One place is in range and the ceiling is RM52.97 against a RM22 outing.
    // Telling the user to raise the ceiling here aims them at a slider that
    // cannot reach the thing that is actually in the way.
    vi.mocked(api.get).mockResolvedValue({
      ...RESPONSE,
      nearby_count: 1,
      matching_count: 0,
      places: [],
    });
    renderDayPlan();

    expect(
      await screen.findByText(/The one place within range of here is not halal/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Raising the ceiling will not change that/i)).toBeInTheDocument();
    expect(screen.queryByText(/Nothing under RM52.97 yet/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Raise the ceiling/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Nothing within range of here/i)).not.toBeInTheDocument();
  });

  it("counts the places the halal filter took out, rather than saying 'some'", async () => {
    vi.mocked(api.get).mockResolvedValue({
      ...RESPONSE,
      nearby_count: 4,
      matching_count: 0,
      places: [],
    });
    renderDayPlan();

    expect(
      await screen.findByText(/None of the 4 places within range of here are halal/i),
    ).toBeInTheDocument();
  });

  it("offers the halal toggle as the way out, and re-asks with it off", async () => {
    vi.mocked(api.get).mockResolvedValue({
      ...RESPONSE,
      nearby_count: 1,
      matching_count: 0,
      places: [],
    });
    renderDayPlan();
    await screen.findByText(/is not halal/i);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Turn Halal off" }));

    await waitFor(() => expect(lastRequestedUrl()).toContain("halal_only=false"));
  });

  it("blames the kind of food rather than the ceiling when that is what emptied it", async () => {
    // There is food in range and the ceiling is RM52.97: neither is the cause.
    // A client told only "3 within range" would send the user at a slider that
    // cannot reach a kind of food this part of town does not have.
    vi.mocked(api.get).mockResolvedValue({
      ...RESPONSE,
      kind: "Noodles",
      nearby_count: 3,
      matching_count: 3,
      kind_count: 0,
      places: [],
    });
    renderDayPlan();

    expect(
      await screen.findByText(/None of the 3 places within range of here are noodles/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Raising the ceiling will not change that/i)).toBeInTheDocument();
    expect(screen.queryByText(/Nothing under RM52.97 yet/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/not halal/i)).not.toBeInTheDocument();
  });

  it("offers dropping the kind as the way out, and re-asks without it", async () => {
    vi.mocked(api.get).mockResolvedValue({
      ...RESPONSE,
      kind: "Noodles",
      nearby_count: 3,
      matching_count: 3,
      kind_count: 0,
      places: [],
    });
    renderDayPlan();
    await screen.findByText(/are noodles/i);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Show every kind" }));

    await waitFor(() => expect(lastRequestedUrl()).not.toContain("kind="));
  });

  it("names the kind when it is the ceiling that emptied the list", async () => {
    // "Nothing under RM52.97 yet" is false where the cheap places are simply
    // not the food that was asked for.
    vi.mocked(api.get).mockResolvedValue({
      ...RESPONSE,
      kind: "Japanese",
      nearby_count: 3,
      matching_count: 3,
      kind_count: 1,
      places: [],
    });
    renderDayPlan();

    expect(await screen.findByText(/No japanese under RM52.97 yet/i)).toBeInTheDocument();
    expect(screen.getByText(/Raise the ceiling/i)).toBeInTheDocument();
  });

  it("keeps blaming the ceiling when the ceiling really is the cause", async () => {
    // The guard against overcorrecting: with everything in range still halal,
    // the ceiling is the only thing left and the copy must still say so.
    vi.mocked(api.get).mockResolvedValue({
      ...RESPONSE,
      nearby_count: 3,
      matching_count: 3,
      places: [],
    });
    renderDayPlan();

    expect(await screen.findByText(/Nothing under RM52.97 yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/not halal/i)).not.toBeInTheDocument();
  });

  it("reports today's room from the server, never inferred from a share", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    // total_sen / share on the first place would give RM52.08, not RM52.97.
    expect(screen.getByText("RM52.97")).toBeInTheDocument();
  });

  it("states nothing is left rather than inventing a room on a spent-out day", async () => {
    // The API floors safe-to-spend at zero and sends no share at all; a share
    // divided into total_sen would print a room the user does not have.
    vi.mocked(api.get).mockResolvedValue({
      ...NOTHING_LEFT,
      cap_sen: 5000,
      places: [{ ...PELITA, share: null, band: "over" }],
    });
    renderDayPlan();

    await screen.findByText("Nasi Kandar Pelita");
    expect(screen.getAllByText("Nothing left in today's room").length).toBeGreaterThan(0);
    expect(screen.queryByText(/% of today's room/i)).not.toBeInTheDocument();
    expect(screen.queryByText("RM6.25")).not.toBeInTheDocument();
  });

  it("sits the ceiling control on the ceiling it names, even at nil", async () => {
    // A range input clamps a value outside its bounds without saying so, which
    // would leave the knob at RM5 beside a figure reading RM0.00.
    vi.mocked(api.get).mockResolvedValue(NOTHING_LEFT);
    renderDayPlan();
    await screen.findByText(/Nothing under RM0.00 yet/i);

    const slider = screen.getByLabelText("Spending ceiling") as HTMLInputElement;
    expect(slider.value).toBe("0");
    expect(screen.getByLabelText("RM0.00")).toBeInTheDocument();
    expect(screen.queryByText("Inside today's room")).not.toBeInTheDocument();
  });

  it("keeps the ceiling control on screen while the new list is fetched", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const slider = screen.getByLabelText("Spending ceiling") as HTMLInputElement;
    fireEvent.change(slider, { target: { value: "3000" } });

    // Unmounting into the loading state here would end the drag on its first step.
    expect(screen.getByLabelText("Spending ceiling")).toBeInTheDocument();
    await waitFor(() => expect(lastRequestedUrl()).toContain("cap_sen=3000"));
  });

  it("does not move the scale out from under a ceiling dragged to the top", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const slider = screen.getByLabelText("Spending ceiling") as HTMLInputElement;
    const top = slider.max;
    fireEvent.change(slider, { target: { value: top } });

    const after = screen.getByLabelText("Spending ceiling") as HTMLInputElement;
    expect(after.max).toBe(top);
    expect(after.value).toBe(top);
  });

  it("never asks for a ceiling of nothing, which the API rejects", async () => {
    vi.mocked(api.get).mockResolvedValue(NOTHING_LEFT);
    renderDayPlan();
    await screen.findByText(/Nothing under RM0.00 yet/i);

    const slider = screen.getByLabelText("Spending ceiling") as HTMLInputElement;
    // Anything the control can reach below RM5 must be asked for as RM5.
    fireEvent.change(slider, { target: { value: "50" } });

    await waitFor(() => expect(lastRequestedUrl()).toContain("cap_sen=500"));
  });

  it("admits when the request fails", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("network down"));
    renderDayPlan();

    expect(await screen.findByText(/couldn't find places/i)).toBeInTheDocument();
  });

  it("re-fetches with the new mode when a mode chip is tapped", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "LRT" }));

    await waitFor(() => expect(lastRequestedUrl()).toContain("mode=transit"));
  });

  it("re-fetches with halal_only=false once the halal toggle is switched off", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Halal" }));

    await waitFor(() => expect(lastRequestedUrl()).toContain("halal_only=false"));
  });

  it("says a blocked location was blocked, and what it is planning from instead", async () => {
    // The bug this guards: locState went to "denied" and nothing on the page
    // read it, so a refused permission looked exactly like an untouched chip.
    // The refusal arrives on its own now — the screen asks on the way in.
    failingGeolocation(1);
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    expect(await screen.findByText(/Location is blocked/i)).toBeInTheDocument();
    // PERMISSION_DENIED does not say who denied it, and a site permission
    // reading "allowed" while the system withholds it is a real case, so the
    // advice must not send anyone to just one of the two settings pages.
    expect(screen.getByText(/your system withholding it/i)).toBeInTheDocument();
    expect(screen.getByText(/planning from KLCC/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Location blocked" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use my location" })).not.toBeInTheDocument();
  });

  it("tells a timeout apart from a refusal, and lets it be tried again", async () => {
    const getCurrentPosition = failingGeolocation(3);
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();

    // Different cause, different advice: settings for a block, another tap here.
    expect(await screen.findByText(/took longer than 15 seconds/i)).toBeInTheDocument();
    expect(screen.queryByText(/your system withholding it/i)).not.toBeInTheDocument();
    const chip = screen.getByRole("button", { name: "Location timed out" });
    expect(chip).toBeEnabled();

    await user.click(chip);
    expect(getCurrentPosition).toHaveBeenCalledTimes(2);
  });

  it("plans from where the user is once located, and says so", async () => {
    geolocationAt(5.4141, 100.3288);
    renderDayPlan();

    expect(await screen.findByRole("button", { name: "Located" })).toBeInTheDocument();
    expect(screen.getByText("Near you")).toBeInTheDocument();
    await waitFor(() => expect(lastRequestedUrl()).toContain("lat=5.4141"));
  });

  it("drops the KLCC list rather than show it under 'where you are'", async () => {
    // The KLCC answer stays valid while only the ceiling moves, so the slider
    // keeps it. It does not survive a change of origin: the header, the voice
    // line and every distance on screen would go on describing KLCC while
    // saying "where you are", 300 km from the nearest of them.
    //
    // The locate on the way in times out, which is what leaves a KLCC list on
    // screen at all; the tap is the one that finds Penang.
    let found = false;
    stubGeolocation(
      vi.fn((success, error) => {
        if (!found) {
          error?.({ code: 3, message: "", PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 });
          return;
        }
        success({ coords: { latitude: 5.4141, longitude: 100.3288 } } as GeolocationPosition);
      }),
    );
    vi.mocked(api.get).mockImplementation((url: string) =>
      String(url).includes("lat=5.4141")
        ? new Promise(() => {}) // the Penang answer never lands
        : Promise.resolve(RESPONSE),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();
    found = true;

    await user.click(screen.getByRole("button", { name: "Location timed out" }));

    expect(await screen.findByText(/Finding what fits today/i)).toBeInTheDocument();
    expect(screen.queryByText("Nasi Kandar Pelita")).not.toBeInTheDocument();
    expect(screen.queryByText(/from where you are/i)).not.toBeInTheDocument();
    expect(screen.queryByText("650 m")).not.toBeInTheDocument();
  });

  it("drops the walking prices rather than show them under a different mode", async () => {
    vi.mocked(api.get).mockImplementation((url: string) =>
      String(url).includes("mode=transit")
        ? new Promise(() => {})
        : Promise.resolve(RESPONSE),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "LRT" }));

    // RM12.50 is what Nasi Kandar costs on foot; by LRT it is not, and a list
    // labelled "lrt from KLCC" showing walking totals is a wrong price.
    expect(await screen.findByText(/Finding what fits today/i)).toBeInTheDocument();
    expect(screen.queryByText("RM12.50")).not.toBeInTheDocument();
  });

  it("names the origin it is really on when a retry fails after a locate", async () => {
    let fail = false;
    stubGeolocation(
      vi.fn((success, error) => {
        if (fail) {
          error?.({ code: 3, message: "", PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 });
          return;
        }
        success({ coords: { latitude: 5.4141, longitude: 100.3288 } } as GeolocationPosition);
      }),
    );
    renderDayPlan();
    await screen.findByRole("button", { name: "Located" });
    const user = userEvent.setup();

    fail = true;
    await user.click(screen.getByRole("button", { name: "Located" }));

    // The first fix is still the origin, so claiming KLCC here would be the
    // same silent lie in the opposite direction.
    expect(await screen.findByText(/still planning from where I last found you/i)).toBeInTheDocument();
    expect(screen.queryByText(/planning from KLCC/i)).not.toBeInTheDocument();
    expect(screen.getByText("Near you")).toBeInTheDocument();
  });

  it("offers KLCC as the way out of an origin with nothing around it", async () => {
    geolocationAt(5.4141, 100.3288);
    vi.mocked(api.get).mockResolvedValue({ ...RESPONSE, nearby_count: 0, matching_count: 0, places: [] });
    renderDayPlan();
    await screen.findByRole("button", { name: "Located" });
    await screen.findByText(/Nothing within range of here/i);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Plan from KLCC instead" }));

    // The chip and the header both name the origin, so neither may keep
    // claiming a location that is no longer being planned from.
    expect(screen.getByText("Near KLCC")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use my location" })).toBeInTheDocument();
    await waitFor(() => expect(lastRequestedUrl()).toContain("lat=3.1577"));
  });

  it("opens a detail sheet with the cost breakdown", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const { sheet } = await openSheet("Nasi Kandar Pelita");
    expect(within(sheet).getAllByText("RM12.50").length).toBeGreaterThan(0);
    expect(within(sheet).getByText("Meal estimate")).toBeInTheDocument();
    expect(within(sheet).getByText("650 m by road")).toBeInTheDocument();
  });
});

describe("DayPlan · finding the user when the screen opens", () => {
  it("asks the device where the user is as soon as the screen opens", async () => {
    // The complaint this answers: nothing on the screen ever tried, so every
    // visit planned from KLCC until somebody thought to tap a chip.
    const getCurrentPosition = geolocationAt(5.4141, 100.3288);
    renderDayPlan();

    expect(await screen.findByText("Near you")).toBeInTheDocument();
    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Located" })).toBeInTheDocument();
    expect(lastRequestedUrl()).toContain("lat=5.4141");
    expect(lastRequestedUrl()).toContain("lng=100.3288");
  });

  it("asks for no list at all while the fix is still in flight", async () => {
    // The window this closes: a whole KLCC plan — its header, its distances,
    // its fares — on screen for the seconds a fix takes, every figure of it
    // replaced the moment the device answers. There is nothing yet to be right
    // about, so nothing is drawn and nothing is fetched.
    const { land } = deferredGeolocationAt(5.4141, 100.3288);
    renderDayPlan();

    expect(await screen.findByText(/Finding where you are/i)).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
    expect(screen.queryByText("Near KLCC")).not.toBeInTheDocument();

    land();

    expect(await screen.findByText("Near you")).toBeInTheDocument();
    const origins = vi.mocked(api.get).mock.calls.map(([url]) => String(url));
    expect(origins.length).toBeGreaterThan(0);
    expect(origins.every((url) => url.includes("lat=5.4141"))).toBe(true);
  });

  it("falls back to KLCC and names the refusal, with nobody tapping anything", async () => {
    failingGeolocation(1);
    renderDayPlan();

    expect(await screen.findByText("Near KLCC")).toBeInTheDocument();
    expect(screen.getByText(/Location is blocked/i)).toBeInTheDocument();
    expect(screen.getByText(/planning from KLCC/i)).toBeInTheDocument();
    expect(lastRequestedUrl()).toContain("lat=3.1577");
    expect(screen.queryByText("Near you")).not.toBeInTheDocument();
  });

  it("names a browser that has no geolocation at all, rather than saying nothing", async () => {
    // jsdom, plain http, some webviews: the object is simply absent, and the
    // fallback still owes the user a reason for being the fallback.
    renderDayPlan();

    expect(
      await screen.findByText(/This browser will not give me your location/i),
    ).toBeInTheDocument();
    expect(screen.getByText("Near KLCC")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Location unavailable" })).toBeInTheDocument();
  });

  it("asks once, however many times the screen re-renders", async () => {
    // Every chip and every step of the ceiling slider re-renders this screen.
    // An effect scoped to any of them would put the browser's permission
    // dialog over a screen the user is in the middle of reading.
    const getCurrentPosition = geolocationAt(5.4141, 100.3288);
    renderDayPlan();
    await screen.findByRole("button", { name: "Located" });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "LRT" }));
    await screen.findByText("Nasi Kandar Pelita");
    await user.click(screen.getByRole("button", { name: "Halal" }));
    await screen.findByText("Nasi Kandar Pelita");
    fireEvent.change(screen.getByLabelText("Spending ceiling"), { target: { value: "3000" } });
    fireEvent.change(screen.getByLabelText("Spending ceiling"), { target: { value: "3500" } });
    await waitFor(() => expect(lastRequestedUrl()).toContain("cap_sen=3500"));

    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
  });

  it("does not ask a second time after a refusal, but the chip still does", async () => {
    // Being nagged for a permission already declined is worse than not being
    // asked. The tap is the one retry there is, and it has to keep working.
    const getCurrentPosition = failingGeolocation(1);
    renderDayPlan();
    await screen.findByText(/Location is blocked/i);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "LRT" }));
    await screen.findByText("Nasi Kandar Pelita");
    fireEvent.change(screen.getByLabelText("Spending ceiling"), { target: { value: "3000" } });
    await waitFor(() => expect(lastRequestedUrl()).toContain("cap_sen=3000"));
    expect(getCurrentPosition).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Location blocked" }));

    expect(getCurrentPosition).toHaveBeenCalledTimes(2);
  });
});

describe("DayPlan · adding a place to today", () => {
  it("writes a real draft, and says where it went", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const { user, sheet } = await openSheet("Nasi Kandar Pelita");
    await user.click(within(sheet).getByRole("button", { name: "Add to today" }));

    expect(api.post).toHaveBeenCalledWith("/v1/day-plan/drafts", {
      name: "Nasi Kandar Pelita",
      total_sen: 1250,
      confidence: "high",
    });
    // A toast that named no destination would leave the user with a draft they
    // have no reason to go looking for.
    expect(await screen.findByText(/waiting in Activity as a draft/i)).toBeInTheDocument();
    expect(screen.getByText(/RM12.50 for Nasi Kandar Pelita/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("never says the money has been set aside", async () => {
    // The prototype's "pencilled in" overstated it: a draft is excluded from
    // every calculation, so nothing whatsoever has been reserved.
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const { user, sheet } = await openSheet("Nasi Kandar Pelita");
    // Said before the tap as well as after it.
    expect(within(sheet).getByText(/Today's money stays where it is until you confirm it/i))
      .toBeInTheDocument();

    await user.click(within(sheet).getByRole("button", { name: "Add to today" }));

    expect(
      await screen.findByText(/Today's money doesn't change until you confirm it/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/pencilled/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/set aside/i)).not.toBeInTheDocument();
  });

  it("sends the whole outing, meal and travel together", async () => {
    // Chee Meng is RM43.00 of food and RM5.00 of fare. RM43.00 is not the
    // figure on the row, and a draft for it would not be what was tapped.
    renderDayPlan();
    await screen.findByText("Chee Meng Chicken Rice");

    const { user, sheet } = await openSheet("Chee Meng Chicken Rice");
    await user.click(within(sheet).getByRole("button", { name: "Add to today" }));

    expect(api.post).toHaveBeenCalledWith("/v1/day-plan/drafts", {
      name: "Chee Meng Chicken Rice",
      total_sen: 4800,
      // The band, not a percentage: what "medium" is worth is the server's to
      // decide, so this screen has no mapping of its own to disagree with.
      confidence: "medium",
    });
  });

  it("keeps the sheet open and claims nothing when the add fails", async () => {
    vi.mocked(api.post).mockRejectedValue(new Error("network down"));
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const { user, sheet } = await openSheet("Nasi Kandar Pelita");
    await user.click(within(sheet).getByRole("button", { name: "Add to today" }));

    expect(await within(sheet).findByText(/Nothing was written/i)).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Nasi Kandar Pelita" })).toBeInTheDocument();
    expect(screen.queryByText(/waiting in Activity as a draft/i)).not.toBeInTheDocument();
  });

  it("does not carry one place's failure into the next place's sheet", async () => {
    vi.mocked(api.post).mockRejectedValue(new Error("network down"));
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const { user, sheet } = await openSheet("Nasi Kandar Pelita");
    await user.click(within(sheet).getByRole("button", { name: "Add to today" }));
    await within(sheet).findByText(/Nothing was written/i);
    await user.click(within(sheet).getByRole("button", { name: "Close" }));

    await user.click(screen.getByRole("button", { name: /Chee Meng Chicken Rice/ }));

    const next = screen.getByRole("dialog", { name: "Chee Meng Chicken Rice" });
    expect(within(next).queryByText(/Nothing was written/i)).not.toBeInTheDocument();
  });
});

describe("DayPlan · the order the list is in", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockResolvedValue(TENSION);
  });

  it("puts the order on the screen, and says what it means", async () => {
    // A weighting the user cannot see is one they can neither trust nor
    // overrule, which is how a two-hour walk reached the top of the list.
    renderDayPlan();
    await screen.findByText("Kenny Hills Bakers");

    expect(screen.getByRole("radio", { name: "Balanced" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Cheapest" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "Closest" })).not.toBeChecked();
    expect(screen.getByText(/Cost and travel time count equally/i)).toBeInTheDocument();
  });

  it("opens on Balanced, which picks the one neither extreme would", async () => {
    renderDayPlan();
    await screen.findByText("Kenny Hills Bakers");

    // RM13.00 at 25 minutes, over RM11.00 at 109 and RM18.00 at 8.
    expect(orderedNames()).toEqual([
      "ABC Bistro Cafe",
      "Kenny Hills Bakers",
      "Gerai Nasi Lemak",
    ]);
  });

  it("orders by the whole outing's cost under Cheapest", async () => {
    renderDayPlan();
    await screen.findByText("Kenny Hills Bakers");
    const user = userEvent.setup();

    await user.click(screen.getByRole("radio", { name: "Cheapest" }));

    expect(orderedNames()).toEqual([
      "Kenny Hills Bakers",
      "ABC Bistro Cafe",
      "Gerai Nasi Lemak",
    ]);
    expect(screen.getByText(/Total outing first/i)).toBeInTheDocument();
  });

  it("orders by travel time under Closest", async () => {
    renderDayPlan();
    await screen.findByText("Kenny Hills Bakers");
    const user = userEvent.setup();

    await user.click(screen.getByRole("radio", { name: "Closest" }));

    expect(orderedNames()).toEqual([
      "Gerai Nasi Lemak",
      "ABC Bistro Cafe",
      "Kenny Hills Bakers",
    ]);
    expect(screen.getByText(/Shortest journey first/i)).toBeInTheDocument();
  });

  it("re-orders the list it already has, without asking the server again", async () => {
    // The endpoint sends every place under the ceiling untruncated, so there is
    // nothing a round trip could add — and a fetch per toggle is a chance for
    // the figures to move under a control that only claims to reorder them.
    renderDayPlan();
    await screen.findByText("Kenny Hills Bakers");
    const before = vi.mocked(api.get).mock.calls.length;
    const user = userEvent.setup();

    await user.click(screen.getByRole("radio", { name: "Cheapest" }));
    await user.click(screen.getByRole("radio", { name: "Closest" }));

    expect(orderedNames()[0]).toBe("Gerai Nasi Lemak");
    expect(vi.mocked(api.get).mock.calls.length).toBe(before);
  });

  it("changes not one figure on any row when the sort changes", async () => {
    // The blend is a preference about ordering. The ringgit and the minutes are
    // claims about the world, and no preference is allowed to touch them.
    renderDayPlan();
    await screen.findByText("Kenny Hills Bakers");
    const balanced = figuresByPlace();
    const user = userEvent.setup();

    await user.click(screen.getByRole("radio", { name: "Cheapest" }));
    const cheapest = figuresByPlace();
    await user.click(screen.getByRole("radio", { name: "Closest" }));
    const closest = figuresByPlace();

    expect(cheapest).toEqual(balanced);
    expect(closest).toEqual(balanced);
    // And the figures are the real ones, not something the blend produced.
    expect(screen.getByText(/Bakery · 7.9 km · 109 min/)).toBeInTheDocument();
    expect(screen.getByText("RM11.00")).toBeInTheDocument();
    expect(screen.getByText(/Malay · 150 m · 8 min/)).toBeInTheDocument();
    expect(screen.getByText("RM18.00")).toBeInTheDocument();
    expect(screen.getByText(/Indian · 1.5 km · 25 min/)).toBeInTheDocument();
    expect(screen.getByText("RM13.00")).toBeInTheDocument();
  });

  it("offers no sort control over a list with nothing to order", async () => {
    vi.mocked(api.get).mockResolvedValue({ ...TENSION, places: [ABC_BISTRO] });
    renderDayPlan();
    await screen.findByText("ABC Bistro Cafe");

    expect(screen.queryByRole("radio", { name: "Cheapest" })).not.toBeInTheDocument();
  });
});

describe("DayPlan · what 'Best fit' is allowed to claim", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockResolvedValue(TENSION);
  });

  it("badges the leader when the outing is one a person would actually make", async () => {
    renderDayPlan();
    await screen.findByText("Kenny Hills Bakers");

    // ABC Bistro: RM13.00, 25 minutes on foot, and it beat the runner-up
    // outright rather than tying with it.
    const badges = screen.getAllByText("Best fit");
    expect(badges).toHaveLength(1);
    expect(badges[0]?.closest(".place")?.textContent).toContain("ABC Bistro Cafe");
  });

  it("badges nothing when the cheapest thing on the list is a two-hour walk", async () => {
    // The bug, exactly: RM11.00 topped the list on cost and was told it was the
    // best fit for the day. Nobody walks 109 minutes to save RM2.
    renderDayPlan();
    await screen.findByText("Kenny Hills Bakers");
    const user = userEvent.setup();

    await user.click(screen.getByRole("radio", { name: "Cheapest" }));

    expect(orderedNames()[0]).toBe("Kenny Hills Bakers");
    expect(screen.queryByText("Best fit")).not.toBeInTheDocument();
    // Still listed, still priced, still addable — only uncrowned.
    expect(screen.getByText("RM11.00")).toBeInTheDocument();
  });

  it("badges the leader under Closest, which is a walk anyone would take", async () => {
    renderDayPlan();
    await screen.findByText("Kenny Hills Bakers");
    const user = userEvent.setup();

    await user.click(screen.getByRole("radio", { name: "Closest" }));

    const badges = screen.getAllByText("Best fit");
    expect(badges).toHaveLength(1);
    expect(badges[0]?.closest(".place")?.textContent).toContain("Gerai Nasi Lemak");
  });

  it("badges nothing when the leader only tied for first", async () => {
    // Two outings at the same price are equally the cheapest, and picking one
    // of them to crown is the arbitrary choice the old "row one" badge made.
    vi.mocked(api.get).mockResolvedValue({
      ...TENSION,
      places: [ABC_BISTRO, { ...GERAI, total_sen: ABC_BISTRO.total_sen }],
    });
    renderDayPlan();
    await screen.findByText("ABC Bistro Cafe");
    const user = userEvent.setup();

    await user.click(screen.getByRole("radio", { name: "Cheapest" }));

    expect(screen.queryByText("Best fit")).not.toBeInTheDocument();
  });

  it("badges nothing that does not fit today", async () => {
    // "Over" and "Best fit" on the same row contradict each other, and on a
    // spent-out day every place is over.
    vi.mocked(api.get).mockResolvedValue({
      ...TENSION,
      places: TENSION.places.map((place) => ({ ...place, share: null, band: "over" as const })),
    });
    renderDayPlan();
    await screen.findByText("Kenny Hills Bakers");

    expect(screen.queryByText("Best fit")).not.toBeInTheDocument();
    expect(screen.getAllByText("Over").length).toBe(3);
  });
});

describe("DayPlan · which distance the numbers are on", () => {
  it("does not print a straight-line figure the way it prints a road one", async () => {
    // The same place, the same fare, on two different measurements: 3.7 km of
    // great circle where the road is 8.1 km. If these two render identically
    // the screen is quoting the optimistic one as though it were the journey.
    vi.mocked(api.get).mockResolvedValue({
      ...RESPONSE,
      places: [PELITA, fellBack(CHEE_MENG, 3.7)],
    });
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    expect(screen.getByText(/Mamak · 650 m by road · 14 min/)).toBeInTheDocument();
    expect(screen.getByText(/Chinese · 3.7 km straight line · 22 min/)).toBeInTheDocument();
  });

  it("leaves the rows unqualified when every distance on them is a road one", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    // Nothing to tell apart, so nothing is hedged: the rows read as the plain
    // figures they are, and no fallback notice is raised over a routed list.
    expect(screen.getByText(/Mamak · 650 m · 14 min/)).toBeInTheDocument();
    expect(screen.queryByText(/straight line/i)).not.toBeInTheDocument();
  });

  it("says once, above the list, that a wholly unrouted list is straight lines", async () => {
    const places = [
      fellBack(PELITA, 0.61),
      fellBack(CHEE_MENG, 3.7),
      fellBack(SKY_BAR, 2.9),
    ];
    vi.mocked(api.get).mockResolvedValue({ ...RESPONSE, places });
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    expect(
      screen.getAllByText(/every distance below is a straight line/i),
    ).toHaveLength(1);
    // Said once at the top rather than repeated down every row.
    expect(screen.queryByText(/km straight line ·/)).not.toBeInTheDocument();
    expect(screen.getByText(/Chinese · 3.7 km · 22 min/)).toBeInTheDocument();
  });

  it("keeps the fallback notice off a list that has any road distance in it", async () => {
    vi.mocked(api.get).mockResolvedValue({
      ...RESPONSE,
      places: [PELITA, fellBack(CHEE_MENG, 3.7)],
    });
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    // One line claiming the whole list is straight lines would be false here,
    // and the rows already name each place's own basis.
    expect(screen.queryByText(/every distance below is a straight line/i)).not.toBeInTheDocument();
  });

  it("names the basis in the sheet, and what the fare was priced on", async () => {
    vi.mocked(api.get).mockResolvedValue({
      ...RESPONSE,
      places: [PELITA, fellBack(CHEE_MENG, 3.7)],
    });
    renderDayPlan();
    await screen.findByText("Chee Meng Chicken Rice");

    const { sheet } = await openSheet("Chee Meng Chicken Rice");
    expect(within(sheet).getByText("3.7 km straight line")).toBeInTheDocument();
    expect(within(sheet).getByText(/RM5.00 of travel is priced on the short figure/)).toBeInTheDocument();
  });

  it("carries no straight-line caveat into the sheet of a routed place", async () => {
    renderDayPlan();
    await screen.findByText("Chee Meng Chicken Rice");

    const { sheet } = await openSheet("Chee Meng Chicken Rice");
    expect(within(sheet).getByText("1.8 km by road")).toBeInTheDocument();
    expect(within(sheet).queryByText(/straight line/i)).not.toBeInTheDocument();
  });
});

describe("DayPlan · finding the shop again", () => {
  it("shows the address the API gave, locality and all", async () => {
    renderDayPlan();
    await screen.findByText("Chee Meng Chicken Rice");

    // "Ampang, Kuala Lumpur" is a locality, not a doorstep. That is what the
    // field says, so that is what the sheet shows — no invented precision.
    const { sheet } = await openSheet("Chee Meng Chicken Rice");
    expect(within(sheet).getByText("Ampang, Kuala Lumpur")).toBeInTheDocument();
  });

  it("points Maps at the coordinates rather than searching for the name", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const { sheet } = await openSheet("Nasi Kandar Pelita");
    const link = within(sheet).getByRole("link", { name: /Open Nasi Kandar Pelita in Google Maps/ });
    expect(link).toHaveAttribute(
      "href",
      "https://www.google.com/maps/search/?api=1&query=3.1591%2C101.7132",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener");
  });

  it("sends two branches of one name to two different pins", async () => {
    // The reason the query is a point and not a name: this set really does
    // hold shops whose name alone cannot say which one is meant.
    const other: Place = { ...PELITA, id: "p1b", lat: 3.1102, lng: 101.6784 };
    vi.mocked(api.get).mockResolvedValue({ ...RESPONSE, places: [PELITA, other] });
    renderDayPlan();
    await screen.findAllByText("Nasi Kandar Pelita");
    const user = userEvent.setup();

    const rows = screen.getAllByRole("button", { name: /Nasi Kandar Pelita/ });
    expect(rows).toHaveLength(2);

    const hrefs: (string | null)[] = [];
    for (const row of rows) {
      await user.click(row);
      const dialog = screen.getByRole("dialog");
      hrefs.push(within(dialog).getByRole("link", { name: /in Google Maps/ }).getAttribute("href"));
      await user.click(within(dialog).getByRole("button", { name: "Close" }));
    }

    expect(hrefs).toEqual([
      "https://www.google.com/maps/search/?api=1&query=3.1591%2C101.7132",
      "https://www.google.com/maps/search/?api=1&query=3.1102%2C101.6784",
    ]);
  });

  it("copies the name and address, and says it did", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const { user, sheet } = await openSheet("Nasi Kandar Pelita");
    const writeText = stubClipboard(async () => {});
    await user.click(within(sheet).getByRole("button", { name: "Copy name and address" }));

    expect(writeText).toHaveBeenCalledWith(
      "Nasi Kandar Pelita, 166 Jalan Ampang, 50450 Kuala Lumpur",
    );
    // The sheet stays open, so the confirmation has to clear it on screen —
    // hence the toast sitting above the sheet rather than behind its scrim.
    expect(
      await screen.findByText("Nasi Kandar Pelita and its address copied."),
    ).toBeInTheDocument();
  });

  it("admits it when there is no clipboard to write to", async () => {
    // http, an old browser, a webview: navigator.clipboard is simply absent,
    // and the button must not sit there looking as though it worked.
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const { user, sheet } = await openSheet("Nasi Kandar Pelita");
    removeClipboard();
    await user.click(within(sheet).getByRole("button", { name: "Copy name and address" }));

    expect(await within(sheet).findByText(/won't give me the clipboard/i)).toBeInTheDocument();
    expect(within(sheet).getByText(/Nothing was copied/i)).toBeInTheDocument();
    // The text is handed back rather than lost with the failure.
    expect(
      within(sheet).getByText("Nasi Kandar Pelita, 166 Jalan Ampang, 50450 Kuala Lumpur"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/and its address copied/i)).not.toBeInTheDocument();
  });

  it("admits it when the clipboard refuses the write", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const { user, sheet } = await openSheet("Nasi Kandar Pelita");
    const writeText = stubClipboard(() => Promise.reject(new Error("denied")));
    await user.click(within(sheet).getByRole("button", { name: "Copy name and address" }));

    expect(writeText).toHaveBeenCalled();
    expect(await within(sheet).findByText(/turned down the copy/i)).toBeInTheDocument();
    expect(within(sheet).getByText(/Nothing was copied/i)).toBeInTheDocument();
    expect(screen.queryByText(/and its address copied/i)).not.toBeInTheDocument();
  });
});

describe("DayPlan · the ask box", () => {
  /** Two POSTs share the mock, so it answers by path. */
  function answering(answer: DayPlanReading | Error) {
    vi.mocked(api.post).mockImplementation((path: string) =>
      String(path).endsWith("/interpret")
        ? answer instanceof Error
          ? Promise.reject(answer)
          : Promise.resolve(answer)
        : Promise.resolve(PLAN_DRAFT),
    );
  }

  async function askFor(sentence: string) {
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Say what you're after"), sentence);
    await user.click(screen.getByRole("button", { name: "Set filters" }));
    return user;
  }

  function ceiling(): string {
    return (screen.getByLabelText("Spending ceiling") as HTMLInputElement).value;
  }

  it("turns a sentence into the chips, the ceiling and the sort", async () => {
    // The whole point of the endpoint: natural language is an input method for
    // the controls, so what it understood is a thing the user can see and tap
    // back — not a paragraph sitting above a list it may or may not describe.
    answering(reading());
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    await askFor("cheapest ride under RM15, halal off");

    await waitFor(() => expect(screen.getByRole("button", { name: "Grab" })).toHaveClass("on"));
    expect(screen.getByRole("button", { name: "Halal" })).not.toHaveClass("on");
    expect(screen.getByRole("button", { name: "Walk" })).not.toHaveClass("on");
    expect(screen.getByRole("radio", { name: "Closest" })).toBeChecked();
    expect(ceiling()).toBe("1500");
  });

  it("re-asks for the list through the ordinary query, with the new filters", async () => {
    // No second list and no rendering of its own: the rows below re-rank
    // because the controls moved, exactly as they do for a tapped chip.
    answering(reading());
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    await askFor("cheapest ride under RM15, halal off");

    await waitFor(() => expect(lastRequestedUrl()).toContain("cap_sen=1500"));
    expect(lastRequestedUrl()).toContain("mode=ride");
    expect(lastRequestedUrl()).toContain("halal_only=false");
  });

  it("shows the line the server built from the filters it applied", async () => {
    answering(reading());
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    await askFor("cheapest ride under RM15, halal off");

    expect(
      await screen.findByText("I read that as halal off, under RM15.00, by Grab, closest first."),
    ).toBeInTheDocument();
  });

  it("says what it could not place, without holding back the rest", async () => {
    // Where the search is measured from is not the model's to set, so a place
    // name in the sentence comes back unread rather than moving the list.
    answering(
      reading({
        filters: {
          lat: 3.1577,
          lng: 101.712,
          mode: "walk",
          halal_only: true,
          cap_sen: 1500,
          sort: "balanced",
        },
        understood: "I read that as under RM15.00.",
        unread: "near Bangsar",
      }),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    await askFor("under RM15 near Bangsar");

    expect(await screen.findByText(/I couldn't place “near Bangsar”/)).toBeInTheDocument();
    expect(screen.getByText(/I read that as under RM15.00/)).toBeInTheDocument();
    await waitFor(() => expect(ceiling()).toBe("1500"));
  });

  it("never moves the origin, whatever the reading carries", async () => {
    // A location the user did not give is the one thing on this screen a model
    // must not be able to invent: every distance below would go on being true
    // of somewhere else.
    answering(
      reading({
        filters: {
          lat: 5.4141,
          lng: 100.3288,
          mode: "walk",
          halal_only: true,
          cap_sen: 1500,
          sort: "balanced",
        },
        understood: "I read that as under RM15.00.",
      }),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    await askFor("somewhere halal near Penang under RM15");

    await waitFor(() => expect(lastRequestedUrl()).toContain("cap_sen=1500"));
    expect(lastRequestedUrl()).toContain("lat=3.1577");
    expect(lastRequestedUrl()).toContain("lng=101.712");
    expect(screen.getByText("Near KLCC")).toBeInTheDocument();
  });

  it("sends the sentence with the controls exactly as they stand", async () => {
    // Most sentences speak to one control. Without the rest going across, the
    // ones they say nothing about would come back at the schema's defaults.
    answering(reading());
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "LRT" }));
    await screen.findByText("Nasi Kandar Pelita");

    await askFor("halal under RM15");

    expect(api.post).toHaveBeenCalledWith("/v1/day-plan/interpret", {
      text: "halal under RM15",
      lat: 3.1577,
      lng: 101.712,
      mode: "transit",
      halal_only: true,
      cap_sen: null,
      kind: null,
      sort: "balanced",
    });
  });

  it("leaves every control exactly as it was when the sentence could not be read", async () => {
    answering(
      reading({
        applied: false,
        filters: null,
        understood: "",
        reason: "I could not read that into these filters. Nothing below has changed.",
      }),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const before = vi.mocked(api.get).mock.calls.length;

    await askFor("mmm");

    expect(
      await screen.findByText(/could not read that into these filters/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Walk" })).toHaveClass("on");
    expect(screen.getByRole("button", { name: "Halal" })).toHaveClass("on");
    expect(screen.getByRole("button", { name: "Grab" })).not.toHaveClass("on");
    expect(screen.getByRole("radio", { name: "Balanced" })).toBeChecked();
    expect(ceiling()).toBe(String(ROOM_SEN));
    // Nothing moved, so there was nothing to ask the server about again.
    expect(vi.mocked(api.get).mock.calls.length).toBe(before);
  });

  it("leaves every control alone when the request never lands", async () => {
    answering(new Error("network down"));
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const before = vi.mocked(api.get).mock.calls.length;

    await askFor("halal under RM15");

    expect(await screen.findByText(/the request didn't get through/i)).toBeInTheDocument();
    expect(screen.getByText(/Nothing below has changed/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Walk" })).toHaveClass("on");
    expect(screen.getByRole("button", { name: "Halal" })).toHaveClass("on");
    expect(screen.getByRole("radio", { name: "Balanced" })).toBeChecked();
    expect(ceiling()).toBe(String(ROOM_SEN));
    expect(vi.mocked(api.get).mock.calls.length).toBe(before);
  });

  it("drops the last reading as soon as the sentence is edited", async () => {
    // A line describing the previous sentence, sitting under a new one, reads
    // as a line about the new one.
    answering(reading());
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const user = await askFor("cheapest ride under RM15, halal off");
    await screen.findByText("I read that as halal off, under RM15.00, by Grab, closest first.");
    await user.type(screen.getByLabelText("Say what you're after"), " and quick");

    expect(screen.queryByText(/I read that as/)).not.toBeInTheDocument();
    // The chips it already set stay set: the reading is gone, not undone.
    expect(screen.getByRole("radio", { name: "Closest" })).toBeChecked();
  });

  it("asks nothing on an empty box", async () => {
    answering(reading());
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    expect(screen.getByRole("button", { name: "Set filters" })).toBeDisabled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("sets the kind of food, and shows it as a chip that can be taken off", async () => {
    // The one control with no permanent chip of its own: twenty-two kinds is a
    // wall nobody reads, so the chip appears when the filter is on. Without it
    // the ask box could narrow the list to something the user can see only in
    // what is missing from it.
    answering(
      reading({
        filters: {
          lat: 3.1577,
          lng: 101.712,
          mode: "walk",
          halal_only: true,
          cap_sen: null,
          kind: "Noodles",
          sort: "balanced",
        },
        understood: "I read that as noodles.",
      }),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const user = await askFor("I want noodles");

    await waitFor(() => expect(lastRequestedUrl()).toContain("kind=Noodles"));
    const chip = screen.getByRole("button", { name: "Clear the Noodles filter" });
    expect(chip).toHaveClass("on");

    await user.click(chip);

    await waitFor(() => expect(lastRequestedUrl()).not.toContain("kind="));
    expect(
      screen.queryByRole("button", { name: "Clear the Noodles filter" }),
    ).not.toBeInTheDocument();
  });

  it("leaves the kind alone when the reading carries none", async () => {
    answering(reading());
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    await askFor("cheapest ride under RM15, halal off");

    await waitFor(() => expect(lastRequestedUrl()).toContain("cap_sen=1500"));
    expect(lastRequestedUrl()).not.toContain("kind=");
  });
});

describe("DayPlan · the part the filters cannot hold", () => {
  function answering(answer: DayPlanReading) {
    vi.mocked(api.post).mockImplementation((path: string) =>
      String(path).endsWith("/interpret") ? Promise.resolve(answer) : Promise.resolve(PLAN_DRAFT),
    );
  }

  async function askFor(sentence: string) {
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Say what you're after"), sentence);
    await user.click(screen.getByRole("button", { name: "Set filters" }));
    return user;
  }

  beforeEach(() => {
    // A sentence left in the slot by one case would be asked by the next
    // Butler to open, which in this file is nobody and in the app is the user.
    takeButlerHandoff();
  });

  it("offers the Butler the sentence when part of it produced no filter", async () => {
    answering(
      reading({
        understood: "I read that as under RM15.00.",
        unread: "what's actually good tonight",
      }),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    await askFor("under RM15, and what's actually good tonight");

    expect(
      await screen.findByRole("button", { name: "Ask Kira about this" }),
    ).toBeInTheDocument();
  });

  it("offers it for a sentence the filters could do nothing with at all", async () => {
    // Nothing applied and nothing to apply: the chips have no answer to this
    // one, which is exactly when the conversation is the whole of the answer.
    answering(
      reading({
        applied: false,
        filters: null,
        understood: "",
        unread: "what should I actually eat tonight",
        reason: "There is nothing in that I can set on this screen. Nothing below has changed.",
      }),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    await askFor("what should I actually eat tonight");

    expect(
      await screen.findByRole("button", { name: "Ask Kira about this" }),
    ).toBeInTheDocument();
  });

  it("does not offer it for a sentence the filters read whole", async () => {
    // Every word of this became a chip, so there is nothing left to take
    // anywhere. An offer standing here anyway would be inviting the user out
    // of a screen that has already answered them.
    answering(reading());
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    await askFor("cheapest ride under RM15, halal off");

    await screen.findByText(/I read that as halal off/);
    expect(
      screen.queryByRole("button", { name: "Ask Kira about this" }),
    ).not.toBeInTheDocument();
  });

  it("hands over the sentence as it was written, not the fragment it could not place", async () => {
    // "under RM15" is the half that makes "what's actually good tonight"
    // answerable, so the Butler is given the whole sentence.
    answering(
      reading({
        understood: "I read that as under RM15.00.",
        unread: "what's actually good tonight",
      }),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = await askFor("under RM15, and what's actually good tonight");

    await user.click(await screen.findByRole("button", { name: "Ask Kira about this" }));

    expect(takeButlerHandoff()).toBe("under RM15, and what's actually good tonight");
  });

  it("says where the question went, since tapping cannot move the user there", async () => {
    answering(
      reading({
        understood: "I read that as under RM15.00.",
        unread: "what's actually good tonight",
      }),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = await askFor("under RM15, and what's actually good tonight");

    await user.click(await screen.findByRole("button", { name: "Ask Kira about this" }));

    expect(await screen.findByText(/waiting in the Butler/i)).toBeInTheDocument();
    expect(screen.getByText(/Open the Butler tab below/i)).toBeInTheDocument();
    // The offer does not stand a second time for the same sentence.
    expect(
      screen.queryByRole("button", { name: "Ask Kira about this" }),
    ).not.toBeInTheDocument();
  });

  it("answers nothing itself, and moves no control, when the question is handed over", async () => {
    // The chips and the rows stay the single account of what is being shown.
    // A reply appearing here would be a second one, with nothing on the page
    // to say which of them the list below came from.
    answering(
      reading({
        understood: "I read that as under RM15.00.",
        unread: "what's actually good tonight",
      }),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = await askFor("under RM15, and what's actually good tonight");
    await waitFor(() => expect(lastRequestedUrl()).toContain("cap_sen=1500"));
    const asked = vi.mocked(api.get).mock.calls.length;
    const posted = vi.mocked(api.post).mock.calls.length;

    await user.click(await screen.findByRole("button", { name: "Ask Kira about this" }));

    expect(vi.mocked(api.get).mock.calls.length).toBe(asked);
    expect(vi.mocked(api.post).mock.calls.length).toBe(posted);
    expect(screen.getByText("Nasi Kandar Pelita")).toBeInTheDocument();
    expect(screen.getByText(/I read that as under RM15.00/)).toBeInTheDocument();
  });

  it("drops the offer when the sentence is edited, and takes the waiting question with it", async () => {
    // The offer belongs to the sentence that was read. Left standing under a
    // half-typed new one, it would hand over words the user has moved on from.
    answering(
      reading({
        understood: "I read that as under RM15.00.",
        unread: "what's actually good tonight",
      }),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = await askFor("under RM15, and what's actually good tonight");
    await screen.findByRole("button", { name: "Ask Kira about this" });

    await user.type(screen.getByLabelText("Say what you're after"), " near work");

    expect(
      screen.queryByRole("button", { name: "Ask Kira about this" }),
    ).not.toBeInTheDocument();
    expect(takeButlerHandoff()).toBeNull();
  });
});

describe("DayPlan · the reading and the controls cannot contradict each other", () => {
  function answering(answer: DayPlanReading) {
    vi.mocked(api.post).mockImplementation((path: string) =>
      String(path).endsWith("/interpret") ? Promise.resolve(answer) : Promise.resolve(PLAN_DRAFT),
    );
  }

  async function askFor(sentence: string) {
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Say what you're after"), sentence);
    await user.click(screen.getByRole("button", { name: "Set filters" }));
    return user;
  }

  it("drops the reading when the user answers it by tapping a chip", async () => {
    // The claim made for this box is that a misreading is correctable by
    // tapping the control it got wrong. Left standing over the corrected chip,
    // the line describes the opposite of what the list is now filtered by.
    answering(
      reading({
        filters: {
          lat: 3.1577,
          lng: 101.712,
          mode: "walk",
          halal_only: true,
          cap_sen: null,
          sort: "balanced",
        },
        understood: "I read that as halal only.",
      }),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Halal" }));
    await screen.findByText("Nasi Kandar Pelita");

    await askFor("halal please");
    await screen.findByText("I read that as halal only.");
    expect(screen.getByRole("button", { name: "Halal" })).toHaveClass("on");

    await user.click(screen.getByRole("button", { name: "Halal" }));

    expect(screen.getByRole("button", { name: "Halal" })).not.toHaveClass("on");
    expect(screen.queryByText("I read that as halal only.")).not.toBeInTheDocument();
  });

  it("drops the reading when the user picks a different sort", async () => {
    answering(reading());
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    await askFor("cheapest ride under RM15, halal off");
    await screen.findByText("I read that as halal off, under RM15.00, by Grab, closest first.");

    await userEvent.setup().click(screen.getByRole("radio", { name: "Balanced" }));

    expect(screen.queryByText(/I read that as/)).not.toBeInTheDocument();
  });

  it("drops the reading when the user picks a different way to travel", async () => {
    answering(reading());
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    await askFor("cheapest ride under RM15, halal off");
    await screen.findByText("I read that as halal off, under RM15.00, by Grab, closest first.");

    await userEvent.setup().click(screen.getByRole("button", { name: "Walk" }));

    expect(screen.queryByText(/I read that as/)).not.toBeInTheDocument();
  });

  it("drops the reading when the user drags the ceiling", async () => {
    answering(reading());
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    await askFor("cheapest ride under RM15, halal off");
    await screen.findByText("I read that as halal off, under RM15.00, by Grab, closest first.");

    fireEvent.change(screen.getByLabelText("Spending ceiling"), { target: { value: "2500" } });

    expect(screen.queryByText(/I read that as/)).not.toBeInTheDocument();
  });

  it("keeps the chips the reading set, so clearing is not undoing", async () => {
    answering(reading());
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    await askFor("cheapest ride under RM15, halal off");
    await waitFor(() => expect(screen.getByRole("radio", { name: "Closest" })).toBeChecked());

    await userEvent.setup().click(screen.getByRole("button", { name: "Halal" }));

    // The line is gone; every other control it set is still where it put it.
    expect(screen.queryByText(/I read that as/)).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Closest" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Grab" })).toHaveClass("on");
    expect(
      (screen.getByLabelText("Spending ceiling") as HTMLInputElement).value,
    ).toBe("1500");
  });
});

describe("DayPlan · the nearest places above the ceiling", () => {
  /** Two places over a RM10 ceiling, which is the case the whole group is for:
   *  a ceiling below everything nearby. Both sit inside today's room, so the
   *  band is not something the room would have produced on its own. */
  const OVER_ONE: Place = {
    ...PELITA,
    id: "o1",
    name: "Mee Sepuluh",
    total_sen: 1150,
    share: 1150 / ROOM_SEN,
    band: "over",
  };
  const OVER_TWO: Place = {
    ...GERAI,
    id: "o2",
    name: "Warung Dua Belas",
    total_sen: 1250,
    share: 1250 / ROOM_SEN,
    band: "over",
  };

  const NOTHING_FITS: DayPlanData = {
    ...RESPONSE,
    cap_sen: 1000,
    places: [],
    nearest_over_cap: [OVER_ONE, OVER_TWO],
  };

  it("offers the nearest places instead of an empty list", async () => {
    vi.mocked(api.get).mockResolvedValue(NOTHING_FITS);
    renderDayPlan();

    // The ceiling is still stated as respected, which is the whole bargain.
    expect(await screen.findByText(/Nothing under RM10.00 yet/i)).toBeInTheDocument();
    expect(screen.getByText("Mee Sepuluh")).toBeInTheDocument();
    expect(screen.getByText("Warung Dua Belas")).toBeInTheDocument();
  });

  it("names the group as over the ceiling rather than letting it read as the list", async () => {
    vi.mocked(api.get).mockResolvedValue(NOTHING_FITS);
    renderDayPlan();

    expect(await screen.findByText(/Over your ceiling/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Nothing fitted RM10.00, so here are the 2 places closest above it/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/They are not in the list because they do not fit/i),
    ).toBeInTheDocument();
  });

  it("says how far over the closest one is, rather than leaving an absence", async () => {
    vi.mocked(api.get).mockResolvedValue(NOTHING_FITS);
    renderDayPlan();

    // RM11.50 against a RM10 ceiling: the shortfall is the figure that makes
    // "nothing fits" into something the user can act on.
    expect(await screen.findByText(/The closest is RM11.50 — RM1.50 over/i)).toBeInTheDocument();
  });

  it("marks every one of them over on the row itself", async () => {
    vi.mocked(api.get).mockResolvedValue(NOTHING_FITS);
    renderDayPlan();
    await screen.findByText("Mee Sepuluh");

    // Not "Over", which is the room's word: these are over the ceiling, and
    // the ceiling here is well below the room.
    expect(screen.getAllByText("Over ceiling")).toHaveLength(2);
    expect(screen.queryByText("Best fit")).not.toBeInTheDocument();
  });

  it("draws them as a group the list above did not admit", async () => {
    vi.mocked(api.get).mockResolvedValue(NOTHING_FITS);
    renderDayPlan();
    await screen.findByText("Mee Sepuluh");

    const rows = Array.from(document.querySelectorAll<HTMLElement>(".place"));
    expect(rows).toHaveLength(2);
    // Every row on screen carries the marker, because every row on screen is
    // one the ceiling turned away.
    expect(rows.every((row) => row.classList.contains("over-cap"))).toBe(true);
  });

  it("shows no group at all when the ceiling admitted something", async () => {
    // The trigger is a completely empty list and never a thin one, so a list
    // with somewhere to eat in it is not topped up from above the ceiling.
    vi.mocked(api.get).mockResolvedValue(RESPONSE);
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    expect(screen.queryByText(/Over your ceiling/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Over ceiling")).not.toBeInTheDocument();
    expect(document.querySelectorAll(".place.over-cap")).toHaveLength(0);
  });

  it("says nothing about a ceiling when distance is what emptied the list", async () => {
    vi.mocked(api.get).mockResolvedValue({
      ...RESPONSE,
      nearby_count: 0,
      matching_count: 0,
      kind_count: 0,
      places: [],
      nearest_over_cap: [],
  nearest_beyond_radius: [],
    });
    renderDayPlan();

    expect(await screen.findByText(/Nothing within range of here/i)).toBeInTheDocument();
    expect(screen.queryByText(/Over your ceiling/i)).not.toBeInTheDocument();
  });

  it("still says the group is halal when the halal filter is on", async () => {
    // The ceiling is the only thing relaxed. Saying so is what keeps the offer
    // from reading as a filter quietly dropped.
    vi.mocked(api.get).mockResolvedValue(NOTHING_FITS);
    renderDayPlan();

    expect(await screen.findByText(/still halal/i)).toBeInTheDocument();
  });

  it("names every filter the group still honours, kind included", async () => {
    vi.mocked(api.get).mockResolvedValue({ ...NOTHING_FITS, kind: "Japanese", kind_count: 2 });
    renderDayPlan();

    expect(await screen.findByText(/still japanese and halal/i)).toBeInTheDocument();
  });

  it("says it in the singular when the ceiling turned away one place", async () => {
    vi.mocked(api.get).mockResolvedValue({ ...NOTHING_FITS, nearest_over_cap: [OVER_ONE] });
    renderDayPlan();

    expect(
      await screen.findByText(/here is the one place closest above it/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/It is not in the list because it does not fit/i),
    ).toBeInTheDocument();
  });

  it("opens one of them, and talks about the ceiling rather than a negative room", async () => {
    vi.mocked(api.get).mockResolvedValue(NOTHING_FITS);
    renderDayPlan();
    await screen.findByText("Mee Sepuluh");

    const { sheet } = await openSheet("Mee Sepuluh");

    // total − room here is −RM41.47. "RM-41.47 over today's room" is exactly
    // the figure this app may never print.
    expect(
      within(sheet).getByText(/RM1.50 over the RM10.00 ceiling/i),
    ).toBeInTheDocument();
    expect(within(sheet).getByText(/Today's room would still cover it/i)).toBeInTheDocument();
    expect(within(sheet).queryByText(/over today's room/i)).not.toBeInTheDocument();
  });

  it("adds one to today at the price the row showed", async () => {
    // It did not fit the ceiling, and it is still a real outing at a real
    // price — the draft is the row's own figure, like every other.
    vi.mocked(api.get).mockResolvedValue(NOTHING_FITS);
    renderDayPlan();
    await screen.findByText("Mee Sepuluh");

    const { user, sheet } = await openSheet("Mee Sepuluh");
    await user.click(within(sheet).getByRole("button", { name: "Add to today" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/v1/day-plan/drafts", {
        name: "Mee Sepuluh",
        total_sen: 1150,
        confidence: "high",
      }),
    );
  });
});

describe("DayPlan · a place that matched on a belief rather than a tag", () => {
  /**
   * The list is wider than the map is. A kind filter matches what
   * OpenStreetMap records about a shop and also what a model believed about it
   * when the data was built — which is the only way a chicken search reaches
   * the McDonald's that OSM calls a burger shop and stops. The rows have to go
   * on saying which is which: the user asked for a longer list, not to be told
   * a guess is a fact.
   */
  // The ids run against the answer on purpose. Ties used to fall to the lower
  // id, so a belief at "m1" would lead a tagged place at "m2" on every figure
  // being equal — which is exactly the ordering the basis has to overturn.
  const TAGGED: Place = {
    ...PELITA,
    id: "m2",
    name: "Ayam Bertanda",
    kind: "Chicken",
    match_basis: "tagged",
  };
  const BELIEVED: Place = {
    ...PELITA,
    id: "m1",
    name: "Burger Bakar Satu",
    kind: "Burgers",
    match_basis: "inferred",
  };
  /** Belief first and level on every figure, so the ordering below has work to do. */
  const CHICKEN: DayPlanData = {
    ...RESPONSE,
    kind: "Chicken",
    nearby_count: 4,
    matching_count: 4,
    kind_count: 2,
    places: [BELIEVED, TAGGED],
  };

  function rowFor(name: string): HTMLElement {
    const row = Array.from(document.querySelectorAll<HTMLElement>(".place")).find(
      (each) => each.querySelector("b")?.textContent === name,
    );
    if (!row) throw new Error(`no row for ${name}`);
    return row;
  }

  it("hedges the row it is only believed to be right about", async () => {
    vi.mocked(api.get).mockResolvedValue(CHICKEN);
    renderDayPlan();
    await screen.findByText("Burger Bakar Satu");

    // The map's word for the shop is still the map's word, and the guess is
    // beside it rather than in place of it.
    expect(rowFor("Burger Bakar Satu").textContent).toContain("Burgers");
    expect(rowFor("Burger Bakar Satu").textContent).toContain("may also do chicken");
  });

  it("says nothing of the kind on a row the map really does tag", async () => {
    vi.mocked(api.get).mockResolvedValue(CHICKEN);
    renderDayPlan();
    await screen.findByText("Ayam Bertanda");

    // A hedge here would be an apology for data that is not a guess, and the
    // two rows would read alike again from the other direction.
    expect(rowFor("Ayam Bertanda").textContent).toContain("Chicken");
    expect(rowFor("Ayam Bertanda").textContent).not.toContain("may also do");
  });

  it("says nothing of the kind on a list nobody narrowed", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    expect(screen.queryByText(/may also do/i)).not.toBeInTheDocument();
  });

  it("puts the tag above the belief where nothing else separates them", async () => {
    vi.mocked(api.get).mockResolvedValue(CHICKEN);
    renderDayPlan();
    await screen.findByText("Ayam Bertanda");

    // Identical price, distance and journey, and the response listed the belief
    // first. One of the two is known and the other is guessed.
    expect(orderedNames()).toEqual(["Ayam Bertanda", "Burger Bakar Satu"]);
  });

  it("still lets a cheaper belief beat a dearer tag", async () => {
    // The basis breaks ties and does nothing else. Re-ordering the list on
    // something the user cannot see, beside figures they can, is what the sort
    // control exists not to do.
    vi.mocked(api.get).mockResolvedValue({
      ...CHICKEN,
      places: [{ ...TAGGED, total_sen: 2400 }, BELIEVED],
    });
    renderDayPlan();
    await screen.findByText("Burger Bakar Satu");

    expect(orderedNames()).toEqual(["Burger Bakar Satu", "Ayam Bertanda"]);
  });

  it("badges neither of two places a tie separated", async () => {
    vi.mocked(api.get).mockResolvedValue(CHICKEN);
    renderDayPlan();
    await screen.findByText("Ayam Bertanda");

    // "Best fit" is a claim about winning, and a tag standing ahead of a belief
    // has not won on cost or on time. The badge rule is untouched by any of
    // this.
    expect(screen.queryByText("Best fit")).not.toBeInTheDocument();
  });

  it("spells the guess out in full when the row is opened", async () => {
    vi.mocked(api.get).mockResolvedValue(CHICKEN);
    renderDayPlan();
    await screen.findByText("Burger Bakar Satu");

    const { sheet } = await openSheet("Burger Bakar Satu");
    expect(within(sheet).getByText(/it is not tagged chicken/i)).toBeInTheDocument();
    expect(within(sheet).getByText(/records a guess/i)).toBeInTheDocument();
    expect(within(sheet).getByText(/Nobody here has read its menu/i)).toBeInTheDocument();
  });

  it("puts nothing of the kind in the sheet of a place the map tags", async () => {
    vi.mocked(api.get).mockResolvedValue(CHICKEN);
    renderDayPlan();
    await screen.findByText("Ayam Bertanda");

    const { sheet } = await openSheet("Ayam Bertanda");
    expect(within(sheet).queryByText(/records a guess/i)).not.toBeInTheDocument();
  });
});

describe("DayPlan · places from outside the search radius", () => {
  /**
   * A rare kind of food in a fixed radius: one western place within reach and
   * three just outside it. The server sends the second group in its own field
   * precisely so this screen cannot draw the two as one list — every row in it
   * is further away than the user asked for.
   */
  const BARAT_DEKAT: Place = {
    ...PELITA,
    id: "w1",
    name: "Barat Dekat",
    kind: "Western",
    km: 2.0,
    road_km: 2.0,
    minutes: 26,
    total_sen: 1800,
    share: 1800 / ROOM_SEN,
  };

  function further(id: string, name: string, km: number, sen: number): Place {
    return {
      ...PELITA,
      id,
      name,
      kind: "Western",
      km,
      road_km: km,
      travel_sen: 900,
      minutes: Math.round(km * 13) + 6,
      total_sen: sen,
      share: sen / ROOM_SEN,
    };
  }

  const JUST_PAST = further("w2", "Barat Jauh Satu", 5.1, 1900);
  const FURTHER_STILL = further("w3", "Barat Jauh Dua", 6.5, 2000);

  const THIN: DayPlanData = {
    ...RESPONSE,
    kind: "Western",
    nearby_count: 5,
    matching_count: 5,
    kind_count: 1,
    places: [BARAT_DEKAT],
    nearest_beyond_radius: [JUST_PAST, FURTHER_STILL],
  };

  function rowFor(name: string): HTMLElement {
    const row = Array.from(document.querySelectorAll<HTMLElement>(".place")).find(
      (each) => each.querySelector("b")?.textContent === name,
    );
    if (!row) throw new Error(`no row for ${name}`);
    return row;
  }

  it("shows them under their own heading rather than in the list", async () => {
    vi.mocked(api.get).mockResolvedValue(THIN);
    renderDayPlan();
    await screen.findByText("Barat Dekat");

    expect(screen.getByText("Further out")).toBeInTheDocument();
    expect(screen.getByText(/from outside the area I searched/i)).toBeInTheDocument();
    expect(screen.getByText(/further away than you asked for/i)).toBeInTheDocument();
    // And the list above still says how many actually fit nearby.
    expect(screen.getByText(/1 western place fit/i)).toBeInTheDocument();
  });

  it("marks every one of those rows on the row itself", async () => {
    vi.mocked(api.get).mockResolvedValue(THIN);
    renderDayPlan();
    await screen.findByText("Barat Jauh Satu");

    // The heading can be scrolled past. The badge and the tint cannot.
    expect(within(rowFor("Barat Jauh Satu")).getByText("Further")).toBeInTheDocument();
    expect(rowFor("Barat Jauh Satu").className).toContain("further");
    // And nothing of the sort on the place that really was in range.
    expect(within(rowFor("Barat Dekat")).queryByText("Further")).not.toBeInTheDocument();
    expect(rowFor("Barat Dekat").className).not.toContain("further");
  });

  it("puts the real distance for the longer journey on each of them", async () => {
    vi.mocked(api.get).mockResolvedValue(THIN);
    renderDayPlan();
    await screen.findByText("Barat Jauh Satu");

    expect(rowFor("Barat Jauh Satu").textContent).toContain("5.1 km");
    expect(rowFor("Barat Jauh Satu").textContent).toContain("RM19.00");
    expect(rowFor("Barat Jauh Dua").textContent).toContain("6.5 km");
  });

  it("says what the group still honours, so nothing reads as a filter dropped", async () => {
    vi.mocked(api.get).mockResolvedValue(THIN);
    renderDayPlan();
    await screen.findByText("Barat Jauh Satu");

    // Distance is the only thing relaxed: the kind and the ceiling both held.
    expect(
      screen.getByText(/still western, halal and under RM52\.97/i),
    ).toBeInTheDocument();
  });

  it("shows no such group when the list is not thin", async () => {
    vi.mocked(api.get).mockResolvedValue(RESPONSE);
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    expect(screen.queryByText("Further out")).not.toBeInTheDocument();
    expect(document.querySelector(".place.further")).toBeNull();
  });

  it("still says what emptied the list when nothing at all was in range", async () => {
    // The group is an addition to that answer, never a replacement for it: the
    // reason the list is empty is a fact the user still has to be told.
    vi.mocked(api.get).mockResolvedValue({
      ...THIN,
      nearby_count: 0,
      matching_count: 0,
      kind_count: 0,
      places: [],
      nearest_beyond_radius: [JUST_PAST],
    });
    renderDayPlan();
    await screen.findByText("Barat Jauh Satu");

    expect(screen.getByText(/Nothing within range of here/i)).toBeInTheDocument();
    expect(screen.getByText(/Nothing western nearby, so here is one more/i)).toBeInTheDocument();
  });

  it("tells the sheet of one of them what it is looking at", async () => {
    vi.mocked(api.get).mockResolvedValue(THIN);
    renderDayPlan();
    await screen.findByText("Barat Jauh Satu");

    const { sheet } = await openSheet("Barat Jauh Satu");
    expect(within(sheet).getByText(/outside the area I searched/i)).toBeInTheDocument();
    expect(within(sheet).getByText(/5\.1 km from where you are/i)).toBeInTheDocument();
    expect(within(sheet).getByText(/all for that longer trip/i)).toBeInTheDocument();
  });

  it("says nothing of the kind in the sheet of a place that was in range", async () => {
    vi.mocked(api.get).mockResolvedValue(THIN);
    renderDayPlan();
    await screen.findByText("Barat Dekat");

    const { sheet } = await openSheet("Barat Dekat");
    expect(within(sheet).queryByText(/outside the area I searched/i)).not.toBeInTheDocument();
  });

  it("adds one to today with the figures for the journey it really is", async () => {
    // The whole outing, priced on the longer trip, exactly as the row showed
    // it. A draft cheaper than the row would be a draft for a different place.
    vi.mocked(api.get).mockResolvedValue(THIN);
    renderDayPlan();
    await screen.findByText("Barat Jauh Satu");

    const { user, sheet } = await openSheet("Barat Jauh Satu");
    await user.click(within(sheet).getByRole("button", { name: /add to today/i }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/v1/day-plan/drafts", {
        name: "Barat Jauh Satu",
        total_sen: 1900,
        confidence: "high",
      }),
    );
  });
});
