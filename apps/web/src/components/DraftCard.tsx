import { useState, type CSSProperties, type ReactNode } from "react";

import type { Transaction } from "@kira/contracts";

import { fmt, parseSen, toRinggitInput } from "../lib/money";
import { SourceIcon, sourceLabel } from "./TxnRow";

type DraftCardProps = {
  draft: Transaction;
  onConfirm: (id: string) => void;
  onDiscard: (id: string) => void;
  /** Resolves when the correction is saved, and rejects when it is not. */
  onCorrect: (id: string, amountSen: number) => void | Promise<unknown>;
  settling: boolean;
  correcting: boolean;
};

const ROW: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: 10,
  padding: "10px 12px",
  background: "rgba(15,28,26,.04)",
  borderRadius: 11,
  fontSize: 13,
};

function DetailRow({
  label,
  index,
  children,
}: {
  label: string;
  index: number;
  children: ReactNode;
}) {
  return (
    <div style={{ ...ROW, animation: `rowIn .45s var(--spring) ${index * 60}ms both` }}>
      <span style={{ color: "var(--muted)", flex: "none" }}>{label}</span>
      {children}
    </div>
  );
}

/** A read Kira is not yet sure enough to count. Every field is visible before it does. */
export function DraftCard({
  draft,
  onConfirm,
  onDiscard,
  onCorrect,
  settling,
  correcting,
}: DraftCardProps) {
  const income = draft.direction === "income";
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [typed, setTyped] = useState(() => toRinggitInput(draft.amount_sen));
  const [failed, setFailed] = useState(false);
  // Null the whole time the entry is half-typed, so nothing can submit "19."
  // as RM19.00 on its way to RM19.90.
  const sen = parseSen(typed);
  const busy = settling || correcting;
  const hintId = `amount-hint-${draft.id}`;

  const startCorrecting = () => {
    setTyped(toRinggitInput(draft.amount_sen));
    setFailed(false);
    setEditing(true);
  };

  const stopCorrecting = () => {
    setFailed(false);
    setEditing(false);
  };

  /**
   * Closes on the answer, never on the tap.
   *
   * A correction that never reached the server must not leave the entry looking
   * like it did. The read stands until it is overwritten, so closing here would
   * put the misheard figure back on a card the user believes they have fixed —
   * and the next Confirm would spend it. The typed figure stays where it is,
   * with the failure said beside it, until it saves or the user gives up on it.
   */
  const save = async () => {
    if (sen === null) return;
    try {
      await onCorrect(draft.id, sen);
      setFailed(false);
      setEditing(false);
    } catch {
      setFailed(true);
    }
  };

  return (
    <div className="draft">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <span className="tag" style={{ color: "var(--brass)" }}>
            <SourceIcon source={draft.source} size={11} /> {sourceLabel(draft.source)}
          </span>
          <b style={{ display: "block", fontSize: 15.5, letterSpacing: "-.02em", marginTop: 5 }}>
            {draft.merchant}
          </b>
          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
            {income ? (draft.income_type === "salary" ? "Salary income" : "Other income") : draft.category_label}
          </span>
        </div>
        <div className="money" style={{ fontSize: 20 }}>RM{fmt(draft.amount_sen)}</div>
      </div>

      {/* No confidence means no machine stands behind the figure — either it was
          typed, or it has been corrected. Showing a full bar and "100% sure"
          would put a reader's voice behind the user's own number. */}
      {draft.confidence === null ? (
        <p className="voice" style={{ margin: "9px 0 0", fontSize: 13, color: "var(--muted)" }}>
          Your figure, not a read. {draft.note}
        </p>
      ) : (
        <>
          <div className="conf">
            <i style={{ width: `${draft.confidence}%` }} />
          </div>
          <p className="voice" style={{ margin: "9px 0 0", fontSize: 13, color: "var(--muted)" }}>
            {/* A scan is sure of what a slip said; a plan is only sure of what
                a meal is likely to cost, and nothing has been read at all. Bare
                "70% sure" on a plan would claim the stronger of the two. */}
            {draft.confidence}% sure{draft.source === "plan" ? " of the price" : ""}. {draft.note}
          </p>
        </>
      )}

      {open && (
        <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
          <DetailRow label="Merchant" index={0}>
            <b>{draft.merchant}</b>
          </DetailRow>

          <DetailRow label="Amount" index={1}>
            {editing ? (
              <span style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <span style={{ color: "var(--muted)" }}>RM</span>
                  <input
                    className="amt-input"
                    value={typed}
                    inputMode="decimal"
                    autoFocus
                    aria-label="Amount in ringgit"
                    aria-invalid={sen === null}
                    aria-describedby={hintId}
                    onChange={(event) => setTyped(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void save();
                    }}
                  />
                </span>
                <button
                  className="btn btn-primary btn-sm"
                  disabled={sen === null || busy}
                  onClick={() => void save()}
                >
                  {failed ? "Try again" : "Save"}
                </button>
                <button className="btn btn-ghost btn-sm" onClick={stopCorrecting}>
                  Cancel
                </button>
              </span>
            ) : (
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <b>RM{fmt(draft.amount_sen)}</b>
                <button
                  className="btn btn-ghost btn-sm"
                  disabled={busy}
                  onClick={startCorrecting}
                >
                  Correct
                </button>
              </span>
            )}
          </DetailRow>

          {editing && (
            <p
              id={hintId}
              role={failed ? "status" : undefined}
              style={{
                margin: "-2px 2px 0",
                fontSize: 12,
                color: failed ? "var(--clay)" : "var(--muted)",
                textAlign: "right",
                lineHeight: 1.5,
              }}
            >
              {/* Named as still-unsaved rather than as a generic failure: what
                  the user needs to know is not that a request failed but that
                  the amount on this draft is still the one that was read, and
                  that confirming now would spend that figure. */}
              {failed
                ? "That didn't save, so this draft still says RM"
                  + fmt(draft.amount_sen)
                  + ". Your figure is still here — try again before you confirm it."
                : sen === null
                  ? "Ringgit and sen, like 19.90."
                  : "Saving replaces what was read with your figure."}
            </p>
          )}

          <DetailRow label={income ? "Income type" : "Category"} index={2}>
            <b>{income ? (draft.income_type ?? "other") : draft.category}</b>
          </DetailRow>
          <DetailRow label="Date" index={3}>
            <b>{draft.occurred_on}</b>
          </DetailRow>
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <button
          className="btn btn-primary btn-sm"
          style={{ flex: 1 }}
          disabled={busy}
          onClick={() => onConfirm(draft.id)}
        >
          {income ? "Confirm income" : "Confirm"}
        </button>
        <button className="btn btn-line btn-sm" onClick={() => setOpen((shown) => !shown)}>
          {open ? "Close" : "Details"}
        </button>
        <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => onDiscard(draft.id)}>
          Discard
        </button>
      </div>
    </div>
  );
}
