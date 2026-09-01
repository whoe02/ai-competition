import { useState, type FormEvent } from "react";

import type { GoalGraphIntent, GoalScenario } from "@kira/contracts";

import { approvalFromRun, useCreateGoal, useGoalScenarios } from "../../api/goalHooks";
import type { GoalApproval } from "../../api/goals";
import { GoalApprovalSheet } from "../../components/GoalApprovalSheet";
import { GoalPlanPreview, formatGoalDate } from "../../components/GoalPlanPreview";
import { fmt, parseNonNegativeSen, parseSen } from "../../lib/money";

type GoalType = NonNullable<GoalGraphIntent["goal_type"]>;
type GoalPriority = NonNullable<GoalGraphIntent["priority"]>;

export const GOAL_TYPES: { value: GoalType; label: string; hint: string }[] = [
  { value: "emergency_starter_fund", label: "Emergency starter fund", hint: "A first layer of protection" },
  { value: "upcoming_bill_annual_expense", label: "Upcoming bill", hint: "Annual or known expense" },
  { value: "travel", label: "Travel", hint: "A trip with a target date" },
  { value: "big_purchase", label: "Big purchase", hint: "Something worth planning for" },
  { value: "wedding_event_deposit", label: "Event deposit", hint: "A near-term booking or deposit" },
  { value: "house_down_payment", label: "House down payment", hint: "A longer-term home target" },
  { value: "car_down_payment", label: "Car down payment", hint: "A vehicle deposit target" },
  { value: "wedding_fund", label: "Wedding fund", hint: "The wider wedding budget" },
  { value: "full_emergency_fund", label: "Full emergency fund", hint: "A deeper safety reserve" },
  { value: "education_family_goal", label: "Education or family", hint: "Study and family milestones" },
  { value: "custom_goal", label: "Custom goal", hint: "Name your own destination" },
];

function todayInput(): string {
  const today = new Date();
  const month = String(today.getMonth() + 1).padStart(2, "0");
  const day = String(today.getDate()).padStart(2, "0");
  return `${today.getFullYear()}-${month}-${day}`;
}

export function GoalCreate({
  onBack,
  onActivated,
}: {
  onBack: () => void;
  onActivated: (goalId: string) => void;
}) {
  const create = useCreateGoal();
  const scenarioMutation = useGoalScenarios();
  const [goalType, setGoalType] = useState<GoalType>("emergency_starter_fund");
  const [name, setName] = useState("Emergency starter fund");
  const [target, setTarget] = useState("");
  const [saved, setSaved] = useState("0.00");
  const [targetDate, setTargetDate] = useState("");
  const [priority, setPriority] = useState<GoalPriority>("important");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [approval, setApproval] = useState<GoalApproval | null>(null);
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [goalId, setGoalId] = useState<string | null>(null);
  const [scenarios, setScenarios] = useState<GoalScenario[]>([]);
  const targetSen = parseSen(target);
  const savedSen = parseNonNegativeSen(saved);

  const chooseType = (value: GoalType) => {
    setGoalType(value);
    const option = GOAL_TYPES.find((item) => item.value === value);
    if (!name.trim() || GOAL_TYPES.some((item) => item.label === name)) {
      setName(option?.label ?? "");
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const nextErrors: Record<string, string> = {};
    if (!name.trim()) nextErrors.name = "Give this goal a name.";
    if (targetSen === null) nextErrors.target = "Enter a target greater than RM0.00.";
    if (savedSen === null) nextErrors.saved = "Enter zero or a valid amount.";
    if (targetSen !== null && savedSen !== null && savedSen > targetSen) {
      nextErrors.saved = "Already saved cannot be more than the target.";
    }
    if (!targetDate || targetDate <= todayInput()) nextErrors.date = "Choose a future target date.";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0 || targetSen === null || savedSen === null) return;

    try {
      const run = await create.mutateAsync({
        action: "create",
        goal_type: goalType,
        name: name.trim(),
        target_amount_sen: targetSen,
        current_saved_sen: savedSen,
        target_date: targetDate,
        priority,
        funding_account_ids: [],
        wants_scenarios: false,
      });
      const nextApproval = approvalFromRun(run);
      if (!run.goal_id || !nextApproval) {
        setErrors({ submit: run.errors?.join(" ") || run.final_response || "No plan was returned." });
        return;
      }
      setGoalId(run.goal_id);
      setApproval(nextApproval);
      if (run.feasible === false) {
        try {
          const alternatives = await scenarioMutation.mutateAsync(run.goal_id);
          setScenarios(alternatives.scenarios);
        } catch {
          // The calculated plan remains reviewable even when alternatives cannot load.
        }
      }
    } catch {
      // Mutation errors are rendered below without losing the user's inputs.
    }
  };

  if (approval && goalId) {
    return (
      <div className="goal-screen">
        <GoalScreenHead eyebrow="Create goal" title="Review your plan" onBack={onBack} />
        <div className="goal-content">
          <div className="goal-review-name">
            <span className="goal-template-mark">{name.slice(0, 1).toUpperCase()}</span>
            <div><h2>{name}</h2><p>{GOAL_TYPES.find((item) => item.value === goalType)?.label}</p></div>
          </div>
          <GoalPlanPreview plan={approval.after} />

          {!approval.after.feasible && scenarios.length > 0 && (
            <section className="goal-alternatives" aria-label="Backend alternatives">
              <div className="goal-section-head">
                <div><p className="eyebrow">Backend alternatives</p><h3>Ways to make it fit</h3></div>
              </div>
              {scenarios.map((scenario) => (
                <article className="goal-scenario-card" key={scenario.scenario_id}>
                  <div className="goal-section-head">
                    <b>{scenario.label}</b>
                    <span className={`goal-health ${scenario.feasible ? "healthy" : "danger"}`}>
                      {scenario.feasible ? "Feasible" : "At risk"}
                    </span>
                  </div>
                  <p><strong>RM{fmt(scenario.contribution_per_payday_sen)}</strong> per payday · {formatGoalDate(scenario.target_date)}</p>
                  {scenario.tradeoffs.map((tradeoff) => <small key={tradeoff}>{tradeoff}</small>)}
                </article>
              ))}
              <p className="goal-muted">Use Edit in the approval review to send adjusted constraints back for deterministic recalculation.</p>
            </section>
          )}

          <button className="btn btn-primary goal-full-button" onClick={() => setApprovalOpen(true)}>
            Review &amp; activate
          </button>
          <p className="goal-lock-note">This is still a draft. Nothing is active until you explicitly approve it.</p>
        </div>

        {approvalOpen && (
          <GoalApprovalSheet
            approval={approval}
            goalId={goalId}
            onClose={() => setApprovalOpen(false)}
            onReplacement={(replacement) => {
              setApproval(replacement);
              setApprovalOpen(true);
            }}
            onSettled={(result) => {
              setApprovalOpen(false);
              if (result === "approved") onActivated(goalId);
              else onBack();
            }}
          />
        )}
      </div>
    );
  }

  return (
    <div className="goal-screen">
      <GoalScreenHead eyebrow="New goal" title="What are you saving toward?" onBack={onBack} />
      <form className="goal-content goal-form" onSubmit={(event) => void submit(event)} noValidate>
        <fieldset>
          <legend className="eyebrow">Choose a goal</legend>
          <div className="goal-template-grid">
            {GOAL_TYPES.map((option) => (
              <button
                type="button"
                className={`goal-template ${goalType === option.value ? "selected" : ""}`}
                aria-pressed={goalType === option.value}
                key={option.value}
                onClick={() => chooseType(option.value)}
              >
                <b>{option.label}</b><span>{option.hint}</span>
              </button>
            ))}
          </div>
        </fieldset>

        <label>
          Goal name
          <input aria-label="Goal name" value={name} maxLength={80} onChange={(event) => setName(event.target.value)} aria-invalid={Boolean(errors.name)} />
          {errors.name && <small className="goal-field-error">{errors.name}</small>}
        </label>
        <div className="goal-form-row">
          <label>
            Target amount <span>RM</span>
            <input aria-label="Target amount" inputMode="decimal" placeholder="50,000.00" value={target} onChange={(event) => setTarget(event.target.value)} aria-invalid={Boolean(errors.target)} />
            {errors.target && <small className="goal-field-error">{errors.target}</small>}
          </label>
          <label>
            Already saved <span>RM</span>
            <input aria-label="Amount already saved" inputMode="decimal" value={saved} onChange={(event) => setSaved(event.target.value)} aria-invalid={Boolean(errors.saved)} />
            {errors.saved && <small className="goal-field-error">{errors.saved}</small>}
          </label>
        </div>
        <label>
          Target date
          <input aria-label="Target date" type="date" min={todayInput()} value={targetDate} onChange={(event) => setTargetDate(event.target.value)} aria-invalid={Boolean(errors.date)} />
          {errors.date && <small className="goal-field-error">{errors.date}</small>}
        </label>
        <fieldset>
          <legend className="eyebrow">Priority</legend>
          <div className="goal-priority-options">
            {(["protected", "important", "flexible"] as GoalPriority[]).map((value) => (
              <button type="button" className={priority === value ? "selected" : ""} aria-pressed={priority === value} key={value} onClick={() => setPriority(value)}>
                {value.replace(/^./, (letter) => letter.toUpperCase())}
              </button>
            ))}
          </div>
        </fieldset>

        {(errors.submit || create.isError) && (
          <p className="goal-inline-error" role="alert">
            {errors.submit || "KIRA could not calculate the plan. Check your connection and try again."}
          </p>
        )}
        <button className="btn btn-primary goal-full-button" type="submit" disabled={create.isPending}>
          {create.isPending ? "Calculating safely…" : "Calculate plan"}
        </button>
        <p className="goal-lock-note">The backend calculates feasibility, reserves and contributions from confirmed records. This form never performs those calculations.</p>
      </form>
    </div>
  );
}

export function GoalScreenHead({ eyebrow, title, onBack }: { eyebrow: string; title: string; onBack: () => void }) {
  return (
    <div className="goal-screen-head">
      <button className="goal-back" onClick={onBack} aria-label="Back to goals">←</button>
      <div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1></div>
    </div>
  );
}
