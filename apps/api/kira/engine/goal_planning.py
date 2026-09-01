"""Pure, deterministic savings-goal planning.

Every monetary value is an integer count of sen.  This module has no database,
clock, network, or model dependency: callers provide the complete financial
snapshot and get the same answer for the same calculation version and inputs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

CALCULATION_VERSION = "goal-plan-v1"

SHORT_TERM_GOAL_TYPES = frozenset(
    {
        "emergency_starter_fund",
        "upcoming_bill_annual_expense",
        "travel",
        "big_purchase",
        "wedding_event_deposit",
    }
)
LONG_TERM_GOAL_TYPES = frozenset(
    {
        "house_down_payment",
        "car_down_payment",
        "wedding_fund",
        "full_emergency_fund",
        "education_family_goal",
        "custom_goal",
    }
)
GOAL_TYPES = SHORT_TERM_GOAL_TYPES | LONG_TERM_GOAL_TYPES
GOAL_PRIORITIES = frozenset({"protected", "important", "flexible"})
GOAL_STATUSES = frozenset(
    {"draft", "active", "at_risk", "needs_replan", "paused", "achieved", "cancelled"}
)
DATA_CONFIDENCE_LEVELS = frozenset({"low", "medium", "high"})


def _require_int(name: str, value: int, *, minimum: int | None = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be integer sen")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")


def _ceil_div(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return -(-numerator // denominator)


@dataclass(frozen=True, slots=True)
class GoalDefinition:
    goal_id: str
    user_id: str
    goal_type: str
    name: str
    currency: str
    target_amount_sen: int
    current_saved_sen: int
    target_date: date
    priority: str
    status: str
    funding_account_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AccountBalance:
    account_id: str
    balance_sen: int
    evidence_ref: str

    def __post_init__(self) -> None:
        _require_int("balance_sen", self.balance_sen, minimum=None)


@dataclass(frozen=True, slots=True)
class IncomePayday:
    payday_date: date
    amount_sen: int | None
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        if self.amount_sen is not None:
            _require_int("amount_sen", self.amount_sen)


@dataclass(frozen=True, slots=True)
class ProtectedCommitment:
    commitment_id: str
    name: str
    amount_sen: int
    due_date: date
    protected: bool
    evidence_ref: str

    def __post_init__(self) -> None:
        _require_int("amount_sen", self.amount_sen)


@dataclass(frozen=True, slots=True)
class ActiveGoalReserve:
    goal_id: str
    next_required_reserve_sen: int
    priority: str

    def __post_init__(self) -> None:
        _require_int("next_required_reserve_sen", self.next_required_reserve_sen)


@dataclass(frozen=True, slots=True)
class FinancialSnapshot:
    user_id: str
    as_of_utc: datetime
    currency: str
    cash_available_sen: int
    accounts: tuple[AccountBalance, ...]
    next_income_payday: IncomePayday
    commitments: tuple[ProtectedCommitment, ...]
    emergency_buffer_sen: int
    active_goal_plans: tuple[ActiveGoalReserve, ...]
    data_confidence: str
    evidence_refs: tuple[str, ...]
    pay_cycle_days: int = 30

    def __post_init__(self) -> None:
        _require_int("cash_available_sen", self.cash_available_sen, minimum=None)
        _require_int("emergency_buffer_sen", self.emergency_buffer_sen)
        if self.as_of_utc.tzinfo is None or self.as_of_utc.utcoffset() is None:
            raise ValueError("as_of_utc must be timezone-aware")
        if self.data_confidence not in DATA_CONFIDENCE_LEVELS:
            raise ValueError(f"unknown data confidence: {self.data_confidence}")
        if isinstance(self.pay_cycle_days, bool) or not isinstance(self.pay_cycle_days, int):
            raise TypeError("pay_cycle_days must be an int")
        if self.pay_cycle_days <= 0:
            raise ValueError("pay_cycle_days must be positive")


@dataclass(frozen=True, slots=True)
class GoalContribution:
    payday: date
    amount_sen: int

    def __post_init__(self) -> None:
        _require_int("amount_sen", self.amount_sen)


@dataclass(frozen=True, slots=True)
class GoalMilestone:
    percentage: int
    amount_sen: int
    projected_date: date


@dataclass(frozen=True, slots=True)
class GoalPlan:
    goal_id: str
    feasible: bool
    target_amount_sen: int
    current_saved_sen: int
    remaining_amount_sen: int
    target_date: date
    required_contribution_per_payday_sen: int
    next_required_reserve_sen: int
    projected_completion_date: date | None
    milestones: tuple[GoalMilestone, ...]
    risk_flags: tuple[str, ...]
    assumptions: tuple[str, ...]
    calculation_version: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoalScenario:
    scenario_id: str
    goal_id: str
    label: str
    feasible: bool
    contribution_per_payday_sen: int
    target_date: date
    goal_delay_days: int
    flexible_spending_delta_sen: int
    tradeoffs: tuple[str, ...]
    risk_flags: tuple[str, ...]
    calculation_version: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CashflowReconciliation:
    goal_id: str
    safe_for_next_payday: bool
    cash_available_sen: int
    protected_commitments_sen: int
    emergency_buffer_sen: int
    other_goal_reserves_sen: int
    next_goal_reserve_sen: int
    flexible_cash_after_reserves_sen: int
    shortfall_sen: int
    risk_flags: tuple[str, ...]
    calculation_version: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoalImpact:
    goal_id: str
    proposed_spend_sen: int
    safe_to_spend: bool
    protected_money_touched: bool
    goal_reserve_shortfall_sen: int
    projected_completion_date: date | None
    goal_delay_days: int
    flexible_spending_remaining_sen: int
    risk_flags: tuple[str, ...]
    assumptions: tuple[str, ...]
    calculation_version: str
    evidence_refs: tuple[str, ...]


def validate_goal_definition(goal: GoalDefinition, *, as_of_date: date | None = None) -> None:
    """Validate a goal without changing or normalising caller data."""
    if not goal.goal_id or not goal.user_id:
        raise ValueError("goal_id and user_id are required")
    if goal.goal_type not in GOAL_TYPES:
        raise ValueError(f"unsupported goal_type: {goal.goal_type}")
    if not goal.name.strip():
        raise ValueError("goal name is required")
    if len(goal.currency) != 3 or not goal.currency.isalpha() or not goal.currency.isupper():
        raise ValueError("currency must be a three-letter uppercase ISO code")
    _require_int("target_amount_sen", goal.target_amount_sen, minimum=1)
    _require_int("current_saved_sen", goal.current_saved_sen)
    if goal.priority not in GOAL_PRIORITIES:
        raise ValueError(f"unsupported priority: {goal.priority}")
    if goal.status not in GOAL_STATUSES:
        raise ValueError(f"unsupported status: {goal.status}")
    if as_of_date is not None and goal.target_date < as_of_date and goal.status != "achieved":
        raise ValueError("target_date cannot be in the past for an unfinished goal")
    if any(not account_id for account_id in goal.funding_account_ids):
        raise ValueError("funding_account_ids cannot contain an empty id")


def classify_goal_horizon(goal: GoalDefinition, as_of_date: date) -> str:
    """Display classification only; the solver always uses the actual dates."""
    return "short" if (goal.target_date - as_of_date).days <= 365 else "long"


def _next_payday(snapshot: FinancialSnapshot) -> date:
    payday = snapshot.next_income_payday.payday_date
    as_of = snapshot.as_of_utc.astimezone(UTC).date()
    while payday < as_of:
        payday += timedelta(days=snapshot.pay_cycle_days)
    return payday


def _paydays_through(snapshot: FinancialSnapshot, through: date) -> tuple[date, ...]:
    payday = _next_payday(snapshot)
    result: list[date] = []
    while payday <= through:
        result.append(payday)
        payday += timedelta(days=snapshot.pay_cycle_days)
    return tuple(result)


def calculate_required_contribution(goal: GoalDefinition, snapshot: FinancialSnapshot) -> int:
    """Return the smallest whole-sen contribution needed on each payday."""
    validate_goal_definition(goal, as_of_date=snapshot.as_of_utc.astimezone(UTC).date())
    if goal.currency != snapshot.currency:
        raise ValueError("goal and snapshot currencies differ")
    remaining = max(0, goal.target_amount_sen - goal.current_saved_sen)
    if remaining == 0:
        return 0
    paydays = _paydays_through(snapshot, goal.target_date)
    if not paydays:
        return remaining
    return _ceil_div(remaining, len(paydays))


def build_goal_contribution_schedule(
    goal: GoalDefinition,
    snapshot: FinancialSnapshot,
    contribution_per_payday_sen: int | None = None,
) -> tuple[GoalContribution, ...]:
    """Build the target-bound schedule, with the last payment trimmed exactly."""
    contribution = (
        calculate_required_contribution(goal, snapshot)
        if contribution_per_payday_sen is None
        else contribution_per_payday_sen
    )
    _require_int("contribution_per_payday_sen", contribution)
    remaining = max(0, goal.target_amount_sen - goal.current_saved_sen)
    if remaining == 0 or contribution == 0:
        return ()
    schedule: list[GoalContribution] = []
    for payday in _paydays_through(snapshot, goal.target_date):
        amount = min(contribution, remaining)
        schedule.append(GoalContribution(payday, amount))
        remaining -= amount
        if remaining == 0:
            break
    return tuple(schedule)


def calculate_projected_completion_date(
    goal: GoalDefinition,
    snapshot: FinancialSnapshot,
    contribution_per_payday_sen: int,
    *,
    first_contribution_sen: int | None = None,
) -> date | None:
    """Project completion on the real repeating payday cadence."""
    _require_int("contribution_per_payday_sen", contribution_per_payday_sen)
    if first_contribution_sen is not None:
        _require_int("first_contribution_sen", first_contribution_sen)
    remaining = max(0, goal.target_amount_sen - goal.current_saved_sen)
    if remaining == 0:
        return snapshot.as_of_utc.astimezone(UTC).date()
    if contribution_per_payday_sen == 0:
        return None
    first = min(
        remaining,
        contribution_per_payday_sen if first_contribution_sen is None else first_contribution_sen,
    )
    remaining -= first
    payments_after_first = _ceil_div(remaining, contribution_per_payday_sen) if remaining else 0
    return _next_payday(snapshot) + timedelta(days=snapshot.pay_cycle_days * payments_after_first)


def _commitments_due_before_next_payday(snapshot: FinancialSnapshot) -> int:
    as_of = snapshot.as_of_utc.astimezone(UTC).date()
    payday = _next_payday(snapshot)
    return sum(
        commitment.amount_sen
        for commitment in snapshot.commitments
        if as_of <= commitment.due_date <= payday
    )


def _other_goal_reserves(snapshot: FinancialSnapshot, goal_id: str) -> int:
    return sum(
        plan.next_required_reserve_sen
        for plan in snapshot.active_goal_plans
        if plan.goal_id != goal_id
    )


def _available_before_goal(snapshot: FinancialSnapshot, goal_id: str) -> int:
    return max(
        0,
        snapshot.cash_available_sen
        - snapshot.emergency_buffer_sen
        - _commitments_due_before_next_payday(snapshot)
        - _other_goal_reserves(snapshot, goal_id),
    )


def _payday_capacity(snapshot: FinancialSnapshot, goal_id: str, payday: date) -> int | None:
    income = snapshot.next_income_payday.amount_sen
    if income is None:
        return None
    next_payday = payday + timedelta(days=snapshot.pay_cycle_days)
    cycle_commitments = sum(
        commitment.amount_sen
        for commitment in snapshot.commitments
        if payday < commitment.due_date <= next_payday
    )
    return max(
        0,
        income - cycle_commitments - _other_goal_reserves(snapshot, goal_id),
    )


def _minimum_payday_capacity(
    snapshot: FinancialSnapshot, goal_id: str, through: date
) -> int | None:
    capacities = [
        _payday_capacity(snapshot, goal_id, payday)
        for payday in _paydays_through(snapshot, through)
    ]
    if not capacities or any(capacity is None for capacity in capacities):
        return None
    return min(capacity for capacity in capacities if capacity is not None)


def _milestones(
    goal: GoalDefinition, snapshot: FinancialSnapshot, contribution_sen: int
) -> tuple[GoalMilestone, ...]:
    as_of = snapshot.as_of_utc.astimezone(UTC).date()
    result: list[GoalMilestone] = []
    for percentage in (25, 50, 75, 100):
        amount = _ceil_div(goal.target_amount_sen * percentage, 100)
        needed = max(0, amount - goal.current_saved_sen)
        if needed == 0:
            projected = as_of
        elif contribution_sen == 0:
            projected = goal.target_date
        else:
            payments = _ceil_div(needed, contribution_sen)
            projected = _next_payday(snapshot) + timedelta(
                days=snapshot.pay_cycle_days * (payments - 1)
            )
        result.append(GoalMilestone(percentage, amount, projected))
    return tuple(result)


def calculate_goal_feasibility(goal: GoalDefinition, snapshot: FinancialSnapshot) -> GoalPlan:
    """Calculate a conservative goal plan without borrowing protected money."""
    as_of = snapshot.as_of_utc.astimezone(UTC).date()
    validate_goal_definition(goal, as_of_date=as_of)
    if goal.user_id != snapshot.user_id:
        raise ValueError("goal and snapshot users differ")
    if goal.currency != snapshot.currency:
        raise ValueError("goal and snapshot currencies differ")

    remaining = max(0, goal.target_amount_sen - goal.current_saved_sen)
    paydays = _paydays_through(snapshot, goal.target_date)
    required = calculate_required_contribution(goal, snapshot)
    next_reserve = min(remaining, required)
    available_now = _available_before_goal(snapshot, goal.goal_id)
    recurring_capacity = _minimum_payday_capacity(snapshot, goal.goal_id, goal.target_date)
    risks: list[str] = []
    assumptions = [
        f"paydays repeat every {snapshot.pay_cycle_days} days from "
        f"{snapshot.next_income_payday.payday_date.isoformat()}",
        "confirmed cash, commitments, and account records are used",
        "emergency buffer and near-term commitments remain reserved",
    ]

    if remaining == 0:
        feasible = True
        risks.append("goal_already_achieved")
    elif not paydays:
        feasible = available_now >= remaining
        risks.append("target_before_next_payday")
        if not feasible:
            risks.append("insufficient_near_term_cashflow")
    else:
        # Confirmed cash can fund some or all of the goal. Unknown future income
        # never becomes an invented positive number.
        cash_covers_goal = available_now >= remaining
        schedule = build_goal_contribution_schedule(goal, snapshot, required)
        first_payday_capacity = _payday_capacity(snapshot, goal.goal_id, paydays[0])
        first_capacity = available_now + (first_payday_capacity or 0)
        first_safe = first_capacity >= schedule[0].amount_sen
        future_safe = cash_covers_goal or all(
            (capacity := _payday_capacity(snapshot, goal.goal_id, item.payday)) is not None
            and capacity >= item.amount_sen
            for item in schedule[1:]
        )
        feasible = first_safe and future_safe
        if not first_safe:
            risks.append("insufficient_near_term_cashflow")
        if recurring_capacity is None and not cash_covers_goal:
            risks.append("income_amount_unavailable")
            assumptions.append("future income amount is unknown and counted as zero")
        elif (
            recurring_capacity is not None
            and recurring_capacity < required
            and not cash_covers_goal
        ):
            risks.append("insufficient_future_payday_capacity")

    if snapshot.data_confidence == "low":
        risks.append("low_data_confidence")
    projected = calculate_projected_completion_date(goal, snapshot, required)
    if projected is not None and projected > goal.target_date:
        risks.append("projected_after_target")
        feasible = False

    return GoalPlan(
        goal_id=goal.goal_id,
        feasible=feasible,
        target_amount_sen=goal.target_amount_sen,
        current_saved_sen=goal.current_saved_sen,
        remaining_amount_sen=remaining,
        target_date=goal.target_date,
        required_contribution_per_payday_sen=required,
        next_required_reserve_sen=next_reserve,
        projected_completion_date=projected,
        milestones=_milestones(goal, snapshot, required),
        risk_flags=tuple(dict.fromkeys(risks)),
        assumptions=tuple(assumptions),
        calculation_version=CALCULATION_VERSION,
        evidence_refs=snapshot.evidence_refs,
    )


def calculate_goal_plan_for_contribution(
    goal: GoalDefinition,
    snapshot: FinancialSnapshot,
    contribution_per_payday_sen: int,
    *,
    target_date: date | None = None,
) -> GoalPlan:
    """Build a complete plan for a user-selected deterministic contribution."""
    _require_int("contribution_per_payday_sen", contribution_per_payday_sen)
    effective = replace(goal, target_date=target_date or goal.target_date)
    validate_goal_definition(effective, as_of_date=snapshot.as_of_utc.astimezone(UTC).date())
    if effective.user_id != snapshot.user_id:
        raise ValueError("goal and snapshot users differ")
    if effective.currency != snapshot.currency:
        raise ValueError("goal and snapshot currencies differ")

    remaining = max(0, effective.target_amount_sen - effective.current_saved_sen)
    projected = calculate_projected_completion_date(
        effective, snapshot, contribution_per_payday_sen
    )
    schedule_target = projected or effective.target_date
    schedule = build_goal_contribution_schedule(
        replace(effective, target_date=schedule_target),
        snapshot,
        contribution_per_payday_sen=contribution_per_payday_sen,
    )
    available_now = _available_before_goal(snapshot, effective.goal_id)
    cash_covers = available_now >= remaining
    first_safe = bool(schedule) and (
        available_now + (_payday_capacity(snapshot, effective.goal_id, schedule[0].payday) or 0)
        >= schedule[0].amount_sen
    )
    future_safe = all(
        (capacity := _payday_capacity(snapshot, effective.goal_id, item.payday)) is not None
        and capacity >= item.amount_sen
        for item in schedule[1:]
    )
    feasible = remaining == 0 or (
        contribution_per_payday_sen > 0
        and bool(schedule)
        and (cash_covers or (first_safe and future_safe))
    )
    risks: list[str] = []
    assumptions = [
        f"paydays repeat every {snapshot.pay_cycle_days} days from "
        f"{_next_payday(snapshot).isoformat()}",
        "the selected per-payday contribution is fixed",
        "confirmed cash, commitments, and account records are used",
        "emergency buffer and near-term commitments remain reserved",
    ]
    if remaining == 0:
        risks.append("goal_already_achieved")
    elif contribution_per_payday_sen == 0:
        risks.append("no_positive_contribution")
    if not feasible:
        risks.append("contribution_exceeds_confirmed_capacity")
    if snapshot.next_income_payday.amount_sen is None and not cash_covers:
        risks.append("income_amount_unavailable")
        assumptions.append("future income amount is unknown and counted as zero")
    if projected is not None and projected > effective.target_date:
        risks.append("projected_after_target")
        feasible = False
    if snapshot.data_confidence == "low":
        risks.append("low_data_confidence")
    return GoalPlan(
        goal_id=effective.goal_id,
        feasible=feasible,
        target_amount_sen=effective.target_amount_sen,
        current_saved_sen=effective.current_saved_sen,
        remaining_amount_sen=remaining,
        target_date=effective.target_date,
        required_contribution_per_payday_sen=contribution_per_payday_sen,
        next_required_reserve_sen=min(remaining, contribution_per_payday_sen),
        projected_completion_date=projected,
        milestones=_milestones(effective, snapshot, contribution_per_payday_sen),
        risk_flags=tuple(dict.fromkeys(risks)),
        assumptions=tuple(assumptions),
        calculation_version=CALCULATION_VERSION,
        evidence_refs=snapshot.evidence_refs,
    )


def _scenario(
    goal: GoalDefinition,
    snapshot: FinancialSnapshot,
    label: str,
    contribution: int,
    baseline: GoalPlan,
    tradeoffs: tuple[str, ...],
) -> GoalScenario:
    projected = calculate_projected_completion_date(goal, snapshot, contribution)
    target = projected or goal.target_date
    delay = max(0, (target - goal.target_date).days)
    available_now = _available_before_goal(snapshot, goal.goal_id)
    cash_covers = available_now >= baseline.remaining_amount_sen
    scenario_goal = replace(goal, target_date=target)
    schedule = build_goal_contribution_schedule(
        scenario_goal, snapshot, contribution_per_payday_sen=contribution
    )
    first_capacity = _available_before_goal(snapshot, goal.goal_id) + (
        (_payday_capacity(snapshot, goal.goal_id, schedule[0].payday) or 0) if schedule else 0
    )
    future_safe = all(
        (capacity := _payday_capacity(snapshot, goal.goal_id, item.payday)) is not None
        and capacity >= item.amount_sen
        for item in schedule[1:]
    )
    feasible = (
        contribution > 0
        and bool(schedule)
        and (cash_covers or (first_capacity >= schedule[0].amount_sen and future_safe))
    )
    risks: list[str] = []
    if projected is None:
        risks.append("no_positive_contribution")
        feasible = False
    if delay:
        risks.append("target_date_delayed")
    if not feasible:
        risks.append("contribution_exceeds_confirmed_capacity")
    scenario_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"kira:{CALCULATION_VERSION}:{goal.goal_id}:{label}:{contribution}:{target.isoformat()}",
        )
    )
    return GoalScenario(
        scenario_id=scenario_id,
        goal_id=goal.goal_id,
        label=label,
        feasible=feasible,
        contribution_per_payday_sen=contribution,
        target_date=target,
        goal_delay_days=delay,
        flexible_spending_delta_sen=baseline.required_contribution_per_payday_sen - contribution,
        tradeoffs=tradeoffs,
        risk_flags=tuple(risks),
        calculation_version=CALCULATION_VERSION,
        evidence_refs=snapshot.evidence_refs,
    )


def generate_goal_scenarios(
    goal: GoalDefinition, snapshot: FinancialSnapshot
) -> tuple[GoalScenario, ...]:
    """Return three reproducible alternatives: on-time, cash-safe, accelerated."""
    baseline = calculate_goal_feasibility(goal, snapshot)
    required = baseline.required_contribution_per_payday_sen
    recurring = _minimum_payday_capacity(snapshot, goal.goal_id, goal.target_date)
    confirmed_capacity = _available_before_goal(snapshot, goal.goal_id)
    if recurring is not None:
        confirmed_capacity = max(confirmed_capacity, recurring)
    cash_safe = min(required, confirmed_capacity)
    accelerated = required + _ceil_div(required, 4) if required else 0
    return (
        _scenario(
            goal,
            snapshot,
            "On-time target",
            required,
            baseline,
            ("Meets the requested date when confirmed cash flow supports it.",),
        ),
        _scenario(
            goal,
            snapshot,
            "Cash-flow-safe",
            cash_safe,
            baseline,
            ("Preserves confirmed near-term commitments and the emergency buffer.",),
        ),
        _scenario(
            goal,
            snapshot,
            "Accelerated",
            accelerated,
            baseline,
            ("Uses 25% more per payday and leaves less flexible spending.",),
        ),
    )


def reconcile_goal_with_short_term_cashflow(
    snapshot: FinancialSnapshot, goal_plan: GoalPlan
) -> CashflowReconciliation:
    """Reserve bills, buffer and other goals before considering this goal."""
    commitments = _commitments_due_before_next_payday(snapshot)
    other_goals = _other_goal_reserves(snapshot, goal_plan.goal_id)
    protected_total = snapshot.emergency_buffer_sen + commitments + other_goals
    after_protected = max(0, snapshot.cash_available_sen - protected_total)
    flexible = max(0, after_protected - goal_plan.next_required_reserve_sen)
    shortfall = max(0, goal_plan.next_required_reserve_sen - after_protected)
    risks: list[str] = []
    if snapshot.cash_available_sen < snapshot.emergency_buffer_sen:
        risks.append("emergency_buffer_underfunded")
    if snapshot.cash_available_sen < snapshot.emergency_buffer_sen + commitments:
        risks.append("protected_commitments_underfunded")
    if shortfall:
        risks.append("goal_reserve_shortfall")
    return CashflowReconciliation(
        goal_id=goal_plan.goal_id,
        safe_for_next_payday=shortfall == 0 and not risks,
        cash_available_sen=snapshot.cash_available_sen,
        protected_commitments_sen=commitments,
        emergency_buffer_sen=snapshot.emergency_buffer_sen,
        other_goal_reserves_sen=other_goals,
        next_goal_reserve_sen=goal_plan.next_required_reserve_sen,
        flexible_cash_after_reserves_sen=flexible,
        shortfall_sen=shortfall,
        risk_flags=tuple(risks),
        calculation_version=CALCULATION_VERSION,
        evidence_refs=snapshot.evidence_refs,
    )


def evaluate_goal_impact(
    proposed_spend_sen: int, snapshot: FinancialSnapshot, goal_plan: GoalPlan
) -> GoalImpact:
    """Evaluate a hypothetical purchase without changing any persisted fact."""
    _require_int("proposed_spend_sen", proposed_spend_sen)
    reconciliation = reconcile_goal_with_short_term_cashflow(snapshot, goal_plan)
    protected_floor = (
        reconciliation.emergency_buffer_sen
        + reconciliation.protected_commitments_sen
        + reconciliation.other_goal_reserves_sen
    )
    cash_after = snapshot.cash_available_sen - proposed_spend_sen
    protected_touched = cash_after < protected_floor
    amount_left_for_this_goal = max(0, cash_after - protected_floor)
    first_contribution = min(goal_plan.next_required_reserve_sen, amount_left_for_this_goal)
    shortfall = goal_plan.next_required_reserve_sen - first_contribution
    flexible_remaining = max(0, amount_left_for_this_goal - goal_plan.next_required_reserve_sen)

    # Recreate only the fields needed by the pure projection. The plan carries
    # the saved/target facts, while the snapshot supplies the payday cadence.
    impact_goal = GoalDefinition(
        goal_id=goal_plan.goal_id,
        user_id=snapshot.user_id,
        goal_type="custom_goal",
        name="Impact projection",
        currency=snapshot.currency,
        target_amount_sen=goal_plan.target_amount_sen,
        current_saved_sen=goal_plan.current_saved_sen,
        target_date=goal_plan.target_date,
        priority="flexible",
        status="active",
    )
    projected = calculate_projected_completion_date(
        impact_goal,
        snapshot,
        goal_plan.required_contribution_per_payday_sen,
        first_contribution_sen=first_contribution,
    )
    baseline = goal_plan.projected_completion_date
    delay = max(0, (projected - baseline).days) if projected and baseline else 0
    risks: list[str] = []
    if protected_touched:
        risks.append("protected_money_would_be_used")
    if shortfall:
        risks.append("goal_reserve_reduced")
    if delay:
        risks.append("goal_completion_delayed")
    return GoalImpact(
        goal_id=goal_plan.goal_id,
        proposed_spend_sen=proposed_spend_sen,
        safe_to_spend=not protected_touched and shortfall == 0,
        protected_money_touched=protected_touched,
        goal_reserve_shortfall_sen=shortfall,
        projected_completion_date=projected,
        goal_delay_days=delay,
        flexible_spending_remaining_sen=flexible_remaining,
        risk_flags=tuple(risks),
        assumptions=("the purchase is hypothetical and no records are changed",),
        calculation_version=CALCULATION_VERSION,
        evidence_refs=snapshot.evidence_refs,
    )


def with_target_date(goal: GoalDefinition, target_date: date) -> GoalDefinition:
    """Small explicit helper for deterministic target-date what-if tests/callers."""
    return replace(goal, target_date=target_date)
