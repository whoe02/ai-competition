// Every figure Kira shows is settled in KL time on the server. The greeting and
// the meal she offers to plan are the only clock-dependent things the client
// decides for itself, so they read the same zone rather than the device's.
const KL = "Asia/Kuala_Lumpur";

const KL_HOUR = new Intl.DateTimeFormat("en-GB", {
  timeZone: KL,
  hour: "2-digit",
  hour12: false,
});

/** The hour in Kuala Lumpur, 0–23, wherever the device happens to be. */
export function klHour(now: Date = new Date()): number {
  // "24" is a legal en-GB rendering of midnight; the day starts at 0 for us.
  return Number(KL_HOUR.format(now)) % 24;
}

export function greeting(now: Date = new Date()): string {
  const hour = klHour(now);
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

/**
 * The meal the Plan screen would be looking for right now, or null outside the
 * hours when offering to find one is useful. Kira names the meal because the
 * planner really does search for places to eat — she does not name a place, a
 * route, or an appointment, because she knows none of those from this screen.
 */
export function mealNow(now: Date = new Date()): "Breakfast" | "Lunch" | "Dinner" | null {
  const hour = klHour(now);
  if (hour >= 6 && hour < 11) return "Breakfast";
  if (hour >= 11 && hour < 15) return "Lunch";
  if (hour >= 17 && hour < 21) return "Dinner";
  return null;
}
