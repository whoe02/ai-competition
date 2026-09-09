import type {
  GoalDetail,
  GoalGraphIntent,
  GoalGraphRunResponse,
  GoalPlan,
  GoalScenarios,
  PartTimeJobRecommendation,
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
import { announceGoalRecommendationReady } from "../lib/goalRecommendationEvents";

export const goalKey = (goalId: string) => ["goals", goalId] as const;
export const goalPlanKey = (goalId: string) => ["goals", goalId, "plan"] as const;
export const goalPartTimeRecommendationKey = (goalId: string) =>
  ["goals", goalId, "part-time-recommendation"] as const;

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

export function useChangeGoalPriority() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ goalId, priority }: { goalId: string; priority: "protected" | "important" | "flexible" }) =>
      runStructuredGoal(
        structuredRequest({
          action: "recalculate",
          goal_id: goalId,
          priority,
          wants_scenarios: false,
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

export function usePartTimeRecommendation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      goalId,
      availableHoursPerWeek,
      workMode,
      transportLimitations,
    }: {
      goalId: string;
      availableHoursPerWeek: number;
      workMode: "remote" | "on_site" | "either";
      transportLimitations: string;
    }) => {
      const result = await api.post<PartTimeJobRecommendation>(`/v1/goals/${goalId}/part-time-recommendation`, {
        available_hours_per_week: availableHoursPerWeek,
        work_mode: workMode,
        transport_limitations: transportLimitations,
      });
      queryClient.setQueryData(goalPartTimeRecommendationKey(goalId), result);
      if (result.status === "available") announceGoalRecommendationReady(goalId);
      return result;
    },
  });
}

export function useStoredPartTimeRecommendation(goalId: string | null) {
  return useQuery({
    queryKey: goalPartTimeRecommendationKey(goalId ?? "none"),
    queryFn: () =>
      api.get<PartTimeJobRecommendation | null>(
        `/v1/goals/${goalId}/part-time-recommendation`,
      ),
    enabled: Boolean(goalId),
  });
}

export function usePartTimeRecommendationImpact() {
  return useMutation({
    mutationFn: ({ goalId, expectedMonthlyIncomeSen }: { goalId: string; expectedMonthlyIncomeSen: number }) =>
      api.post<PartTimeJobRecommendation>(`/v1/goals/${goalId}/part-time-recommendation/impact`, {
        expected_monthly_income_sen: expectedMonthlyIncomeSen,
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
