import type {
  GoalGraphRunRequest,
  GoalGraphRunResponse,
  GoalPlan,
} from "@kira/contracts";

import { decide, type ApprovalView } from "./butler";
import { api } from "./client";

/** The graph's draft is a calculated plan before persistence adds record metadata. */
export type GoalPlanDraft = Omit<GoalPlan, "plan_id" | "version" | "approval_status">;

export type GoalApproval = Omit<ApprovalView, "before" | "after"> & {
  before: GoalPlanDraft | null;
  after: GoalPlanDraft;
};

function planDraft(value: unknown): GoalPlanDraft | null {
  if (!value || typeof value !== "object") return null;
  const plan = value as Partial<GoalPlanDraft>;
  if (
    typeof plan.goal_id !== "string" ||
    typeof plan.target_amount_sen !== "number" ||
    typeof plan.current_saved_sen !== "number" ||
    typeof plan.remaining_amount_sen !== "number" ||
    typeof plan.required_contribution_per_payday_sen !== "number" ||
    typeof plan.next_required_reserve_sen !== "number" ||
    typeof plan.target_date !== "string" ||
    typeof plan.feasible !== "boolean"
  ) {
    return null;
  }
  return plan as GoalPlanDraft;
}

/** Narrow the graph's deliberately-generic approval payload at the API boundary. */
export function goalApproval(value: unknown): GoalApproval | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const after = planDraft(raw.after);
  if (
    typeof raw.approval_id !== "string" ||
    typeof raw.summary !== "string" ||
    typeof raw.tool !== "string" ||
    !after
  ) {
    return null;
  }
  return {
    id: raw.approval_id,
    summary: raw.summary,
    tool: raw.tool,
    before: planDraft(raw.before),
    after,
    basePlanVersion:
      typeof raw.base_plan_version === "number" ? raw.base_plan_version : undefined,
  };
}

export async function runStructuredGoal(
  request: GoalGraphRunRequest,
): Promise<GoalGraphRunResponse> {
  return api.post<GoalGraphRunResponse>("/v1/goals/runs", request);
}

export type GoalApprovalResult = {
  replacement: GoalApproval | null;
  applied: boolean;
  answer: string;
};

/** Consume the same approval stream as Butler, retaining any edited replacement draft. */
export async function settleGoalApproval(
  approvalId: string,
  action: "accept" | "edit" | "reject",
  args?: Record<string, unknown>,
): Promise<GoalApprovalResult> {
  let replacement: GoalApproval | null = null;
  let applied = false;
  let answer = "";
  for await (const event of decide({ id: approvalId }, action, args)) {
    if (event.type === "approval") replacement = goalApproval(event);
    if (event.type === "token") answer += event.text;
    if (event.type === "done") {
      answer = event.answer || answer;
      applied = Boolean(event.applied);
    }
    if (event.type === "error") throw new Error(event.message);
  }
  return { replacement, applied, answer };
}
