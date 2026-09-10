"""Structured model outputs and approval payloads for the goal graph."""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

GoalAction = Literal["create", "replan", "impact", "select_scenario", "recalculate"]
GoalType = Literal[
    "emergency_starter_fund",
    "upcoming_bill_annual_expense",
    "travel",
    "big_purchase",
    "wedding_event_deposit",
    "house_down_payment",
    "car_down_payment",
    "wedding_fund",
    "full_emergency_fund",
    "education_family_goal",
    "custom_goal",
]


def _json_integer(value: object) -> object:
    """Accept a schema integer quoted by a tool-calling provider.

    Only canonical base-10 integers are converted. Floats, formatted currency
    and arbitrary text still fail the strict field validation instead of being
    rounded or interpreted here.
    """
    if isinstance(value, str) and re.fullmatch(r"-?(?:0|[1-9]\d*)", value):
        return int(value)
    return value


class GoalIntent(BaseModel):
    """LLM call #1 output. It interprets; it never calculates."""

    action: GoalAction = "create"
    goal_id: uuid.UUID | None = None
    goal_reference: str | None = Field(default=None, max_length=80)
    goal_type: GoalType | None = None
    name: str | None = Field(default=None, max_length=80)
    target_amount_sen: int | None = Field(default=None, strict=True, gt=0)
    current_saved_sen: int | None = Field(default=None, strict=True, ge=0)
    target_date: date | None = None
    contribution_per_payday_sen: int | None = Field(default=None, strict=True, gt=0)
    funding_account_ids: list[uuid.UUID] = Field(default_factory=list)
    proposed_spend_sen: int | None = Field(default=None, strict=True, ge=0)
    scenario_id: uuid.UUID | None = None
    scenario_label: str | None = Field(default=None, max_length=60)
    wants_scenarios: bool = False
    missing_fields: list[str] = Field(default_factory=list)

    _normalise_json_integers = field_validator(
        "target_amount_sen",
        "current_saved_sen",
        "contribution_per_payday_sen",
        "proposed_spend_sen",
        mode="before",
    )(_json_integer)


class GoalExplanation(BaseModel):
    """LLM call #2 output. Python inserts every number around this prose."""

    explanation: str = Field(min_length=1, max_length=500)
    tradeoffs: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("explanation")
    @classmethod
    def explanation_has_no_financial_claims(cls, value: str) -> str:
        if re.search(r"\d|\bRM\b|\bMYR\b", value, re.I):
            raise ValueError("explanation must not restate or alter calculated figures")
        return value.strip()

    @field_validator("tradeoffs")
    @classmethod
    def tradeoffs_have_no_financial_claims(cls, values: list[str]) -> list[str]:
        if any(re.search(r"\d|\bRM\b|\bMYR\b", value, re.I) for value in values):
            raise ValueError("tradeoffs must not restate or alter calculated figures")
        return [value.strip() for value in values if value.strip()]


class GoalDataQuality(BaseModel):
    status: Literal["ready", "limited", "blocked"]
    issues: list[str] = Field(default_factory=list)


class PlanEdit(BaseModel):
    target_amount_sen: int | None = Field(default=None, strict=True, gt=0)
    current_saved_sen: int | None = Field(default=None, strict=True, ge=0)
    target_date: date | None = None
    contribution_per_payday_sen: int | None = Field(default=None, strict=True, gt=0)

    _normalise_json_integers = field_validator(
        "target_amount_sen",
        "current_saved_sen",
        "contribution_per_payday_sen",
        mode="before",
    )(_json_integer)


class ApprovalDecision(BaseModel):
    action: Literal["accept", "edit", "reject"]
    edit: PlanEdit | None = None
