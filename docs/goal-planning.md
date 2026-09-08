# KIRA deterministic goal planning

The goal planner is pure Python. It receives a `GoalDefinition` and a complete
`FinancialSnapshot`; it does not read a clock, database, network, LangGraph, or
language model. Money is always an integer number of sen. The current solver is
identified by `goal-plan-v1`, and its assumptions, risk flags, and evidence
references travel with every plan.

## Calculation rules

- The remaining amount is `max(0, target - currently saved)`.
- Paydays start at the supplied next payday and repeat using the supplied pay
  cycle. Only actual payday dates on or before the goal's target date count.
- Required contribution is the remaining amount divided by the number of those
  paydays, rounded upward to the next sen. The final scheduled payment is
  trimmed so contributions never exceed the remaining target.
- `short` means a target within 365 days and `long` means later than 365 days.
  This is display metadata only; calculations use the actual dates.
- Confirmed account and transaction records determine available cash. Draft
  transactions are excluded.
- Emergency buffer, commitments due by the next payday, and approved reserves
  for other active goals are subtracted before this goal receives money.
- Unknown income is never estimated. It is counted as unavailable and emitted
  as an explicit assumption/risk when future paydays require it.
- Purchase impact is hypothetical. It first consumes flexible cash, then marks
  any goal-reserve shortfall, completion delay, or protected-money breach. It
  does not mutate financial records.

## Versioning and persistence

`goals` stores the definition. `goal_plans` stores append-only numbered plan
versions, including its calculated milestone and scenario JSON. An approved
calculation is inserted as another version; previous approved versions are not
overwritten.

The authenticated REST endpoints are:

- `POST /v1/goals`
- `GET /v1/goals/{goal_id}`
- `GET /v1/goals/{goal_id}/plan`
- `POST /v1/goals/{goal_id}/scenarios`
- `POST /v1/goals/{goal_id}/impact`
