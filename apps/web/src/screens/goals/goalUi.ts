import type { GoalDetail } from "@kira/contracts";

import { GOAL_TYPES } from "./GoalCreate";

export function goalTypeLabel(value: string): string {
  return GOAL_TYPES.find((option) => option.value === value)?.label ??
    value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

export function statusLabel(status: GoalDetail["status"], feasible = true): string {
  if (status === "at_risk") return "At risk";
  if (status === "needs_replan") return "Needs replan";
  if (status === "achieved") return "Achieved";
  if (status === "paused") return "Paused";
  if (status === "draft") return "Draft";
  return feasible ? "On track" : "Needs adjustment";
}
