export const GOAL_RECOMMENDATION_READY = "kira:goal-recommendation-ready";

export type GoalRecommendationReadyDetail = {
  goalId: string;
};

export function announceGoalRecommendationReady(goalId: string): void {
  window.dispatchEvent(
    new CustomEvent<GoalRecommendationReadyDetail>(GOAL_RECOMMENDATION_READY, {
      detail: { goalId },
    }),
  );
}
