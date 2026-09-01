import { describe, expect, it } from "vitest";

import type { Place } from "@kira/contracts";

import { balancedScore, bestFitId, REASONABLE_MINUTES, sortPlaces } from "./placeSort";

const ROOM_SEN = 5297;

function place(
  id: string,
  totalSen: number,
  minutes: number,
  over = false,
  matchBasis: Place["match_basis"] = null,
): Place {
  return {
    id,
    name: id,
    kind: "Cafe",
    match_basis: matchBasis,
    address: "Kuala Lumpur",
    lat: 3.1577,
    lng: 101.712,
    km: 1,
    road_km: 1,
    distance_basis: "road",
    travel_sen: 0,
    minutes,
    total_sen: totalSen,
    share: totalSen / ROOM_SEN,
    band: over ? "over" : "ok",
    confidence: "high",
    halal: true,
    note: "",
  };
}

/**
 * The tension the whole control exists for: the cheapest thing on the list is
 * a two-hour walk, the nearest is nearly twice the price, and the one a person
 * would actually pick is neither.
 */
const FAR = place("far", 1100, 109);
const NEAR = place("near", 1800, 8);
const MIDDLE = place("middle", 1300, 25);
const TENSION = [FAR, NEAR, MIDDLE];

function ids(places: readonly Place[]): string[] {
  return places.map((each) => each.id);
}

describe("sortPlaces", () => {
  it("puts the cheapest first under Cheapest, however far it is", () => {
    expect(ids(sortPlaces(TENSION, "cheapest"))).toEqual(["far", "middle", "near"]);
  });

  it("puts the shortest journey first under Closest, whatever it costs", () => {
    expect(ids(sortPlaces(TENSION, "closest"))).toEqual(["near", "middle", "far"]);
  });

  it("puts the sensible one first under Balanced, where the other two pick an extreme", () => {
    // Neither extreme wins: each is best on one axis and worst on the other, so
    // both land at 0.5 and the middle beats them at 0.23.
    expect(ids(sortPlaces(TENSION, "balanced"))).toEqual(["middle", "far", "near"]);
  });

  it("weights cost and time evenly, and states the blend in no unit at all", () => {
    // 0.5 · (200/700) + 0.5 · (17/101). Not ringgit, not minutes — a standing
    // in this list, which is all it is ever allowed to be.
    expect(balancedScore(MIDDLE, TENSION)).toBeCloseTo(0.5 * (200 / 700) + 0.5 * (17 / 101), 10);
    expect(balancedScore(FAR, TENSION)).toBeCloseTo(0.5, 10);
    expect(balancedScore(NEAR, TENSION)).toBeCloseTo(0.5, 10);
  });

  it("does not touch the list it was handed", () => {
    const original = [...TENSION];
    sortPlaces(TENSION, "closest");
    expect(TENSION).toEqual(original);
  });

  it("survives a list with no spread to normalise against", () => {
    // Every place identical: the range is nil on both axes, and a division by
    // it would put NaN in the comparator and shuffle the list at random.
    const flat = [place("a", 1200, 20), place("b", 1200, 20), place("c", 1200, 20)];
    expect(ids(sortPlaces(flat, "balanced"))).toEqual(["a", "b", "c"]);
  });

  it("handles an empty list and a single place", () => {
    expect(sortPlaces([], "balanced")).toEqual([]);
    expect(ids(sortPlaces([FAR], "balanced"))).toEqual(["far"]);
  });

  /**
   * A kind filter matches the map's own tags and also what a model believes a
   * place serves beyond them, so the list holds two different sorts of claim.
   * Where the axis has run out of things to say between two of them, the one
   * the map records goes first.
   */
  describe("a tag against a belief", () => {
    // "a" sorts ahead of "b", so the belief wins on the old id tie-break and
    // the new rule is the only thing that can reverse it.
    const GUESSED = place("a", 1600, 14, false, "inferred");
    const RECORDED = place("b", 1600, 14, false, "tagged");

    it("puts the tag first where the axis is level, on every sort", () => {
      const orders = (["balanced", "cheapest", "closest"] as const).map((sort) =>
        ids(sortPlaces([GUESSED, RECORDED], sort)),
      );
      expect(orders).toEqual([["b", "a"], ["b", "a"], ["b", "a"]]);
    });

    it("leaves a cheaper belief in front of a dearer tag", () => {
      // The tie-break decides ties. A basis that outranked money would be
      // re-ordering the list on something the user cannot see, beside figures
      // they can.
      const dearer = place("b", 2400, 14, false, "tagged");
      expect(ids(sortPlaces([dearer, GUESSED], "cheapest"))).toEqual(["a", "b"]);
    });

    it("leaves a list nobody narrowed exactly as it was", () => {
      // No kind was asked for, so nothing matched anything and every basis is
      // null. The old ordering has to survive that untouched.
      const flat = [place("b", 1200, 20), place("a", 1200, 20)];
      expect(ids(sortPlaces(flat, "balanced"))).toEqual(["a", "b"]);
    });

    it("badges neither of them, because neither won", () => {
      // The basis settles who is drawn first. It is not a victory, and "Best
      // fit" is a claim about winning on the axis being sorted by.
      const ordered = sortPlaces([GUESSED, RECORDED], "cheapest");
      expect(bestFitId(ordered, "cheapest", "walk")).toBeNull();
    });
  });
});

describe("bestFitId", () => {
  it("badges a leader that genuinely won and is a reasonable trip", () => {
    const ordered = sortPlaces(TENSION, "balanced");
    expect(bestFitId(ordered, "balanced", "walk")).toBe("middle");
  });

  it("withholds the badge from a two-hour walk, however cheap it is", () => {
    // The bug this exists for: RM11.00 at 109 minutes on foot topped the list
    // and was told it was the best fit for the day.
    const ordered = sortPlaces(TENSION, "cheapest");
    expect(ids(ordered)[0]).toBe("far");
    expect(bestFitId(ordered, "cheapest", "walk")).toBeNull();
  });

  it("lets the same journey be badged in a mode that can take it", () => {
    const forty = [place("long", 1100, 40), place("other", 1900, 55)];
    expect(REASONABLE_MINUTES.walk).toBeLessThan(40);
    expect(REASONABLE_MINUTES.transit).toBeGreaterThanOrEqual(40);
    expect(bestFitId(sortPlaces(forty, "cheapest"), "cheapest", "walk")).toBeNull();
    expect(bestFitId(sortPlaces(forty, "cheapest"), "cheapest", "transit")).toBe("long");
  });

  it("badges a journey exactly on the threshold, and not one minute past it", () => {
    const at = [place("at", 1100, REASONABLE_MINUTES.walk), place("far", 1900, 90)];
    const past = [place("past", 1100, REASONABLE_MINUTES.walk + 1), place("far", 1900, 90)];
    expect(bestFitId(sortPlaces(at, "cheapest"), "cheapest", "walk")).toBe("at");
    expect(bestFitId(sortPlaces(past, "cheapest"), "cheapest", "walk")).toBeNull();
  });

  it("withholds the badge from a leader that is first among equals", () => {
    // Two places at the same price are equally the cheapest. Crowning one of
    // them is the arbitrary pick the old "row one" badge made every time.
    const tied = [place("a", 1200, 12), place("b", 1200, 26)];
    expect(bestFitId(sortPlaces(tied, "cheapest"), "cheapest", "walk")).toBeNull();
    // On the axis they are not tied on, one of them really does win.
    expect(bestFitId(sortPlaces(tied, "closest"), "closest", "walk")).toBe("a");
  });

  it("withholds the badge from a place that does not fit today", () => {
    // "Over" and "Best fit" on the same row contradict each other on screen,
    // and a spent-out day makes every place over — where nothing fits, the
    // honest answer is no badge at all.
    const overs = [place("a", 9800, 12, true), place("b", 12000, 30, true)];
    expect(bestFitId(sortPlaces(overs, "cheapest"), "cheapest", "walk")).toBeNull();
  });

  it("badges the only place on a list of one, when it has earned it", () => {
    expect(bestFitId([place("only", 1200, 12)], "balanced", "walk")).toBe("only");
    expect(bestFitId([place("only", 1200, 90)], "balanced", "walk")).toBeNull();
    expect(bestFitId([], "balanced", "walk")).toBeNull();
  });
});
