/** Format the integer-sen amount received from the API for display only. */
export function fmt(sen: number): string {
  return (sen / 100).toLocaleString("en-MY", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

const RINGGIT = /^(\d+)(?:\.(\d{1,2}))?$/;

/**
 * A hand-typed ringgit amount as integer sen, or null when it is not one yet.
 *
 * Null, not a guess: "19." and "19.9" are what a half-typed RM19.90 looks like
 * on the way past, and either one submitted as a number would be the wrong
 * number. The caller keeps the entry until this says yes.
 *
 * The digits are read as digits and never divided, so no float holds money on
 * its way to the wire — `parseFloat("19.90") * 100` is 1989.9999999999998.
 */
export function parseSen(input: string): number | null {
  const typed = input.trim().replace(/^RM\s*/i, "").replace(/,/g, "");
  const match = RINGGIT.exec(typed);
  if (!match) return null;
  const sen = Number(match[1]) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
  // Nothing on a ledger costs nothing, and the API refuses it either way.
  return sen > 0 ? sen : null;
}

/** Like parseSen, but for fields such as already-saved money where zero is valid. */
export function parseNonNegativeSen(input: string): number | null {
  const typed = input.trim().replace(/^RM\s*/i, "").replace(/,/g, "");
  const match = RINGGIT.exec(typed);
  if (!match) return null;
  const sen = Number(match[1]) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
  return Number.isSafeInteger(sen) && sen >= 0 ? sen : null;
}

/** The plain editable form of an amount: no grouping, always two decimals. */
export function toRinggitInput(sen: number): string {
  const sign = sen < 0 ? "-" : "";
  const absolute = Math.abs(sen);
  return `${sign}${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, "0")}`;
}
