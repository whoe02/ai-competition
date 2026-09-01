/**
 * The order the day plan's list is read in, and when the leader has earned a
 * badge.
 *
 * All of this runs on the client, over the whole list the API sent. That is a
 * decision rather than a convenience: `GET /v1/day-plan/places` returns every
 * place under the ceiling untruncated, so re-ordering here can only ever
 * rearrange rows the user already has. A server-side `sort` parameter would
 * matter if the list arrived cut — the Butler's `build_day_plan` tool does take
 * `found.places[:5]`, and a cheapest-five re-sorted by time would be five
 * cheap places in a new order rather than the quickest five — but that
 * truncation is inside the tool, downstream of the service, and nothing on this
 * path shares it. So: client-side, no round trip per toggle, and the figures
 * cannot change because nothing is re-fetched to change them.
 *
 * The blend below is a preference about ordering. It is never a claim about the
 * world, and it produces nothing that reaches the screen except a sequence.
 */

import type { Place } from "@kira/contracts";

/** How the user would travel there. The API's own three modes. */
export type TravelMode = "walk" | "transit" | "ride";

export type SortId = "balanced" | "cheapest" | "closest";

export type SortOption = {
  label: string;
  /** Said on screen under the control, so the order is never a mystery. */
  explains: string;
};

/**
 * Visible on the screen, not tuned behind it. A hidden weighting that puts a
 * two-hour walk at the top of the list is a thing the user can neither see nor
 * argue with; a named order they chose is one they can change.
 */
export const SORTS: Record<SortId, SortOption> = {
  balanced: {
    label: "Balanced",
    explains:
      "Cost and travel time count equally, each measured against the rest of this list. "
      + "Only the order changes — every ringgit and minute below is the real one.",
  },
  cheapest: {
    label: "Cheapest",
    explains: "Total outing first — meal and travel together — however far away it is.",
  },
  closest: {
    label: "Closest",
    explains: "Shortest journey first, door to door, whatever it costs when you get there.",
  },
};

export const SORT_IDS: readonly SortId[] = ["balanced", "cheapest", "closest"];

/**
 * How long a one-way journey can run before the outing stops being a trip out
 * for a meal, per mode. Above this the leader gets no badge, whatever the sort
 * put it there for: a 109-minute walk is the cheapest thing on the list and
 * nobody's best fit, and stapling "BEST FIT" to two hours on foot is the badge
 * making a claim about the user's day that it cannot support.
 *
 * `minutes` is door to door one way — waiting, travelling, and a six-minute
 * constant the service adds — so double it for the round trip.
 *
 * * **walk 30.** Habitual walking for daily errands runs 10–15 minutes; 30 is
 *   already twice that and an hour on foot for one meal. Past it, the walk is
 *   the outing.
 * * **transit 45.** A rail leg is spent sitting and the wait is unavoidable, so
 *   the tolerable figure is genuinely higher than on foot — but 45 minutes each
 *   way is a commute, and lunch is not one.
 * * **ride 30.** A ride is charged by the kilometre, so a long one is usually
 *   priced off the list before it is timed off it. The threshold is here for
 *   the case where it is not — cheap traffic-bound distance.
 *
 * These bound the *badge*, never the list. A place past the threshold is still
 * shown, still priced, still addable; it simply does not get told it is the
 * best thing on offer.
 */
export const REASONABLE_MINUTES: Record<TravelMode, number> = {
  walk: 30,
  transit: 45,
  ride: 30,
};

type Bounds = {
  minSen: number;
  maxSen: number;
  minMinutes: number;
  maxMinutes: number;
};

/**
 * Balanced compares two places with two units, so a difference of 1 in the
 * blend is a difference of nothing in particular — floats only. Cost and time
 * on their own are integers and never come near this.
 */
const TIE = 1e-9;

function boundsOf(places: readonly Place[]): Bounds {
  const sen = places.map((place) => place.total_sen);
  const minutes = places.map((place) => place.minutes);
  return {
    minSen: Math.min(...sen),
    maxSen: Math.max(...sen),
    minMinutes: Math.min(...minutes),
    maxMinutes: Math.max(...minutes),
  };
}

/**
 * Where a value sits between the smallest and largest in this list: 0 for the
 * best on that axis, 1 for the worst.
 *
 * A list with no spread on an axis — every place the same price, or a single
 * place — has nowhere to place anything, so everything scores 0 there and the
 * other axis decides on its own. Dividing by a zero range instead would give
 * NaN, and NaN in a comparator sorts at random.
 */
function normalise(value: number, min: number, max: number): number {
  return max === min ? 0 : (value - min) / (max - min);
}

/**
 * Half the cost's standing in this list, half the travel time's. Lower is
 * better; the result is between 0 and 1 and means nothing outside this list.
 *
 * Deliberately not a value of time in ringgit. Pricing a minute would mean
 * inventing a rate the user never gave, and the moment a rate exists somebody
 * will want to show the total it implies — a made-up figure sitting beside the
 * real ones. Normalising keeps the blend unitless: it can decide an order and
 * nothing else, so no number on screen can be computed from it.
 */
export function balancedScore(place: Place, places: readonly Place[]): number {
  const bounds = boundsOf(places);
  return blend(place, bounds);
}

function blend(place: Place, bounds: Bounds): number {
  return (
    0.5 * normalise(place.total_sen, bounds.minSen, bounds.maxSen)
    + 0.5 * normalise(place.minutes, bounds.minMinutes, bounds.maxMinutes)
  );
}

/** What the chosen sort is ordering on, lower being better. */
function axisValue(place: Place, sort: SortId, bounds: Bounds): number {
  switch (sort) {
    case "cheapest":
      return place.total_sen;
    case "closest":
      return place.minutes;
    case "balanced":
      return blend(place, bounds);
  }
}

/**
 * Tagged before inferred, as a number to sort on: 0 for a place the map really
 * does record as this food, 1 for one a model only believes serves it.
 *
 * It settles ties and nothing else. Where the axis has already separated two
 * places this never runs, so a cheap belief still beats a dear tag — re-ordering
 * the list on something the user cannot see, beside figures they can, is exactly
 * what a sort control must not do. Where the axis has nothing left to say, one
 * of the two is known and the other is guessed, and the known one goes first.
 */
function believedLast(place: Place): number {
  return place.match_basis === "inferred" ? 1 : 0;
}

/** The list in the chosen order. A copy — the query cache's array is not ours. */
export function sortPlaces(places: readonly Place[], sort: SortId): Place[] {
  if (places.length === 0) return [];
  const bounds = boundsOf(places);
  return [...places].sort((a, b) => {
    const byAxis = axisValue(a, sort, bounds) - axisValue(b, sort, bounds);
    if (Math.abs(byAxis) > TIE) return byAxis;
    // Ties break the same way on every axis — cheaper first, then the tag ahead
    // of the belief, then by id — so the rows below the leader do not reshuffle
    // between renders of the same list, and two identical outings always land
    // the same way round.
    return (
      a.total_sen - b.total_sen
      || believedLast(a) - believedLast(b)
      || a.id.localeCompare(b.id)
    );
  });
}

/**
 * The id of the row that has earned the "Best fit" badge, or null when none
 * has. Takes the list already in order, as `sortPlaces` returned it.
 *
 * The badge used to mean "first row", which is not a fact about anything: some
 * row is always first. Three things have to hold before it is a claim worth
 * making.
 *
 * 1. **It fits.** A place over today's room does not fit today, and a row
 *    badged "OVER" and "BEST FIT" at once contradicts itself on screen. On a
 *    spent-out day every place is over, and nothing is badged — which is the
 *    honest answer to "what fits today" when the answer is nothing.
 * 2. **The journey is reasonable for the mode.** See `REASONABLE_MINUTES`.
 * 3. **It actually won.** Strictly better than the runner-up on the axis being
 *    sorted by, not merely first among equals. Two places at the same price
 *    under Cheapest are equally the cheapest, and picking one of them to
 *    crown is the arbitrary choice the old badge was making every time.
 */
export function bestFitId(
  ordered: readonly Place[],
  sort: SortId,
  mode: TravelMode,
): string | null {
  const leader = ordered[0];
  if (!leader) return null;
  if (leader.band === "over") return null;
  if (leader.minutes > REASONABLE_MINUTES[mode]) return null;

  const runnerUp = ordered[1];
  if (runnerUp) {
    const bounds = boundsOf(ordered);
    const margin = axisValue(runnerUp, sort, bounds) - axisValue(leader, sort, bounds);
    if (margin <= TIE) return null;
  }
  return leader.id;
}
