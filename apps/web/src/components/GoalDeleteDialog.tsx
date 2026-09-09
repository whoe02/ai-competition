import { useContext, useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";

import type { GoalDeletionImpact } from "@kira/contracts";

import { fmt } from "../lib/money";
import { SheetHostContext } from "./Sheet";

export function GoalDeleteDialog({
  goalName,
  impact,
  loading,
  deleting,
  previewError,
  deleteError,
  onCancel,
  onConfirm,
}: {
  goalName: string;
  impact?: GoalDeletionImpact;
  loading: boolean;
  deleting: boolean;
  previewError: boolean;
  deleteError: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const host = useContext(SheetHostContext);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !deleting) onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [deleting, onCancel]);
  const content: ReactNode = (
    <>
      <div className="scrim" onClick={deleting ? undefined : onCancel} />
      <section className="goal-delete-dialog" role="dialog" aria-modal="true" aria-label={`Delete ${goalName}`}>
        <span className="goal-delete-mark" aria-hidden="true">×</span>
        <p className="eyebrow">Remove goal</p>
        <h2>Delete “{goalName}”?</h2>
        <p>The goal will disappear from your planner and stop reserving future money. Its plan and contribution history will be kept for your records.</p>
        {loading && <div className="goal-delete-impact">Calculating the cash-flow effect…</div>}
        {impact && (
          <div className="goal-delete-impact">
            <span>Per-payday capacity released <b>RM{fmt(impact.contribution_per_payday_released_sen)}</b></span>
            <span>Safe to Spend today <b>RM{fmt(impact.safe_today_before_sen)} → RM{fmt(impact.safe_today_after_sen)}</b></span>
            <small>
              {impact.safe_today_increase_sen > 0
                ? `RM${fmt(impact.safe_today_increase_sen)} more is available today.`
                : "Today’s amount does not increase yet because no reserve from this goal is currently accrued."}
            </small>
          </div>
        )}
        {previewError && <p className="goal-inline-error" role="alert">The impact could not be loaded. Nothing has been deleted.</p>}
        {deleteError && <p className="goal-inline-error" role="alert">The goal could not be deleted. Nothing changed; you can try again.</p>}
        <div className="goal-delete-actions">
          <button className="btn btn-danger" disabled={loading || deleting || !impact} onClick={onConfirm}>
            {deleting ? "Deleting…" : "Delete goal"}
          </button>
          <button className="btn btn-line" disabled={deleting} onClick={onCancel}>Keep goal</button>
        </div>
      </section>
    </>
  );
  return host?.current ? createPortal(content, host.current) : content;
}
