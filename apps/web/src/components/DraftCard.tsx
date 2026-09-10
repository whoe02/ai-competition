import { useState, type CSSProperties, type ReactNode } from "react";

import type { Category, Transaction, TransactionCorrection } from "@kira/contracts";

import { fmt, parseSen, toRinggitInput } from "../lib/money";
import { SourceIcon, sourceLabel } from "./TxnRow";

export type DraftCorrection = TransactionCorrection;

type DraftCardProps = {
  draft: Transaction;
  onConfirm: (id: string) => void;
  onDiscard: (id: string) => void;
  /** Resolves when the correction is saved, and rejects when it is not. */
  onCorrect: (id: string, correction: DraftCorrection) => void | Promise<unknown>;
  categories?: Category[];
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
  categories,
  settling,
  correcting,
}: DraftCardProps) {
  const income = draft.direction === "income";
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [typed, setTyped] = useState(() => toRinggitInput(draft.amount_sen));
  const [merchant, setMerchant] = useState(draft.merchant);
  const [category, setCategory] = useState(draft.category);
  const [occurredOn, setOccurredOn] = useState(draft.occurred_on);
  const [note, setNote] = useState(draft.note);
  const [failed, setFailed] = useState(false);
  // Null the whole time the entry is half-typed, so nothing can submit "19."
  // as RM19.00 on its way to RM19.90.
  const sen = parseSen(typed);
  const busy = settling || correcting;
  const hintId = `edit-hint-${draft.id}`;
  const categoryOptions = categories?.length
    ? categories
    : [{ slug: draft.category, label: draft.category_label }];

  const startCorrecting = () => {
    setTyped(toRinggitInput(draft.amount_sen));
    setMerchant(draft.merchant);
    setCategory(draft.category);
    setOccurredOn(draft.occurred_on);
    setNote(draft.note);
    setFailed(false);
    setEditing(true);
  };

  const stopCorrecting = () => {
    setFailed(false);
    setEditing(false);
    setOpen(false);
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
    if (sen === null || !merchant.trim() || !category || !occurredOn) return;
    const correction: DraftCorrection = {
      ...(merchant.trim() !== draft.merchant ? { merchant: merchant.trim() } : {}),
      ...(sen !== draft.amount_sen ? { amount_sen: sen } : {}),
      ...(category !== draft.category ? { category } : {}),
      ...(occurredOn !== draft.occurred_on ? { occurred_on: occurredOn } : {}),
      ...(note !== draft.note ? { note } : {}),
    };
    if (Object.keys(correction).length === 0) {
      stopCorrecting();
      return;
    }
    try {
      await onCorrect(draft.id, correction);
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
          <span className="tag" style={{ color: "var(--accent)" }}>
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
            {editing ? (
              <input
                className="amt-input draft-text-input"
                value={merchant}
                aria-label="Merchant"
                aria-invalid={!merchant.trim()}
                onChange={(event) => setMerchant(event.target.value)}
              />
            ) : <b>{draft.merchant}</b>}
          </DetailRow>

          <DetailRow label="Amount" index={1}>
            {editing ? <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
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
            </span> : <b>RM{fmt(draft.amount_sen)}</b>}
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
              {failed
                ? "That didn't save. Your edits are still here — try again before you confirm this draft."
                : sen === null
                  ? "Ringgit and sen, like 19.90."
                  : !merchant.trim()
                    ? "Add a merchant before saving."
                    : "Review every detail, then save the draft."}
            </p>
          )}

          <DetailRow label={income ? "Income type" : "Category"} index={2}>
            {editing && !income ? (
              <select className="amt-input draft-category-input" value={category} aria-label="Category" onChange={(event) => setCategory(event.target.value)}>
                {categoryOptions.map((option) => <option key={option.slug} value={option.slug}>{option.label}</option>)}
              </select>
            ) : <b>{income ? (draft.income_type ?? "other") : draft.category_label}</b>}
          </DetailRow>
          <DetailRow label="Date" index={3}>
            {editing ? <input className="amt-input draft-date-input" type="date" value={occurredOn} aria-label="Date" onChange={(event) => setOccurredOn(event.target.value)} /> : <b>{draft.occurred_on}</b>}
          </DetailRow>
          <DetailRow label="Note" index={4}>
            {editing ? <textarea className="amt-input draft-text-input draft-note-input" value={note} aria-label="Note" maxLength={280} onChange={(event) => setNote(event.target.value)} /> : <b>{draft.note || "None"}</b>}
          </DetailRow>

          {editing && (
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button className="btn btn-primary btn-sm" disabled={sen === null || !merchant.trim() || !category || !occurredOn || busy} onClick={() => void save()}>
                {failed ? "Try again" : "Save changes"}
              </button>
              <button className="btn btn-ghost btn-sm" disabled={busy} onClick={stopCorrecting}>Cancel</button>
            </div>
          )}
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
        <button
          className="btn btn-line btn-sm"
          disabled={busy}
          onClick={() => {
            if (open) {
              stopCorrecting();
            } else {
              setOpen(true);
              startCorrecting();
            }
          }}
        >
          {open ? "Close" : "Edit"}
        </button>
        <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => onDiscard(draft.id)}>
          Discard
        </button>
      </div>
    </div>
  );
}
