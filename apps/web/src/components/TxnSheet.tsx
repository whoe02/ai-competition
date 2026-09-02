import { useState } from "react";

import type { Transaction } from "@kira/contracts";

import { useApproveIncomeGoalAllocation, useIncomeGoalAllocation } from "../api/hooks";
import { fmt } from "../lib/money";
import { SourceIcon, sourceLabel } from "./TxnRow";

const DAY = new Intl.DateTimeFormat("en-MY", { weekday: "long", day: "numeric", month: "long" });

type TxnSheetProps = {
  txn: Transaction;
  onUnconfirm: (id: string) => void;
  onClose: () => void;
  busy: boolean;
};

export function TxnSheet({ txn, onUnconfirm, onClose, busy }: TxnSheetProps) {
  const income = txn.direction === "income";
  const rows: [string, string][] = [
    [income ? "Income type" : "Category", income ? (txn.income_type === "salary" ? "Salary" : "Other income") : txn.category_label],
    ["Day", DAY.format(new Date(`${txn.occurred_on}T00:00:00`))],
    ["Captured by", sourceLabel(txn.source)],
    ...(txn.note ? ([["Kira's note", txn.note]] as [string, string][]) : []),
  ];

  return (
    <>
      <div className="sheet-head">
        <div>
          <span className="tag" style={{ color: "var(--brass)" }}>
            <SourceIcon source={txn.source} size={11} /> On your ledger
          </span>
          <h2 style={{ margin: "6px 0 0", fontSize: 21, letterSpacing: "-.03em" }}>
            {txn.merchant}
          </h2>
        </div>
        <div className="money" style={{ fontSize: 22 }}>{income ? "+" : ""}RM{fmt(txn.amount_sen)}</div>
      </div>

      <div style={{ display: "grid", gap: 8 }}>
        {rows.map(([label, value], index) => (
          <div
            key={label}
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: 14,
              padding: "11px 13px",
              background: "rgba(233,237,233,.07)",
              borderRadius: 11,
              fontSize: 13,
              animation: `rowIn .45s var(--spring) ${index * 55}ms both`,
            }}
          >
            <span style={{ color: "rgba(233,237,233,.6)", flex: "none" }}>{label}</span>
            <b style={{ textAlign: "right" }}>{value}</b>
          </div>
        ))}
      </div>

      <p
        style={{
          fontSize: 12.5,
          color: "rgba(233,237,233,.62)",
          margin: "14px 0 0",
          lineHeight: 1.5,
        }}
      >
        Counted since {DAY.format(new Date(`${txn.occurred_on}T00:00:00`))}. {income
          ? "It increases confirmed cash; goal money is earmarked only after you approve the split below."
          : "Move it back and today's safe-to-spend returns to what it was."}
      </p>

      {income && <IncomeGoalAllocation txn={txn} />}

      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <button
          className="btn btn-brass btn-sm"
          style={{ flex: 1 }}
          disabled={busy || (income && Boolean(txn.goal_allocation_applied))}
          onClick={() => onUnconfirm(txn.id)}
        >
          {busy ? "Moving…" : "Move back to drafts"}
        </button>
        <button className="btn btn-line btn-sm" onClick={onClose}>
          Close
        </button>
      </div>
    </>
  );
}

function IncomeGoalAllocation({ txn }: { txn: Transaction }) {
  const [applied, setApplied] = useState(Boolean(txn.goal_allocation_applied));
  const allocation = useIncomeGoalAllocation(
    txn.id,
    !applied && txn.status === "confirmed",
  );
  const approve = useApproveIncomeGoalAllocation();
  return (
    <section style={{ marginTop: 16, padding: 13, borderRadius: 12, background: "rgba(233,237,233,.07)" }}>
          <p className="eyebrow on-ink" style={{ margin: 0 }}>Goal recommendation</p>
          {applied ? (
            <p style={{ fontSize: 13, lineHeight: 1.5, marginBottom: 0 }}>
              This income&apos;s approved goal contributions are already earmarked and included in Daily Planner.
            </p>
          ) : allocation.isLoading ? (
            <p style={{ fontSize: 13 }}>Calculating from protected bills, buffer and active goals…</p>
          ) : allocation.isError ? (
            <p style={{ fontSize: 13 }}>No goal split is available for this income.</p>
          ) : allocation.data ? (
            <>
              {allocation.data.allocations.length === 0 ? (
                <p style={{ fontSize: 13 }}>Nothing is available for goals after protected money, or there are no active goals.</p>
              ) : (
                <div style={{ display: "grid", gap: 7, marginTop: 10 }}>
                  {allocation.data.allocations.map((item) => (
                    <div key={item.goal_id} style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 13 }}>
                      <span>{item.name} · {item.priority}</span>
                      <b>RM{fmt(item.amount_sen)} · {(item.income_share_bp / 100).toFixed(2)}%</b>
                    </div>
                  ))}
                </div>
              )}
              <p style={{ fontSize: 12.5, color: "rgba(233,237,233,.62)", lineHeight: 1.5 }}>
                RM{fmt(allocation.data.allocated_sen)} would be earmarked. RM{fmt(allocation.data.unallocated_income_sen)} remains unallocated. No bill or emergency buffer is used.
              </p>
              {allocation.data.allocations.length > 0 && (
                <button
                  className="btn btn-brass btn-sm"
                  style={{ width: "100%" }}
                  disabled={approve.isPending}
                  onClick={() => approve.mutate(txn.id, { onSuccess: () => setApplied(true) })}
                >
                  {approve.isPending ? "Applying…" : "Approve goal contributions"}
                </button>
              )}
              {approve.isError && <p style={{ fontSize: 12.5 }}>The split was not applied. Nothing changed.</p>}
            </>
          ) : null}
    </section>
  );
}
