# KIRA Goal orchestration

This package implements the Goal workflow around the deterministic finance
engine. Its trust boundary is deliberately simple:

1. the Butler's chat-model call interprets natural language into `GoalIntent`;
2. explicit LangGraph nodes call deterministic Python services;
3. a chat model explains the immutable result without supplying numbers.

The model is never bound to database writes, SQL, plan mutation, money
movement, or autonomous finance tools. The node-to-service calls are the tool
boundary: LangGraph chooses the workflow, while `kira.engine.goal_planning`
owns every financial value and decision.

## Graph

```text
START -> intake -> resolve target -> policy -> snapshot -> quality -> solve -> reconcile
      -> [impact] -> [scenarios] -> compose
      -> [draft -> interrupt -> apply] -> audit -> END
```

Clarification exits through audit without solving. Infeasible plans and unsafe
purchase impacts route through the deterministic scenario solver. Selecting a
scenario replaces the baseline contribution with a complete plan calculated
by Python; it does not copy model-authored numbers.

`GoalGraphState` is checkpointed typed state. The SQLAlchemy session, current
user, clock, and model factory live in non-checkpointed `GoalGraphContext`.
Production uses the same PostgreSQL saver as the Butler graph. Development and
tests use an in-memory saver with an explicit serializer allowlist for KIRA's
state types.

## LLM-call budget

| Flow | Calls |
| --- | ---: |
| Natural-language create or replan | 2 |
| Natural-language clarification | 1 |
| Structured form with explanation | 1 |
| Structured form without explanation | 0 |
| Automatic recalculation | 0 |
| Approve, reject, edit, or stale-version recalculation | 0 additional |

Call one uses LangChain structured output with `GoalIntent`; missing amounts or
dates stay missing. Call two uses `GoalExplanation`. Its schema rejects digits
and currency markers, and Python composes the authoritative numeric sentence.
If explanation validation fails, a fixed non-numeric fallback is used.

## Approval and versioning

Only an active financial-plan change reaches `interrupt()`. The approval card
contains exact before/after plans plus `base_plan_version`.

- Accept locks the latest plan, checks the base version, and appends a new
  approved version in the same transaction as approval settlement and audit.
- Reject leaves the current plan untouched.
- Edit reruns the deterministic solver and interrupts again with a new draft.
- A stale base version rejects the old approval, reloads confirmed data,
  recalculates, and asks for fresh approval.

Existing plan versions are never overwritten.

## Entry points

- `POST /v1/butler/messages` is the normal conversational entry point. The
  Butler exposes `start_goal_planning` as a typed workflow boundary, validates
  the intent, and enters this subgraph. It bypasses the ordinary Butler
  composer because this graph already made the second and final model call.
- `POST /v1/goals/runs` starts a natural-language run, or accepts a typed
  `intent` for form/event-driven flows.
- `POST /v1/butler/approvals/{approval_id}/respond` resumes both ordinary
  Butler approvals and Goal-plan approvals, routing each to its owning graph.
- `run_goal_request()` and `resume_goal_run()` provide the same boundary for
internal transaction-triggered recalculation.

The subgraph stays in `agent/goal_graph` because it has its own typed state,
conditional routes, checkpoint, and approval lifecycle. Its Butler-facing
bridge is `agent/nodes/goal.py`, alongside the other nodes in the main graph;
it is part of the same runtime rather than a second chatbot.

Run the focused tests from `apps/api`:

```bash
poetry run pytest -q tests/agent/goal_graph tests/api/test_goals.py
```
