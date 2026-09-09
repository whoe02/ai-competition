import { useEffect, useState } from "react";

import { DayPlan } from "./DayPlan";
import { GoalPlanner } from "./goals/GoalPlanner";

export type PlanView = "daily" | "goals" | "foresight";

type PlanProps = {
  initialView?: PlanView;
  recommendationGoalId?: string;
  onRecommendationOpened?: () => void;
};

/** Shared PLAN shell for Daily planning and Goal planning. */
export function Plan({
  initialView = "daily",
  recommendationGoalId,
  onRecommendationOpened,
}: PlanProps) {
  const [view, setView] = useState<PlanView>(initialView);

  useEffect(() => {
    setView(initialView);
  }, [initialView]);

  const selectView = (next: PlanView) => setView(next);

  return (
    <>
      <div className="plan-view-switch">
        <div className="seg-toggle" role="tablist" aria-label="Plan view">
          <span
            className="seg-thumb"
            aria-hidden="true"
            style={{
              transform:
                view !== "daily" ? "translateX(calc(100% + 5px))" : "translateX(0)",
            }}
          />
          <button
            id="plan-daily-tab"
            className={`seg-btn ${view === "daily" ? "on" : ""}`}
            type="button"
            role="tab"
            aria-selected={view === "daily"}
            aria-controls="plan-daily-panel"
            onClick={() => selectView("daily")}
          >
            Daily
          </button>
          <button
            id="plan-goals-tab"
            className={`seg-btn ${view !== "daily" ? "on" : ""}`}
            type="button"
            role="tab"
            aria-selected={view !== "daily"}
            aria-controls="plan-goals-panel"
            onClick={() => selectView("goals")}
          >
            Goals
          </button>
        </div>
      </div>

      {view === "daily" ? (
        <div id="plan-daily-panel" role="tabpanel" aria-labelledby="plan-daily-tab">
          <DayPlan />
        </div>
      ) : (
        <div id="plan-goals-panel" role="tabpanel" aria-labelledby="plan-goals-tab">
          <GoalPlanner
            recommendationGoalId={recommendationGoalId}
            onRecommendationOpened={onRecommendationOpened}
          />
        </div>
      )}
    </>
  );
}
