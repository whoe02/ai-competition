import { describe, expect, it } from "vitest";

import { fmt, parseNonNegativeSen, parseSen, toRinggitInput } from "./money";

describe("fmt", () => {
  it("formats sen as grouped ringgit", () => {
    expect(fmt(418040)).toBe("4,180.40");
  });

  it("always shows two decimals", () => {
    expect(fmt(5)).toBe("0.05");
    expect(fmt(100)).toBe("1.00");
  });

  it("formats the demo safe-to-spend", () => {
    expect(fmt(5297)).toBe("52.97");
  });

  it("handles zero", () => {
    expect(fmt(0)).toBe("0.00");
  });

  it("handles negatives", () => {
    expect(fmt(-1890)).toBe("-18.90");
  });
});

describe("parseSen", () => {
  it("reads ringgit and sen as integer sen", () => {
    expect(parseSen("19.90")).toBe(1990);
    expect(parseSen("14")).toBe(1400);
    expect(parseSen("0.05")).toBe(5);
  });

  it("reads the amounts a float would round wrong", () => {
    // parseFloat("19.90") * 100 is 1989.9999999999998.
    expect(parseSen("19.90")).toBe(1990);
    expect(parseSen("1.10")).toBe(110);
    expect(parseSen("4180.40")).toBe(418040);
  });

  it("takes a single decimal as tens of sen", () => {
    expect(parseSen("19.9")).toBe(1990);
  });

  it("tolerates the RM, grouping and stray spaces a person types", () => {
    expect(parseSen(" RM 1,234.50 ")).toBe(123450);
  });

  it("refuses a half-typed amount rather than guessing at it", () => {
    expect(parseSen("19.")).toBeNull();
    expect(parseSen(".9")).toBeNull();
    expect(parseSen("")).toBeNull();
  });

  it("refuses what is not an amount", () => {
    expect(parseSen("nineteen ninety")).toBeNull();
    expect(parseSen("19.905")).toBeNull();
    expect(parseSen("1e3")).toBeNull();
  });

  it("refuses nothing and less than nothing", () => {
    expect(parseSen("0")).toBeNull();
    expect(parseSen("0.00")).toBeNull();
    expect(parseSen("-19.90")).toBeNull();
  });

  it("round-trips what the editable form shows", () => {
    expect(parseSen(toRinggitInput(1400))).toBe(1400);
    expect(toRinggitInput(1990)).toBe("19.90");
    expect(toRinggitInput(5)).toBe("0.05");
  });
});

describe("parseNonNegativeSen", () => {
  it("allows an empty goal's zero balance while still using integer sen", () => {
    expect(parseNonNegativeSen("0.00")).toBe(0);
    expect(parseNonNegativeSen("8,000.25")).toBe(800025);
    expect(parseNonNegativeSen("-1.00")).toBeNull();
  });
});
