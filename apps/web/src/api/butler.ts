import type { ButlerApproval } from "@kira/contracts";

import { api } from "./client";

export type EvidenceRow = [string, string];

export type GoalPlanPreview = {
  target_amount_sen: number;
  current_saved_sen: number;
  required_contribution_per_payday_sen: number;
  target_date: string;
  feasible: boolean;
};

export type ApprovalView = {
  id: string;
  summary: string;
  tool: string;
  args?: Record<string, unknown>;
  before?: GoalPlanPreview | null;
  after?: GoalPlanPreview | null;
  basePlanVersion?: number;
};

export type ButlerEvent =
  | { type: "message"; id: string; role: string }
  | { type: "thinking"; text: string }
  | { type: "tool"; tool: string; module: string; label: string }
  | { type: "evidence"; rows: EvidenceRow[] }
  | { type: "token"; text: string }
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
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = "";
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
      if (payload) yield JSON.parse(payload) as ButlerEvent;
      split = buffer.indexOf("\n\n");
    }
  }
}

export const ask = (text: string, attachment?: unknown) =>
  readTurn("/v1/butler/messages", { text, attachment: attachment ?? null });

export const decide = (
  approval: Pick<ButlerApproval, "id">,
  action: "accept" | "edit" | "reject",
  args?: Record<string, unknown>,
) => readTurn(`/v1/butler/approvals/${approval.id}/respond`, { action, args: args ?? null });
