import type { Transaction } from "@kira/contracts";

import { fmt } from "../lib/money";
import { IcActivity, IcCam, IcMic, IcPen, IcPlan } from "./Icons";

const SOURCE_LABEL: Record<string, string> = {
  manual: "Manual",
  receipt: "Receipt",
  voice: "Voice",
  import: "Import",
  // Named, because the fallback below reads "Imported" — and a place the user
  // picked on the planner two minutes ago labelled as an import from their bank
  // is the row telling them something that never happened.
  plan: "Plan",
};

/** How a transaction arrived, so a wrong figure can be traced to its source. */
export function SourceIcon({ source, size = 16 }: { source: string; size?: number }) {
  if (source === "receipt") return <IcCam size={size} />;
  if (source === "voice") return <IcMic size={size} />;
  if (source === "manual") return <IcPen size={size} />;
  if (source === "plan") return <IcPlan size={size} />;
  return <IcActivity size={size} />;
}

export function sourceLabel(source: string): string {
  return SOURCE_LABEL[source] ?? "Imported";
}

export function TxnRow({ txn, onOpen }: { txn: Transaction; onOpen: (txn: Transaction) => void }) {
  const income = txn.direction === "income";
  return (
    <button
      type="button"
      className="txn tapp"
      style={{ width: "100%", background: "none", border: 0, textAlign: "left", font: "inherit" }}
      aria-label={`${txn.merchant}, RM${fmt(txn.amount_sen)}`}
      onClick={() => onOpen(txn)}
    >
      <span className="txn-ic">
        <SourceIcon source={txn.source} />
      </span>
      <span style={{ flex: 1, minWidth: 0 }}>
        <b style={{ fontSize: 14, letterSpacing: "-.01em" }}>{txn.merchant}</b>
        <span style={{ display: "block", fontSize: 11.5, color: "var(--muted)" }}>
          {income ? (txn.income_type === "salary" ? "Salary" : "Other income") : txn.category_label} · {sourceLabel(txn.source)}
        </span>
      </span>
      <span className="money" style={{ fontSize: 14.5, color: income ? "var(--jade)" : undefined }}>
        {income ? "+" : "−"}RM{fmt(txn.amount_sen)}
      </span>
    </button>
  );
}
