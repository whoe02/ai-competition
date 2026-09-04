import { useId, useState } from "react";

import type { Category } from "@kira/contracts";

import { useCreateDraft } from "../api/hooks";
import { parseSen } from "../lib/money";
import { IcCheck } from "./Icons";

/** Which way the money went. Not a category — the two are opposite arithmetic. */
type Direction = "out" | "in";

/**
 * Where money in came from.
 *
 * The ledger only records two kinds — salary and everything else — because that
 * is the distinction forecasting needs. But "everything else" is not a thing
 * anyone earns: a part-time shift, an angpau and a refund are three different
 * answers to "why did my balance go up", and the one the user picked is kept as
 * the name on the row so the ledger still reads back the way they said it.
 */
type Source = {
  id: string;
  label: string;
  type: "salary" | "other";
  hint: string;
};

export const INCOME_SOURCES: Source[] = [
  { id: "salary", label: "Salary", type: "salary", hint: "Your regular pay" },
  { id: "part-time", label: "Part-time job", type: "other", hint: "Shifts, hourly work" },
  { id: "freelance", label: "Freelance or side gig", type: "other", hint: "Work you invoiced" },
  { id: "bonus", label: "Bonus or commission", type: "other", hint: "On top of your pay" },
  { id: "allowance", label: "Allowance", type: "other", hint: "Given to you regularly" },
  { id: "gift", label: "Gift or angpau", type: "other", hint: "Given, not earned" },
  { id: "refund", label: "Refund or reimbursement", type: "other", hint: "Money coming back" },
  { id: "rental", label: "Rent received", type: "other", hint: "From a room or a property" },
  { id: "investment", label: "Dividend or interest", type: "other", hint: "From what you hold" },
  { id: "sale", label: "Something you sold", type: "other", hint: "Second-hand, one-off" },
  { id: "other", label: "Something else", type: "other", hint: "Name it yourself" },
];

/** Today, in the device's own timezone. `toISOString` would be yesterday after 8pm here. */
function today(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/**
 * The whole entry, typed out by hand — either way the money went.
 *
 * Nothing is read, inferred or asked of a model here: what the user types is
 * what the draft says. That is the point of having it beside the Butler rather
 * than inside it — when you already know the figure, the fastest honest route
 * is to write it down, and a form cannot mishear you. It still lands as a
 * draft, because a draft is what the Activity screen knows how to check.
 */
export function ManualBody({
  onClose,
  categories,
}: {
  onClose: () => void;
  categories?: Category[];
}) {
  const fieldId = useId();
  const [direction, setDirection] = useState<Direction>("out");
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [occurredOn, setOccurredOn] = useState(today);
  const [category, setCategory] = useState("uncategorised");
  const [sourceId, setSourceId] = useState("salary");
  const draft = useCreateDraft();

  const income = direction === "in";
  const source = INCOME_SOURCES.find((option) => option.id === sourceId) ?? INCOME_SOURCES[0]!;
  // Every other source names itself; "Something else" names nothing, so there
  // the row would land on the ledger called "Something else" forever.
  const needsName = income && source.id === "other";
  const sen = parseSen(amount);
  const merchant = income ? name.trim() || source.label : name.trim();
  const dated = occurredOn !== "";
  const ready = sen !== null && dated && (income ? !needsName || name.trim() !== "" : merchant !== "");

  // The button disables itself while the write is in flight; Enter does not, and
  // two of these is two rows on the ledger for one thing that happened once.
  const save = () => {
    if (sen === null || !ready || draft.isPending) return;
    draft.mutate(
      income
        ? {
            merchant,
            amount_sen: sen,
            occurred_on: occurredOn,
            category: "income",
            source: "manual",
            note: needsName ? "" : `${source.label}.`,
            direction: "income",
            income_type: source.type,
          }
        : {
            merchant,
            amount_sen: sen,
            occurred_on: occurredOn,
            category,
            source: "manual",
            note: "",
            direction: "expense",
          },
      { onSuccess: onClose },
    );
  };

  return (
    <>
      <div className="sheet-head">
        <div>
          <p className="eyebrow on-ink" style={{ margin: 0 }}>
            By hand
          </p>
          <h2 style={{ margin: "5px 0 0", fontSize: 20, fontWeight: 800, letterSpacing: "-.03em" }}>
            {income ? "What came in, and where from" : "What you spent it on"}
          </h2>
        </div>
      </div>

      <div className="entry-seg" role="radiogroup" aria-label="Which way the money went">
        {([
          { id: "out", label: "Spent" },
          { id: "in", label: "Received" },
        ] as const).map(({ id, label }) => (
          <button
            key={id}
            role="radio"
            aria-checked={direction === id}
            aria-label={label}
            className={direction === id ? "on" : ""}
            onClick={() => setDirection(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {income ? (
        <>
          <label className="entry-label" htmlFor={`${fieldId}-source`}>
            Where it came from
          </label>
          <select
            id={`${fieldId}-source`}
            className="entry-in"
            value={sourceId}
            onChange={(event) => setSourceId(event.target.value)}
          >
            {INCOME_SOURCES.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
          <p className="entry-hint">
            {source.hint}
            {source.type === "salary" ? " · counted as salary" : " · counted as other income"}
          </p>

          <label className="entry-label" htmlFor={`${fieldId}-name`}>
            {needsName ? "What was it?" : "Who paid you (optional)"}
          </label>
          <input
            id={`${fieldId}-name`}
            className="entry-in"
            value={name}
            placeholder={needsName ? "Say it in your own words" : source.label}
            onChange={(event) => setName(event.target.value)}
          />
        </>
      ) : (
        <>
          <label className="entry-label" htmlFor={`${fieldId}-name`}>
            Where it went
          </label>
          <input
            id={`${fieldId}-name`}
            className="entry-in"
            value={name}
            placeholder="Nasi Kandar Pelita, Grab, Tesco…"
            onChange={(event) => setName(event.target.value)}
          />

          {/* Only when the vocabulary is actually to hand. A hardcoded copy of
              the server's list would go stale, and a free-text category is how
              the same spending ends up under Food, food and Makan. */}
          {categories && categories.length > 0 && (
            <>
              <label className="entry-label" htmlFor={`${fieldId}-category`}>
                Category
              </label>
              <select
                id={`${fieldId}-category`}
                className="entry-in"
                value={category}
                onChange={(event) => setCategory(event.target.value)}
              >
                {categories.map((option) => (
                  <option key={option.slug} value={option.slug}>
                    {option.label}
                  </option>
                ))}
              </select>
            </>
          )}
        </>
      )}

      <label className="entry-label" htmlFor={`${fieldId}-amount`}>
        How much
      </label>
      <div className="entry-money">
        <span>RM</span>
        <input
          id={`${fieldId}-amount`}
          className="entry-in"
          inputMode="decimal"
          placeholder="0.00"
          value={amount}
          aria-invalid={amount !== "" && sen === null}
          onChange={(event) => setAmount(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") save();
          }}
        />
      </div>

      <label className="entry-label" htmlFor={`${fieldId}-date`}>
        {income ? "When it arrived" : "When"}
      </label>
      <input
        id={`${fieldId}-date`}
        className="entry-in"
        type="date"
        value={occurredOn}
        onChange={(event) => setOccurredOn(event.target.value)}
      />

      <p className="sheet-note" role={draft.isError ? "status" : undefined}>
        {draft.isError
          ? "That didn't save, so nothing was added. Your figures are still here — try again."
          : income
            ? "Income waits for you in Activity like any other draft. Your balance only moves once you confirm it."
            : "This waits for you in Activity like anything else you tell me. Nothing is counted until you confirm it."}
      </p>

      <div style={{ display: "flex", gap: 9, marginTop: 16 }}>
        <button className="btn btn-sm btn-ghost" style={{ flex: 1 }} onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn btn-brass btn-sm"
          style={{ flex: 1 }}
          disabled={!ready || draft.isPending}
          onClick={save}
        >
          {draft.isPending
            ? "Saving…"
            : draft.isError
              ? "Try again"
              : income
                ? "Add income"
                : "Add spending"}{" "}
          <IcCheck size={14} />
        </button>
      </div>
    </>
  );
}
