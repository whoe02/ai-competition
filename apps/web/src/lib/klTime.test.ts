import { describe, expect, it } from "vitest";

import { greeting, klHour, mealNow } from "./klTime";

// 03:00Z is 11:00 in KL. A device in London would call this the morning.
const KL_ELEVEN = new Date("2026-09-07T03:00:00Z");
const KL_MIDNIGHT = new Date("2026-09-06T16:00:00Z");
const KL_HALF_SEVEN_PM = new Date("2026-09-07T11:30:00Z");

describe("klTime", () => {
  it("reads the hour in KL, not on the device", () => {
    expect(klHour(KL_ELEVEN)).toBe(11);
    expect(klHour(KL_HALF_SEVEN_PM)).toBe(19);
  });

  it("counts midnight in KL as hour zero", () => {
    expect(klHour(KL_MIDNIGHT)).toBe(0);
  });

  it("greets by the KL clock", () => {
    expect(greeting(KL_ELEVEN)).toBe("Good morning");
    expect(greeting(KL_HALF_SEVEN_PM)).toBe("Good evening");
    expect(greeting(KL_MIDNIGHT)).toBe("Good morning"); // hour 0 is still the morning
  });

  it("names the meal the planner would be looking for", () => {
    expect(mealNow(new Date("2026-09-07T00:30:00Z"))).toBe("Breakfast"); // 08:30 KL
    expect(mealNow(KL_ELEVEN)).toBe("Lunch");
    expect(mealNow(KL_HALF_SEVEN_PM)).toBe("Dinner");
  });

  it("offers no meal outside the hours when one would be useful", () => {
    expect(mealNow(KL_MIDNIGHT)).toBeNull();
    expect(mealNow(new Date("2026-09-07T08:00:00Z"))).toBeNull(); // 16:00 KL
  });
});
