import type { ButlerApproval } from "@kira/contracts";

import { api } from "./client";

export type EvidenceRow = [string, string];

export type GoalPlanPreview = {
  target_amount_sen: number;
  current_saved_sen: number;
  remaining_amount_sen?: number;
  required_contribution_per_payday_sen: number;
  target_date: string;
  projected_completion_date?: string | null;
  feasible: boolean;
  monthly_income_sen?: number | null;
  monthly_protected_commitments_sen?: number;
  monthly_disposable_for_goals_sen?: number;
  monthly_goal_contributions_sen?: number;
  contribution_ratio_bp?: number | null;
  affordability_status?: string;
  risk_flags?: string[];
};

export type ApprovalView = {
  id: string;
  summary: string;
  tool: string;
  args?: Record<string, unknown>;
  before?: GoalPlanPreview | null;
  after?: GoalPlanPreview | null;
  basePlanVersion?: number;
  changes?: ChangeSetLine[];
};

export type ChangeSetLine = {
  id: string;
  tool: string;
  summary: string;
  args: Record<string, unknown>;
  enabled: boolean;
};

export type AppAction = {
  action: "navigate" | "open_sheet" | "focus_goal" | "set_plan_view";
  tab?: "today" | "activity" | "butler" | "plan" | "more";
  category?: string;
  sheet?: "entry";
  prefill?: Record<string, unknown>;
  goal_id?: string;
  plan_view?: "daily" | "goals" | "foresight";
};

export type ButlerEvent =
  | { type: "message"; id: string; role: string }
  | { type: "thinking"; text: string }
  | { type: "tool"; tool: string; module: string; label: string }
  | { type: "evidence"; rows: EvidenceRow[] }
  | { type: "token"; text: string }
  | ({ type: "app_action" } & AppAction)
  | {
      type: "approval";
      approval_id: string;
      tool: string;
      module: string;
      summary: string;
      args: Record<string, unknown>;
      before?: GoalPlanPreview | null;
      after?: GoalPlanPreview | null;
      base_plan_version?: number;
      changes?: ChangeSetLine[];
    }
  | {
      type: "done";
      answer: string;
      evidence?: EvidenceRow[];
      tools_used?: string[];
      approval: { approval_id: string; summary: string } | null;
      applied?: { tool: string; summary: string } | null;
      llm_calls?: number;
    }
  | { type: "error"; message: string };

/**
 * Read one turn as it happens.
 *
 * The graph emits its own progress events, so the "thinking" and "tool" lines
 * are real steps rather than a spinner: the reasoning turns cannot stream
 * tokens, and only the final composition does.
 */
export async function* readTurn(
  path: string,
  body?: unknown,
): AsyncGenerator<ButlerEvent> {
  const response = await api.stream(path, body);
  const reader = response.body?.getReader();
  if (!reader) throw new Error("The server opened no response stream.");

  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let split = buffer.indexOf("\n\n");
    while (split !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      const payload = frame
        .split("\n")
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice(6))
        .join("");
      if (payload) {
        const event = JSON.parse(payload) as ButlerEvent;
        terminal ||= event.type === "done" || event.type === "error";
        yield event;
      }
      split = buffer.indexOf("\n\n");
    }
  }
  if (!terminal) {
    throw new Error("The response was interrupted before Butler finished.");
  }
}

export const ask = (text: string, attachment?: unknown, threadId?: string) =>
  readTurn(threadId ? `/v1/butler/threads/${threadId}/messages` : "/v1/butler/messages", { text, attachment: attachment ?? null });

export const resumeAnswer = (threadId: string, messageId: string) =>
  readTurn(`/v1/butler/threads/${threadId}/messages/${messageId}/resume`);

export const decide = (
  approval: Pick<ButlerApproval, "id">,
  action: "accept" | "edit" | "reject",
  args?: Record<string, unknown>,
) => readTurn(`/v1/butler/approvals/${approval.id}/respond`, { action, args: args ?? null });
