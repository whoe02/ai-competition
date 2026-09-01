import { useState } from "react";

import type { GoalApproval } from "../api/goals";
import { useGoalApproval } from "../api/goalHooks";
import { parseSen, toRinggitInput } from "../lib/money";
import { GoalPlanPreview } from "./GoalPlanPreview";
import { Sheet } from "./Sheet";

export function GoalApprovalSheet({
  approval,
  goalId,
  onClose,
  onReplacement,
  onSettled,
}: {
  approval: GoalApproval;
  goalId: string;
  onClose: () => void;
  onReplacement: (approval: GoalApproval) => void;
  onSettled: (result: "approved" | "rejected") => void;
}) {
  const mutation = useGoalApproval(goalId);
  const [editing, setEditing] = useState(false);
  const [target, setTarget] = useState(() => toRinggitInput(approval.after.target_amount_sen));
  const [contribution, setContribution] = useState(() =>
    toRinggitInput(approval.after.required_contribution_per_payday_sen),
  );
  const [targetDate, setTargetDate] = useState(approval.after.target_date);
  const targetSen = parseSen(target);
  const contributionSen = parseSen(contribution);

  const decide = async (
    action: "accept" | "edit" | "reject",
    args?: Record<string, unknown>,
  ) => {
    try {
      const result = await mutation.mutateAsync({ approvalId: approval.id, action, args });
      if (result.replacement) {
        onReplacement(result.replacement);
        setEditing(false);
        return;
      }
      onSettled(action === "accept" && result.applied ? "approved" : "rejected");
    } catch {
      // The mutation's error is rendered in the sheet, keeping the decision available to retry.
    }
  };

  return (
    <Sheet label="Review goal plan change" onClose={mutation.isPending ? () => undefined : onClose}>
      <div className="grab" />
      <div className="sheet-head">
        <div>
          <p className="eyebrow on-ink" style={{ margin: 0 }}>Approval required</p>
          <h2>Review before anything changes</h2>
        </div>
        <button className="xbtn" onClick={onClose} disabled={mutation.isPending} aria-label="Close">×</button>
      </div>

      {!editing ? (
        <div className="goal-approval-compare">
          {approval.before ? (
            <GoalPlanPreview plan={approval.before} title="Current plan" compact />
          ) : (
            <section className="goal-plan-preview compact">
              <p className="eyebrow">Current plan</p>
              <p className="goal-sheet-empty">No active plan yet.</p>
            </section>
          )}
          <GoalPlanPreview plan={approval.after} title="Proposed plan" compact />
        </div>
      ) : (
        <div className="goal-form goal-sheet-form">
          <label>
            Target amount <span>RM</span>
            <input aria-label="Edited target amount" inputMode="decimal" value={target} onChange={(event) => setTarget(event.target.value)} />
          </label>
          <label>
            Contribution per payday <span>RM</span>
            <input aria-label="Edited contribution per payday" inputMode="decimal" value={contribution} onChange={(event) => setContribution(event.target.value)} />
          </label>
          <label>
            Target date
            <input aria-label="Edited target date" type="date" value={targetDate} onChange={(event) => setTargetDate(event.target.value)} />
          </label>
          <p className="goal-sheet-note">KIRA will send these constraints back to the deterministic solver and ask for approval again.</p>
        </div>
      )}

      {mutation.isError && (
        <p className="goal-inline-error" role="alert">The decision could not be saved. Your current plan is unchanged.</p>
      )}

      <div className="goal-approval-actions">
        {editing ? (
          <button
            className="btn btn-brass"
            disabled={mutation.isPending || targetSen === null || contributionSen === null || !targetDate}
            onClick={() => void decide("edit", {
              target_amount_sen: targetSen,
              contribution_per_payday_sen: contributionSen,
              target_date: targetDate,
            })}
          >
            {mutation.isPending ? "Recalculating…" : "Recalculate"}
          </button>
        ) : (
          <button className="btn btn-brass" disabled={mutation.isPending} onClick={() => void decide("accept")}>
            {mutation.isPending ? "Applying…" : "Approve"}
          </button>
        )}
        <button className="btn btn-ghost" disabled={mutation.isPending} onClick={() => setEditing((value) => !value)}>
          {editing ? "Cancel edit" : "Edit"}
        </button>
        <button className="btn btn-line" disabled={mutation.isPending} onClick={() => void decide("reject")}>Reject</button>
      </div>
      <p className="goal-sheet-note">Nothing changes until you approve. Protected bills and your emergency buffer remain off limits.</p>
    </Sheet>
  );
}
