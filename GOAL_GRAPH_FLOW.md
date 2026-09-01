# KIRA Goal Graph: Complete Pipeline Flow

## Overview

The Goal Graph is a **deterministic financial planning subgraph** within the Butler's LangGraph framework. It handles the complete lifecycle of goal planning from user intent → financial calculation → approval → application.

**Key Principle**: The model interprets intent. Python calculates everything. The model explains only (no numbers).

---

## 1. Entry Points (API Layer)

Users interact with goals through multiple entry points:

### A. Through Butler Chat (Most Common)
```
POST /v1/butler/messages
→ User message: "I want to save RM50,000 for a wedding by August 2027"
→ Butler agent detects goal intent
→ Triggers: start_goal_planning workflow
```

### B. Direct Goal API
```
POST /v1/goals/runs  
→ Structured intent or free text
→ Launches goal graph directly
```

### C. Goal CRUD Operations
```
POST /v1/goals           # Create new goal (basic)
GET  /v1/goals/{id}      # View goal details
GET  /v1/goals/{id}/plans     # View plan history
```

### D. Impact Analysis
```
POST /v1/goals/{id}/impact
→ "What if I spend RM500 on this trip?"
→ Returns impact on goal feasibility
```

---

## 2. Butler Integration: Entry to Goal Graph

When the Butler's agent detects a goal-related message:

```
┌─────────────────────────────────────────────────────────────┐
│ Butler Main Graph                                           │
├─────────────────────────────────────────────────────────────┤
│ START → load_context → agent → insist → guard              │
│                                          ↓                 │
│                            route_after_guard()             │
│                                  ↓                          │
│                        Is this a goal workflow?             │
│                            ↓ (YES)                          │
│                        goal_workflow NODE                   │
│                            ↓                                │
│                    Calls: start_goal_planning               │
│                            ↓                                │
│         ┌─────────────────────────────────────┐            │
│         │  ENTER GOAL SUBGRAPH                │            │
│         │  (goal_graph/graph.py)              │            │
│         └─────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────┘
```

The goal workflow executes **`run_goal_request()`** which:
- Creates a new thread ID: `goal:{butler_thread_id}:{request_id}`
- Initializes GoalGraphState
- Creates GoalGraphContext (session, user, clock, model)
- Invokes the goal graph with structured intent (if provided by Butler)

---

## 3. Goal Graph: Full Pipeline

### **High-Level Flow**

```
START → intake → resolve target → policy → snapshot → quality 
  → solve → reconcile → [impact/scenarios/compose] → draft 
  → interrupt → [apply/snapshot] → audit → END
```

### **Detailed Node-by-Node Breakdown**

#### **Stage 1: INTAKE & INTENT PARSING**

**Node: `goal_intake`**
```
Input: User message or structured intent
Output: GoalIntent (Pydantic model)

What it does:
- If structured intent provided: validate and normalize it (skip LLM call)
- Else: Call LLM #1 with GOAL_INTAKE_PROMPT to parse natural language
- Extracts: action, goal_id, goal_type, target_amount, target_date, etc.
- Normalizes: Identifies missing fields

LLM Cost: 0-1 call (1 only if free text, 0 if form-provided)
```

**Routing: `route_after_intake`**
- If missing critical fields → `clarification_response` (ask user for details)
- Else → `resolve_goal_target`

---

#### **Stage 2: GOAL TARGET RESOLUTION**

**Node: `resolve_goal_target`**
```
Input: GoalIntent, optional goal_id/reference
Output: GoalDefinition

What it does:
- For CREATE action: Build new GoalDefinition from intent
- For REPLAN/IMPACT/RECALCULATE: Load existing goal from DB
- Reference lookup: Search by goal name/keywords if needed
- Validates: All required fields present and sensible

Database: Reads Goal table, performs fuzzy matching if needed
```

**Routing: `route_after_resolve`**
- If still missing fields → `clarification_response`
- Else → `goal_policy_guard`

---

#### **Stage 3: POLICY & CONSTRAINTS CHECK**

**Node: `goal_policy_guard`**
```
Input: GoalDefinition
Output: Validated goal with policy checks

What it does:
- Validates goal against policy rules:
  * Target date must be in the future
  * Target amount reasonable range
  * No duplicate simultaneous goals of same type
  * Respects account funding restrictions
  * Checks user's buffer and protected commitments don't conflict

Returns: OK to proceed, or CLARIFY if policy violation
```

**Routing: `route_after_guard`**
- Policy OK → `load_financial_snapshot`
- Policy violation → `clarification_response`

---

#### **Stage 4: FINANCIAL SNAPSHOT LOAD**

**Node: `load_financial_snapshot`**
```
Input: GoalDefinition, current user/date
Output: FinancialSnapshot

What it does (calls kira.engine.goal_planning):
- Queries: Current accounts, balance, transactions
- Queries: Protected commitments (rent, loans)
- Queries: Other active goals
- Queries: Next paydays and income
- Builds: Complete financial picture as-of-date
- Calculates: Current goal reserve amounts

Returned snapshot includes:
  * AccountBalance[] - available funds
  * IncomePayday[] - income schedule  
  * ProtectedCommitment[] - reserved amounts
  * ActiveGoalReserve[] - other goal claims
```

**Always flows to: `goal_data_quality_gate`**

---

#### **Stage 5: DATA QUALITY ASSESSMENT**

**Node: `goal_data_quality_gate`**
```
Input: FinancialSnapshot, GoalDefinition
Output: GoalDataQuality status

What it does:
- Assesses data completeness:
  * DO WE HAVE NEXT PAYDAY? (critical)
  * DO WE HAVE INCOME AMOUNT? (important)
  * HOW COMPLETE ARE COMMITMENTS? (important)
  * HOW COMPLETE ARE ACCOUNTS? (context)
  
- Returns status: "ready" | "limited" | "blocked"
  * ready: Full data, can calculate confidently
  * limited: Can calculate but with assumptions/caveats
  * blocked: Cannot proceed safely (no payday, no income)

If blocked and blocking field is missing:
  → clarification_response (ask user for it)
```

**Routing: `route_after_quality`**
- Data ready or limited → `solve_goal_baseline`
- Data blocked → `clarification_response`

---

#### **Stage 6: SOLVE BASELINE PLAN**

**Node: `solve_goal_baseline`**
```
Input: GoalDefinition, FinancialSnapshot, data quality
Output: GoalPlan (baseline solution)

What it calls: kira.engine.goal_planning.calculate_goal_feasibility()

What it does:
- Pure Python deterministic calculation
- Given target date and savings target
- Calculates MINIMUM required monthly/payday contribution
- Calculates milestones (25%, 50%, 75%, 100%)
- Assesses feasibility:
  * Feasible: Can reach goal with available funds
  * Tight: Possible but risky (low buffer, high committed)
  * Infeasible: Impossible given constraints
  * At Risk: Feasible but needs plan change if income drops

- Generates evidence_refs for all assumptions

Returns: GoalPlan with:
  * target_amount_sen
  * required_contribution_per_payday_sen
  * next_required_reserve_sen (for current cycle)
  * projected_completion_date
  * milestones[]
  * risk_flags: ["low_income_assumed", "tight_buffer", ...]
  * assumptions: ["income stable", "no emergency spending", ...]
```

**Always flows to: `reconcile_short_term_cashflow`**

---

#### **Stage 7: SHORT-TERM CASHFLOW RECONCILIATION**

**Node: `reconcile_short_term_cashflow`**
```
Input: GoalPlan, FinancialSnapshot
Output: CashflowReconciliation + routing decision

What it does:
- Checks: Can we afford the required contribution NEXT payday?
- Calculates: Will the goal reserve fit alongside commitments?
- Identifies: Any immediate conflict with protected spending
- Returns: Reconciliation report with warnings

Reconciliation output includes:
  * next_payday_feasible: bool (can we make next deposit?)
  * days_until_next_payday: int
  * required_reserve_sen: int
  * available_for_contribution_sen: int
  * shortfall_or_surplus_sen: int
  * conflict_details: str
```

**Routing: `route_after_reconciliation`**
Decides what to present to user:

1. **Infeasible & high impact** → `evaluate_goal_impact`
   (Let user see what impact a purchase would have)

2. **Feasible with scenarios** → `generate_goal_scenarios`
   (User wants to see alternatives)

3. **Feasible baseline** → `compose_goal_response`
   (Just explain the one solution)

4. **User wants to change it** → `create_plan_change_draft`
   (Create approval workflow)

---

#### **Stage 8: IMPACT ANALYSIS (Conditional)**

**Node: `evaluate_goal_impact`**
```
Input: GoalPlan, proposed purchase amount (from state.proposed_spend_sen)
Output: GoalImpact

What it calls: kira.engine.goal_planning.purchase_impact()

What it does:
- Simulates: "If I spend RM{X}, what happens to my goal?"
- Calculates:
  * New available balance after purchase
  * Will it touch protected money? (goal reserve, buffer, commitments)
  * New projected completion date
  * How many days of delay?
  * How much flexible spending remains?
  
Returns: GoalImpact with full before/after comparison
```

**Routing: `route_after_impact`**
- If impact is acceptable → `compose_goal_response`
- If impact requires scenarios → `generate_goal_scenarios`

---

#### **Stage 9: SCENARIO GENERATION (Conditional)**

**Node: `generate_goal_scenarios`**
```
Input: GoalPlan, FinancialSnapshot, data quality
Output: GoalScenario[] (3-5 alternative plans)

What it calls: kira.engine.goal_planning.create_scenarios()

What it generates:
1. BASELINE: The required minimum contribution (already calculated)
2. ACCELERATED: Higher contribution, reach goal faster
3. CONSERVATIVE: Lower contribution, stretched timeline (if feasible)
4. BUFFER_FOCUS: Prioritize emergency fund first, then goal
5. RECALC_WITH_INCOME: Assumes future income increase

Each scenario includes:
  * label: "Reach by June 2027"
  * contribution_per_payday_sen
  * target_date (may differ from baseline)
  * flexible_spending_delta_sen: How much daily spend changes
  * tradeoffs: ["Higher daily expense", "Lower buffer"]
  * risk_flags: Warnings specific to this scenario
  
All values calculated by deterministic engine, not LLM
```

**Routing: `route_after_scenarios`**
- Scenarios OK → `compose_goal_response`
- Cannot create safe scenarios → `clarification_response`

---

#### **Stage 10: RESPONSE COMPOSITION**

**Node: `compose_goal_response`**
```
Input: GoalDefinition, GoalPlan, GoalScenario[], data quality
Output: final_response (prose explanation)

What it calls: LLM call #2 with GOAL_RESPONSE_PROMPT

What the LLM does:
- DOES NOT calculate or supply numbers
- Schema: GoalExplanation { explanation: str, tradeoffs: str[] }
- Validates: No digits, no currency symbols in response
- Explains reasoning in prose:
  * "Here's why this goal is feasible"
  * "Here's what changes if you accelerate"
  * "Here's the key risk to watch"

All numbers are inserted by Python around this prose:
```python
f"To reach RM{fmt(plan.target_amount_sen)} by {plan.projected_completion_date}, 
you need to save RM{fmt(plan.required_contribution_per_payday_sen)} each payday.
{explanation}  # ← LLM writes only this
This requires {fmt(plan.next_required_reserve_sen)} reserved before payday."
```

LLM Cost: 1 call (or 0 if explain=False)

Returns: final_response ready for user
```

**Routing: `route_after_compose`**
- Plan needs approval (goal change) → `create_plan_change_draft`
- Just informational → `audit_goal_run` → END

---

#### **Stage 11: DRAFT PLAN CHANGE (For Approvals)**

**Node: `create_plan_change_draft`**
```
Input: GoalPlan (new), GoalDefinition
Output: PlanChangeDraft + creates DB record

What it does:
- Stores BEFORE plan (previous version if replan, else None)
- Stores AFTER plan (new proposed plan)
- Stores base_plan_version for optimistic locking
- Stores reason/context
- Creates approval record with:
  * approval_id (UUID)
  * approval_status: "pending"
  * before_plan: Previous plan details (if replan)
  * after_plan: Proposed plan details
  
Database writes:
- Inserts GoalPlanRecord (version = current_version + 1, status = draft)
- Creates ButlerApproval record

Returns: PlanChangeDraft to interrupt execution
```

**Always flows to: `approval_interrupt`**

---

#### **Stage 12: APPROVAL INTERRUPT**

**Node: `approval_interrupt`**
```
Input: PlanChangeDraft
Output: Interrupts execution, waits for user response

What it does:
- Pauses the subgraph (LangGraph interrupt mechanism)
- Stores approval data in interrupts[]
- Returns control to user
- User sees approval card in UI:
  * Before: Previous plan (if any)
  * After: Proposed plan
  * Buttons: Accept | Edit | Reject

Execution pauses at this exact point.
Next user action resumes with decision payload.

Routing information stored for next step:
- route_after_approval awaits decision
```

**Execution waits for user action via:**
```
POST /v1/butler/approvals/{approval_id}/respond
{
  "action": "accept" | "edit" | "reject",
  "edit": { "target_amount_sen": 600000, ... }  // if action="edit"
}
```

---

#### **Stage 13: APPROVAL RESPONSE ROUTING**

**Node: `route_after_approval` (conditional edge)**

**Decision A: User clicks ACCEPT**
```
→ apply_goal_plan (proceed with state.approval)
```

**Decision B: User clicks EDIT**
```
→ load_financial_snapshot (restart calculation loop)
  (Recalculates with edited parameters, re-interrupts)
```

**Decision C: User clicks REJECT**
```
→ audit_goal_run (log rejection, no plan change)
```

**Decision D: Plan version is stale**
```
→ load_financial_snapshot (reload all data, recalculate)
  (Another goal changed, this plan is outdated)
```

---

#### **Stage 14: APPLY PLAN CHANGE**

**Node: `apply_goal_plan`**
```
Input: Approved PlanChangeDraft
Output: Applied plan record in database

What it calls: kira.services.goal_planning.apply_approved_plan_change()

What it does:
- Validates: base_plan_version still matches (no race condition)
- Creates: New GoalPlanRecord with approval_status = "approved"
- Updates: Goal table (set current_plan_version += 1)
- Marks: Previous draft versions as superseded
- Records: Approval timestamp
- Writes audit entry

Database transactions:
- Insert approved GoalPlanRecord
- Update Goal.current_plan_version
- Update ButlerApproval.status
- Create AuditLog entry

Returns: Applied version info for next stage

Error handling:
- If base_plan_version != current: StalePlanVersion error
  → Reject approval, ask for fresh approval
```

**Routing: `route_after_apply`**
- Success → `audit_goal_run`
- Stale version → `load_financial_snapshot` (restart)

---

#### **Stage 15: AUDIT & LOGGING**

**Node: `audit_goal_run`**
```
Input: Complete GoalGraphState
Output: Audit log entry + cleanup

What it does:
- Records: request_id, goal_id, action, result
- Records: Plan version applied (if any)
- Records: Number of LLM calls used
- Records: All evidence_refs used
- Records: Any errors/clarifications
- Records: Timestamp and user ID

Audit entry stored in: butler_messages or dedicated audit table

Format:
{
  request_id: UUID
  user_id: UUID
  action: "create" | "replan" | "impact" | "select_scenario"
  goal_id: UUID (if applicable)
  applied_plan_version: int (if approved)
  llm_calls: int
  clarifications: int
  errors: str[]
  completed_at: timestamp
}
```

**Always flows to: END**

---

#### **ALTERNATIVE: Clarification Response**

**Node: `clarification_response` (Throughout pipeline)**
```
Input: State with missing/invalid data
Output: Clarification message to user, then audit

What it does:
- Identifies what info is missing
- Generates friendly ask: "I need to know your target date"
- Returns explanation without calculating

LLM Cost: 0 (uses templates)

Then: → audit_goal_run → END

User responds with clarification, restarts the flow with new intent
```

---

## 4. Goal Graph State Machine

### **GoalGraphState** (Typed checkpoint)

```python
GoalGraphState(TypedDict):
  # Inputs
  request_id: str
  thread_id: str
  user_id: str
  user_message: str
  
  # Parsed Intent
  goal_intent: GoalIntent | None
  
  # Resolved Goal
  goal_definition: GoalDefinition | None
  base_goal_definition: GoalDefinition | None  # For replans
  
  # Financial Context
  financial_snapshot: FinancialSnapshot | None
  data_quality: GoalDataQuality | None
  
  # Calculated Plans
  current_goal_plan: GoalPlan | None
  base_goal_plan: GoalPlan | None  # Previous plan if replan
  current_plan_version: int
  
  # Scenario Data
  goal_scenarios: tuple[GoalScenario, ...]
  selected_scenario: GoalScenario | None
  
  # Analysis
  reconciliation: CashflowReconciliation | None
  goal_impact: GoalImpact | None
  
  # Approval Workflow
  proposed_change: PlanChangeDraft | None
  approval: dict[str, Any] | None
  resume_action: str | None  # "accept" | "reject" | "edit"
  applied_plan_version: int | None
  approval_round: int
  
  # Output
  final_response: str
  evidence_refs: tuple[str, ...]
  errors: list[str]
  llm_calls: int
  override_contribution_sen: int | None
```

### **GoalGraphContext** (Non-checkpointed runtime)

```python
GoalGraphContext:
  session: AsyncSession  # Database connection
  user: User  # Current user object
  as_of_utc: datetime  # Clock for calculations
  thread_id: uuid.UUID  # Butler thread ID
  model_factory: Callable  # LLM factory for stages
  structured_intent: GoalIntent | None  # From form/API
  explain: bool  # Whether to call composition LLM
```

---

## 5. Database Schema Impact

### **Primary Tables Affected**

#### `goals` table (Updated)
```
id (PK)
user_id (FK to users)
name, goal_type, horizon
target_amount_sen, current_saved_sen
target_date, priority, status
funding_account_ids (JSON)
created_at, updated_at
current_plan_version: int  # NEW: Points to latest version
```

#### `goal_plans` (NEW - Versioned Plans)
```
id (PK)
goal_id (FK)
version: int  # 1, 2, 3, ...
approval_status: "draft" | "approved"
feasible: bool
target_amount_sen, remaining_amount_sen
required_contribution_per_payday_sen
next_required_reserve_sen
projected_completion_date
risk_flags, assumptions, evidence_refs (JSON)
created_at, approved_at
```

#### `goal_scenarios` (NEW - Alternative Plans)
```
id (PK)
plan_id (FK)
label: str  # "Accelerated", "Conservative", ...
feasible: bool
contribution_per_payday_sen
target_date
goal_delay_days
flexible_spending_delta_sen
tradeoffs, risk_flags (JSON)
```

#### `goal_milestones` (NEW - Progress Checkpoints)
```
id (PK)
plan_id (FK)
percentage: 25, 50, 75, 100
amount_sen
projected_date
```

#### `butler_approvals` (Updated)
```
id (PK)
thread_id, message_id (FK)
tool: str  # "start_goal_planning" for goal approvals
approval_status: "pending" | "approved" | "rejected"
args: JSON  # { before, after, base_plan_version }
created_at, responded_at
```

---

## 6. Complete Message Flow Example

### **User Input: "I want to save RM50,000 for a wedding by August 2027"**

```
1. BUTLER RECEIVES MESSAGE
   POST /v1/butler/messages
   body: { content: "I want to save RM50,000 for a wedding by August 2027" }
   
2. BUTLER AGENT RECOGNIZES GOAL INTENT
   → Detects: goal creation workflow needed
   → Extracts preliminary intent (tentative)
   → Produces tool call: start_goal_planning
   
3. BUTLER ROUTES TO GOAL_WORKFLOW NODE
   → Creates goal subgraph thread
   → Passes intent to goal graph
   
4. GOAL GRAPH: goal_intake NODE
   LLM Call #1: Parse intent
   Input: GOAL_INTAKE_PROMPT + user message
   Output: GoalIntent {
     action: "create",
     goal_type: "wedding_fund",
     target_amount_sen: 5000000,  # RM50,000
     target_date: 2027-08-01,
     priority: "important"
   }
   
5. GOAL GRAPH: resolve_goal_target NODE
   → Check: Does similar goal exist?
   → No existing goal
   → Create new GoalDefinition
   
6. GOAL GRAPH: goal_policy_guard NODE
   → Validate: Date is future? ✓
   → Validate: Amount reasonable? ✓
   → No policy violations
   
7. GOAL GRAPH: load_financial_snapshot NODE
   Query user's accounts:
   → Account balance: RM50,000
   → Next paydays: [2026-09-15, 2026-09-30, ...]
   → Monthly income: RM8,000
   → Protected commitments: [Rent RM1,200 on 5th]
   → Other goals: [Emergency fund at RM10,000]
   → Buffer required: RM800
   → Current goals reserve: RM5,000
   
8. GOAL GRAPH: goal_data_quality_gate NODE
   → Have income amount? ✓
   → Have next payday? ✓
   → Quality: "ready"
   
9. GOAL GRAPH: solve_goal_baseline NODE
   Python calculation (kira.engine.goal_planning):
   Input: target = RM50,000, target_date = 2027-08-01, available = RM34,200/month
   Calculation:
   - Months until: 23 months
   - Required monthly: RM50,000 / 23 = RM2,174 minimum
   - Try: RM2,500/month → feasible ✓
   - Projected completion: 2027-07-15 (20 months actual)
   - Risk: Low buffer if emergency spending
   
   Output: GoalPlan {
     feasible: true,
     required_contribution_per_payday_sen: 115000,  # RM1,150 per payday
     next_required_reserve_sen: 115000,
     projected_completion_date: 2027-07-15,
     milestones: [
       { percentage: 25, amount: 1250000, projected_date: 2026-11-15 },
       { percentage: 50, amount: 2500000, projected_date: 2027-02-15 },
       { percentage: 75, amount: 3750000, projected_date: 2027-05-15 },
       { percentage: 100, amount: 5000000, projected_date: 2027-07-15 }
     ],
     risk_flags: ["buffer_moderate", "income_assumed_stable"]
   }
   
10. GOAL GRAPH: reconcile_short_term_cashflow NODE
    Check next payday (2026-09-15):
    → Checking account balance: RM50,000
    → After next rent (RM1,200): RM48,800
    → After goal reserve (RM1,150): RM47,650
    → After other goals (RM500): RM47,150
    → After buffer protect: RM46,350 flexible
    → Next payday income: +RM8,000
    → Can afford contribution? YES
    
    Output: CashflowReconciliation {
      next_payday_feasible: true,
      required_reserve_sen: 115000,
      available_for_contribution_sen: 500000,
      conflict_details: ""
    }
    → Route to: compose_goal_response
    
11. GOAL GRAPH: compose_goal_response NODE
    LLM Call #2: Explain plan (if explain=true)
    Input: GOAL_RESPONSE_PROMPT + plan details
    Output: GoalExplanation {
      explanation: "This is achievable with your income level. You'll reach 
                    25% of your target by November, which gives you time to 
                    adjust if your income changes.",
      tradeoffs: [
        "Your emergency buffer becomes moderate (not high)",
        "Large discretionary purchases become harder to absorb"
      ]
    }
    
    Composite response:
    "To reach RM50,000 for your wedding by July 2027, 
     you need to save RM1,150 per payday.
     
     This is achievable with your income level. You'll reach 
     25% of your target by November, which gives you time to 
     adjust if your income changes.
     
     Your emergency buffer becomes moderate (not high).
     Large discretionary purchases become harder to absorb.
     
     Key milestones:
     · RM12,500 (25%) by November 2026
     · RM25,000 (50%) by February 2027
     · RM37,500 (75%) by May 2027
     · RM50,000 (100%) by July 2027"
    
12. ROUTE_AFTER_COMPOSE
    Is this a plan change (replan/edit)? No, it's create.
    → audit_goal_run
    
13. GOAL GRAPH: audit_goal_run NODE
    Record:
    {
      request_id: <UUID>,
      user_id: <UUID>,
      action: "create",
      goal_id: <NEW UUID>,
      applied_plan_version: 1,  # First version
      llm_calls: 2,  # intake + compose
      completed_at: <now>,
      success: true
    }
    
    Database writes:
    - INSERT Goal (target: 5000000, name: "Wedding Fund", ...)
    - INSERT GoalPlanRecord (version: 1, feasible: true, ...)
    - INSERT GoalMilestoneRecord × 4
    
14. RETURN TO BUTLER
    goal_workflow node receives result:
    - final_response: Complete explanation above
    - approval: None (no approval needed for simple create)
    - evidence_refs: [...]
    
15. BUTLER COMPOSES FINAL MESSAGE
    Adds:
    - Goal response above
    - Evidence row: "Wedding fund created"
    - Status: Complete
    
    → extract_memory (extract any preferences from convo)
    → END
    
16. USER RECEIVES
    "To reach RM50,000 for your wedding by July 2027, 
     you need to save RM1,150 per payday.
     
     [Full explanation and milestones above]"
```

---

## 7. Example: Plan Change (Replan/Edit)

### **User: "I found out my wedding moved to June. What changes?"**

```
1. Butler receives message
   → Detects: Goal replan needed
   → Extracts intent: action="replan", goal_reference="wedding"
   → Calls start_goal_planning with replan intent
   
2. goal_intake: Skip (structured intent provided)
   → output: GoalIntent { action: "replan", goal_reference: "wedding" }
   
3. resolve_goal_target:
   → Fuzzy match: "wedding" → finds goal_id
   → Load Goal from database
   → Extract current values
   → Update target_date: 2027-06-01 (instead of 2027-08-01)
   → Create GoalDefinition with new target_date
   
4-8. [Same as before: guard, snapshot, quality]
   
9. solve_goal_baseline:
   NEW CALCULATION:
   - Months until: 21 months (was 23)
   - Available: RM50,000 - RM12,500 already saved = RM37,500 left
   - Required: RM37,500 / 21 = RM1,786/month
   - Previous plan required: RM1,150/month
   - NEW PLAN REQUIRED: RM2,000+/month
   
   Risk changed: buffer_low (was buffer_moderate)
   
   Output: GoalPlan {
     feasible: true,  // But tight
     required_contribution_per_payday_sen: 231500,  # RM2,315 per payday
     risk_flags: ["buffer_low", "tight_timeline", "income_assumed_stable"],
     assumptions: ["Wedding moved 2 months earlier"]
   }
   
10. reconcile_short_term_cashflow:
    Available after commitments: RM46,350
    Required reserve: RM2,315
    Feasible? YES, but less comfortable
    → Route to: create_plan_change_draft (because this is a replan)
    
11. create_plan_change_draft:
    Store:
    - before: GoalPlan { version: 1, contribution: 1150 }
    - after: GoalPlan { version: 2, contribution: 2315 }
    - reason: "Goal target moved 2 months earlier (June 2027)"
    
    Create approval record:
    ButlerApproval {
      id: <UUID>
      approval_id: <UUID>,
      tool: "start_goal_planning",
      status: "pending",
      args: {
        before: { 
          required_contribution: 1150,
          projected_completion: 2027-07-15
        },
        after: {
          required_contribution: 2315,
          projected_completion: 2027-05-15,
          risk_flags: ["buffer_low"]
        },
        base_plan_version: 1
      }
    }
    
12. approval_interrupt:
    Execution pauses.
    User sees approval card:
    
    BEFORE:
    "RM1,150 per payday
     Reach by July 2027"
    
    AFTER:
    "RM2,315 per payday
     Reach by May 2027
     ⚠️ Your emergency buffer becomes low"
    
    Buttons: [ACCEPT] [EDIT] [REJECT]
    
13. USER CLICKS "ACCEPT"
    → POST /v1/butler/approvals/{approval_id}/respond
       { action: "accept" }
    
14. resume_goal_run():
    Command(resume={"action": "accept"})
    Resumes at approval_interrupt state
    
15. route_after_approval → "apply"
    
16. apply_goal_plan:
    Database writes:
    - INSERT GoalPlanRecord version 2 with approval_status="approved"
    - UPDATE Goal set current_plan_version=2
    - UPDATE ButlerApproval set status="approved"
    - CREATE AuditLog { action: "replan", applied_version: 2 }
    
17. audit_goal_run:
    Record completion
    
18. Return to Butler
    final_response: "Approved. Your wedding plan is now updated. 
                     You'll need to save RM2,315 per payday to reach 
                     your June 2027 deadline."
```

---

## 8. Key Architecture Insights

### **Trust Boundary**

```
┌─────────────────────────────────────────────────────────────┐
│  KIRA Goal Graph Trust Model                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  SAFE (No LLM Authority):                                  │
│  ✓ Database writes (Goal, GoalPlan, approval records)      │
│  ✓ Money calculations (all in Python engine)               │
│  ✓ Financial constraints (buffer, protected spending)      │
│  ✓ Scenario generation (deterministic alternatives)        │
│                                                             │
│  LLM ONLY (Interpretation & Explanation):                 │
│  • LLM Call #1: Parse user intent to GoalIntent            │
│    (No calculation, just schema validation)                │
│  • LLM Call #2: Explain plan (no numbers allowed)          │
│    (Python composes final message)                         │
│                                                             │
│  DETERMINISTIC ENGINE (Pure Python):                       │
│  → calculate_goal_feasibility()                            │
│  → calculate_goal_plan_for_contribution()                  │
│  → purchase_impact()                                       │
│  → create_scenarios()                                      │
│  → validate_goal_definition()                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### **LLM Call Budget**

| Flow | Calls | Why |
|------|-------|-----|
| Natural language create | 2 | intake + compose |
| Structured form create | 1 | compose only |
| Clarification loop | +1 per round | intake retry |
| Approval accept/reject | 0 | deterministic |
| Recalculate (income change) | 0 | Python only |
| Replan with change | 2 | intake + compose |

### **Version Control**

- Every plan is immutable: `GoalPlanRecord(version=1,2,3,...)`
- Approval compares against `base_plan_version` to detect stale data
- If stale: reject approval, reload financial snapshot, recalculate
- This prevents race conditions when user changes goals while planning

### **Checkpointing**

- GoalGraphState is fully checkpointed to PostgreSQL
- Allows pause at approval_interrupt() without losing calculation state
- Resume can come hours later; state reconstructed exactly
- Non-checkpointed context (session, model) provided at resume time

---

## 9. Error Handling & Resilience

### **Failure Modes**

| Scenario | Handling |
|----------|----------|
| User provides target_date in past | → clarification_response |
| No payday configured | → clarification_response (blocked) |
| Goal impossible with full income | → offer to split with partner or extend date |
| Protected commitments too high | → clarification_response (policy block) |
| Account balance query fails | → error logged, execution halts, user told |
| LLM call fails | → error logged, execution halts, user told |
| Base plan version stale | → reject approval, reload, recalculate |
| Database write fails | → transaction rolled back, error returned |

### **Recovery Paths**

- **Clarification Loop**: User provides missing info, flow restarts from intake
- **Approval Retry**: User clicks EDIT, flow restarts from snapshot with new params
- **Stale Version**: Reject old approval, automatic recalculation with fresh data

---

## 10. Summary: Full Pipeline

```
USER INPUT
    ↓
BUTLER AGENT (Detects goal intent)
    ↓
goal_workflow NODE (Butler bridge)
    ↓
GOAL GRAPH ENTRY: run_goal_request()
    ↓
goal_intake → resolve_target → policy → snapshot → quality
    ↓
solve_baseline → reconcile → [impact/scenarios/compose]
    ↓
[If change needed] create_draft → approval_interrupt (PAUSE)
    ↓ (User approves/edits/rejects)
[If approved] apply_plan ← If edited, restart from snapshot
    ↓
audit_goal_run
    ↓
Return to BUTLER COMPOSE
    ↓
final_response to USER
```

**Each stage is deterministic and replayable. The only LLM calls parse intent and explain results. All financial calculations are pure Python with full audit trail.**

