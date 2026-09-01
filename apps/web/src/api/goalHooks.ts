import type {
  GoalDetail,
  GoalGraphIntent,
  GoalGraphRunResponse,
  GoalImpact,
  GoalPlan,
  GoalScenarios,
} from "@kira/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import {
  goalApproval,
  runStructuredGoal,
  settleGoalApproval,
  type GoalApprovalResult,
} from "./goals";
import { butlerThreadKey, dashboardTodayKey } from "./hooks";

export const goalKey = (goalId: string) => ["goals", goalId] as const;
export const goalPlanKey = (goalId: string) => ["goals", goalId, "plan"] as const;

export function useGoal(goalId: string | null) {
  return useQuery({
    queryKey: goalKey(goalId ?? "none"),
    queryFn: () => api.get<GoalDetail>(`/v1/goals/${goalId}`),
    enabled: Boolean(goalId),
  });
}

export function useGoalPlan(goalId: string | null) {
  return useQuery({
    queryKey: goalPlanKey(goalId ?? "none"),
    queryFn: () => api.get<GoalPlan>(`/v1/goals/${goalId}/plan`),
    enabled: Boolean(goalId),
  });
}

function structuredRequest(intent: GoalGraphIntent) {
  return { text: "", intent, explain: false } as const;
}

export function useCreateGoal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (intent: GoalGraphIntent) => runStructuredGoal(structuredRequest(intent)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: butlerThreadKey }),
  });
}

export function useSelectGoalScenario() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ goalId, scenarioId, label }: { goalId: string; scenarioId: string; label: string }) =>
      runStructuredGoal(
        structuredRequest({
          action: "select_scenario",
          goal_id: goalId,
          scenario_id: scenarioId,
          scenario_label: label,
          wants_scenarios: true,
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: butlerThreadKey }),
  });
}

export function useGoalScenarios() {
  return useMutation({
    mutationFn: (goalId: string) =>
      api.post<GoalScenarios>(`/v1/goals/${goalId}/scenarios`),
  });
}

export function useGoalImpact() {
  return useMutation({
    mutationFn: ({ goalId, proposedSpendSen }: { goalId: string; proposedSpendSen: number }) =>
      api.post<GoalImpact>(`/v1/goals/${goalId}/impact`, {
        proposed_spend_sen: proposedSpendSen,
      }),
  });
}

export function useGoalApproval(goalId: string | null) {
  const queryClient = useQueryClient();
  return useMutation<
    GoalApprovalResult,
    Error,
    { approvalId: string; action: "accept" | "edit" | "reject"; args?: Record<string, unknown> }
  >({
    mutationFn: ({ approvalId, action, args }) =>
      settleGoalApproval(approvalId, action, args),
    onSuccess: async () => {
      const invalidations = [
        queryClient.invalidateQueries({ queryKey: dashboardTodayKey }),
        queryClient.invalidateQueries({ queryKey: butlerThreadKey }),
      ];
      if (goalId) {
        invalidations.push(
          queryClient.invalidateQueries({ queryKey: goalKey(goalId) }),
          queryClient.invalidateQueries({ queryKey: goalPlanKey(goalId) }),
        );
      }
      await Promise.all(invalidations);
    },
  });
}

export function approvalFromRun(run: GoalGraphRunResponse) {
  return goalApproval(run.approval);
}
