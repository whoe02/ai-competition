export const GOAL_RECOMMENDATION_READY = "kira:goal-recommendation-ready";
export const GOAL_RECOMMENDATION_OFFER = "kira:goal-recommendation-offer";

export type GoalRecommendationReadyDetail = {
  goalId: string;
};

export type GoalRecommendationOfferDetail = {
  goalId: string;
  goalName: string;
};

export function announceGoalRecommendationReady(goalId: string): void {
  window.dispatchEvent(
    new CustomEvent<GoalRecommendationReadyDetail>(GOAL_RECOMMENDATION_READY, {
      detail: { goalId },
    }),
  );
}

export function announceGoalRecommendationOffer(goalId: string, goalName: string): void {
  window.dispatchEvent(
    new CustomEvent<GoalRecommendationOfferDetail>(GOAL_RECOMMENDATION_OFFER, {
      detail: { goalId, goalName },
    }),
  );
}
