"""Wire shapes. Money crosses the wire as an integer sen field named *_sen."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(min_length=1, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(ResponseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(ResponseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    currency: str
    buffer_sen: int
    next_payday: date
    cycle_start: date
    cycle_days: int


class NextCommitmentResponse(ResponseModel):
    id: uuid.UUID
    name: str
    amount_sen: int
    due_date: date
    days_until: int
    protected: bool


class GoalSummaryResponse(ResponseModel):
    id: uuid.UUID
    name: str
    horizon: str
    target_sen: int
    saved_sen: int
    monthly_sen: int
    months_left: int
    note: str


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
GoalPriority = Literal["protected", "important", "flexible"]
GoalStatus = Literal[
    "draft", "active", "at_risk", "needs_replan", "paused", "achieved", "cancelled"
]


class GoalCreateRequest(BaseModel):
    goal_type: GoalType
    name: str = Field(min_length=1, max_length=80)
    target_amount_sen: int = Field(strict=True, gt=0)
    current_saved_sen: int = Field(default=0, strict=True, ge=0)
    target_date: date
    priority: GoalPriority = "flexible"
    funding_account_ids: list[uuid.UUID] = Field(default_factory=list)


class GoalDetailResponse(ResponseModel):
    goal_id: uuid.UUID
    user_id: uuid.UUID
    goal_type: GoalType
    name: str
    currency: str
    target_amount_sen: int
    current_saved_sen: int
    target_date: date | None
    horizon: Literal["short", "long"]
    priority: GoalPriority
    status: GoalStatus
    funding_account_ids: list[uuid.UUID]
    current_plan_version: int | None = None


class GoalMilestoneResponse(ResponseModel):
    percentage: int
    amount_sen: int
    projected_date: date


class GoalPlanResponse(ResponseModel):
    plan_id: uuid.UUID
    goal_id: uuid.UUID
    version: int
    approval_status: Literal["draft", "approved", "superseded"]
    feasible: bool
    target_amount_sen: int
    current_saved_sen: int
    remaining_amount_sen: int
    target_date: date
    required_contribution_per_payday_sen: int
    next_required_reserve_sen: int
    projected_completion_date: date | None
    milestones: list[GoalMilestoneResponse]
    risk_flags: list[str]
    assumptions: list[str]
    calculation_version: str
    evidence_refs: list[str]


class GoalCreateResponse(ResponseModel):
    goal: GoalDetailResponse
    plan: GoalPlanResponse


class GoalScenarioResponse(ResponseModel):
    scenario_id: uuid.UUID
    goal_id: uuid.UUID
    label: str
    feasible: bool
    contribution_per_payday_sen: int
    target_date: date
    goal_delay_days: int
    flexible_spending_delta_sen: int
    tradeoffs: list[str]
    risk_flags: list[str]
    calculation_version: str
    evidence_refs: list[str]


class GoalScenariosResponse(ResponseModel):
    scenarios: list[GoalScenarioResponse]


class GoalImpactRequest(BaseModel):
    proposed_spend_sen: int = Field(strict=True, ge=0)


class GoalImpactResponse(ResponseModel):
    goal_id: uuid.UUID
    proposed_spend_sen: int
    safe_to_spend: bool
    protected_money_touched: bool
    goal_reserve_shortfall_sen: int
    projected_completion_date: date | None
    goal_delay_days: int
    flexible_spending_remaining_sen: int
    risk_flags: list[str]
    assumptions: list[str]
    calculation_version: str
    evidence_refs: list[str]


class PlaceResponse(ResponseModel):
    """One outing, priced on the distance named by ``distance_basis``.

    A fare is charged on the road, so ``km`` is the road distance whenever the
    router answered for this place. Where it did not, ``km`` falls back to the
    great circle, ``road_km`` is null, and ``distance_basis`` says
    ``straight_line`` -- which the screen has to show, because a straight-line
    ride fare in Kuala Lumpur can be half of the real one. The basis is
    per-place: one search routes some destinations and fails on others.

    ``match_basis`` is the other thing a row must not be read without. A search
    matches what OpenStreetMap states about a place, and also what a model
    believes it serves beyond that, so a chicken search reaches the McDonald's
    that OSM only ever calls a burger shop. Those are not the same kind of truth
    and a client may not have to guess between them: ``tagged`` is the map
    stating the cuisine, ``inferred`` is a belief about the menu recorded when
    the data was built, ``judged`` is a model reading this search's own request
    and saying this place answers it with nothing in the data to point at, and
    null is nothing having been asked for. A screen that drew any of the last
    two exactly like a tagged one would be presenting a guess as a fact --
    which is the one thing a wider list must not buy.

    ``match_strength`` is how well that model thought this place answers the
    request, and it is null on every row nothing judged -- which is every row
    while ``DayPlanResponse.ranking`` says ``deterministic``, because a word
    either matched or it did not and there is no degree in that.

    ``match_reason`` is why this row is here, in words that can be printed as
    they stand: "Tagged chicken", "Also serves chicken", "The model thinks this
    serves beef". Empty where nothing matched. It exists because a row otherwise
    cannot explain itself -- a place labelled Dessert answering a search for
    chicken is either a good answer or a bug, and the category alone does not
    say which. Every word of it is the server's; the model contributes at most
    the name of a food.
    """

    id: str
    name: str
    kind: str
    address: str
    # The point itself, because the address alone does not always find it: a
    # quarter of them name a locality rather than a doorstep, and several names
    # in the set belong to two branches. A client sending the user to a map has
    # to be able to send them to this one.
    lat: float
    lng: float
    km: float
    road_km: float | None
    distance_basis: Literal["road", "straight_line"]
    travel_sen: int
    minutes: int
    total_sen: int
    # Null on a day with no room left, so no client can turn a stand-in ratio
    # into a percentage or divide its way back to a room that is not there.
    share: float | None
    band: Literal["ok", "tight", "over"]
    confidence: str
    halal: bool
    note: str
    # Null on every row of a list nobody narrowed, and on every near miss: those
    # matched nothing, so there is no basis to state. Required rather than
    # optional for the same reason ``nearest_over_cap`` is -- a field a client
    # may find missing is a field a client will forget to read.
    match_basis: Literal["tagged", "inferred", "judged"] | None
    match_strength: Literal["strong", "weak"] | None
    match_reason: str


class DayPlanResponse(ResponseModel):
    """The places, and the figures they were judged against.

    ``room_sen`` is stated rather than left to be inferred from ``share``: it
    is zero on a day already spent out, and a client dividing to recover it
    would turn that zero into a number the user never had.

    ``nearby_count`` is how many places the radius held before any filter ran,
    ``matching_count`` how many were still standing after the halal filter, and
    ``kind_count`` how many of those were the kind of food that was asked for —
    all three before the ceiling. Without them, an empty ``places`` is
    unreadable: a client would have to guess which of four causes emptied it,
    and would blame the ceiling for a distance no ceiling can close, for a
    halal toggle no ceiling can reach, or for there being no noodles in this
    part of town. The counts nest, so the first of them that is nil is the
    cause.

    ``kind`` is the food filter this list was actually built with, echoed back.
    Null means none was asked for. A client reads it rather than its own state
    for the same reason it reads ``cap_sen``: while a newly tapped filter is in
    flight, its own state describes a list that has not arrived yet. It is also
    the word every row's ``match_basis`` is about — a row saying ``inferred``
    is saying it was kept for this kind on a belief rather than on a tag, and
    the word that belief is about is the one here.

    ``kind_count`` counts every sort of match, because all of them are in
    ``places``. Where ``ranking`` is ``deterministic`` it is still the ``kind``
    row of the price landscape and still the number of places a search for that
    word returns; where a model ranked instead, it is how many places the model
    kept. Which of them rest on a tag and which on a guess is on the rows
    themselves and nowhere else.

    ``nearest_over_cap`` is the cheapest few places the ceiling turned away, and
    it is only ever non-empty when ``places`` is empty. It is a separate field
    rather than extra rows in ``places`` precisely so that no client can render
    it as though it had fitted: every place in it costs more than ``cap_sen``,
    each carries ``band: "over"`` to say so on the row itself, and a client that
    shows them owes the user a heading that says what they are. Every other
    filter still holds over it — halal is still halal and ``kind`` is still that
    kind — so the ceiling is the only thing relaxed, and only to say what the
    money would have to stretch to.
    """

    room_sen: int
    cap_sen: int
    kind: str | None
    nearby_count: int
    matching_count: int
    kind_count: int
    # Which of the two narrowed this list. ``deterministic`` is the kind filter
    # above; ``model`` is a model having read the request itself. Stated because
    # the two are not equally good and the difference cannot be seen in a list
    # of places: a client that cannot say "I could not reach my model, so this
    # is the word filter" will say nothing, and a search that quietly fell back
    # to matching two dozen cuisine tags looks exactly like one that did not.
    ranking: Literal["model", "deterministic"]
    places: list[PlaceResponse]
    # Required rather than optional, and empty on almost every response. A field
    # a client may find missing is a field a client will forget to read, and the
    # one list it must never quietly omit is this one.
    nearest_over_cap: list[PlaceResponse]


class PlanDraftRequest(BaseModel):
    """A place the user tapped "Add to today" on, as the row showed it.

    ``total_sen`` is the whole outing — meal plus travel — because that is the
    single figure on the row and in the sheet's total. Sending the meal alone
    would put a draft on screen that is not the thing the user added.

    ``confidence`` is the place's own band, not a percentage: what "high" is
    worth is the server's to decide, so two clients cannot come to different
    answers about it. It is typed as a plain string rather than an enum because
    the bands come from a curated data file that is regenerated, and a word this
    build has not seen should cost the user their tap the least — the service
    reads an unfamiliar one as the least certain band.
    """

    name: str = Field(min_length=1, max_length=120)
    total_sen: int = Field(gt=0)
    confidence: str = Field(min_length=1, max_length=16)


class DayPlanFilters(ResponseModel):
    """The Plan screen's controls, in one shape.

    The same shape goes both ways: it is the state the screen is in when it
    asks, and the state it should be in afterwards. ``lat``/``lng`` travel with
    it because a ceiling means nothing without knowing where the list was
    measured from — but they are only ever echoed back, never rewritten. See
    ``DayPlanInterpretResponse``.
    """

    lat: float
    lng: float
    mode: Literal["walk", "transit", "ride"] = "walk"
    halal_only: bool = False
    # Null means the screen is carrying no ceiling of its own and today's
    # safe-to-spend is standing in for one.
    cap_sen: int | None = Field(default=None, gt=0)
    # One kind of food, or null for every kind. Only ever a word the curated
    # set actually carries: a sentence read as some other category is left
    # unapplied and reported in ``unread``, because a filter that can match
    # nothing is not a reading of anything.
    kind: str | None = Field(default=None, max_length=40)
    sort: Literal["balanced", "cheapest", "closest"] = "balanced"


class DayPlanInterpretRequest(DayPlanFilters):
    """One sentence, and the controls it is to be read against.

    The current state is sent with the sentence rather than assumed, because
    most sentences only speak to one or two controls and the rest have to come
    back untouched.
    """

    text: str = Field(min_length=1, max_length=280)


class DayPlanInterpretResponse(ResponseModel):
    """What the sentence came to, and whether any of it may be applied.

    ``filters`` is the whole new control state or it is null. There is no
    partial answer: a client that applied half of a request would be showing a
    list the user reads as the answer to all of it.

    ``understood`` is the short line to show back, so a misreading is visible
    and can be corrected by tapping the chip it got wrong. It is built from the
    filters themselves, so it cannot describe a setting other than the one
    being applied. ``unread`` is whatever part of the sentence produced no
    filter — a place name, most often, since the origin is not the model's to
    set. ``reason`` says why nothing was applied, and is empty when something
    was.
    """

    applied: bool
    filters: DayPlanFilters | None
    understood: str
    unread: str
    reason: str


class DashboardTodayResponse(ResponseModel):
    date: date
    display_name: str
    currency: str
    balance_sen: int
    reserved_sen: int
    buffer_sen: int
    goal_reserve_sen: int
    unclaimed_sen: int
    per_day_sen: int
    spent_today_sen: int
    safe_today_sen: int
    days_to_payday: int
    cycle_elapsed: int
    commitment_count: int
    drafts_waiting: int
    next_commitment: NextCommitmentResponse | None
    goals: list[GoalSummaryResponse]


class TransactionResponse(ResponseModel):
    id: uuid.UUID
    merchant: str
    amount_sen: int
    category: str
    category_label: str
    occurred_on: date
    status: str
    source: str
    confidence: int | None
    note: str


class ActivityDayResponse(ResponseModel):
    date: date
    total_sen: int
    transactions: list[TransactionResponse]


class CategorySummaryResponse(ResponseModel):
    slug: str
    label: str
    spent_this_cycle_sen: int
    count: int


class ActivityResponse(ResponseModel):
    drafts: list[TransactionResponse]
    draft_total_sen: int
    days: list[ActivityDayResponse]
    spent_this_cycle_sen: int
    categories: list[CategorySummaryResponse]


class ButlerMessageResponse(ResponseModel):
    id: uuid.UUID
    role: str
    content: str
    evidence: list[tuple[str, str]]
    attachment: dict | None
    created_at: datetime


class ButlerApprovalResponse(ResponseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    tool: str
    args: dict
    summary: str
    evidence: list[tuple[str, str]]
    status: str
    created_at: datetime


class ButlerThreadResponse(ResponseModel):
    id: uuid.UUID
    title: str
    messages: list[ButlerMessageResponse]
    pending_approvals: list[ButlerApprovalResponse]


class ButlerAskRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    # A receipt or voice read from /v1/capture, passed back verbatim. It is a
    # proposal the Butler can look at, never a ledger entry.
    attachment: dict | None = None


class ApprovalDecisionRequest(BaseModel):
    action: Literal["accept", "edit", "reject"]
    args: dict | None = None


class MemoryResponse(ResponseModel):
    id: uuid.UUID
    kind: str
    subject: str
    fact: str
    confidence: int
    source_message_id: uuid.UUID | None
    created_at: datetime
    last_used_at: datetime | None


class MemoryCorrectionRequest(BaseModel):
    fact: str = Field(min_length=1, max_length=280)


class CaptureFieldResponse(ResponseModel):
    label: str
    value: str
    confidence: int


class CaptureResponse(ResponseModel):
    """What a reader made of a photo or a recording. Nothing is on the ledger."""

    kind: str
    source: str
    merchant: str
    amount_sen: int
    occurred_on: date
    category: str
    confidence: int
    note: str
    transcript: str
    fields: list[CaptureFieldResponse]


class CaptureAvailability(ResponseModel):
    """Whether the affordances should be offered at all."""

    receipt: bool
    voice: bool
    max_bytes: int


class CreateTransactionRequest(BaseModel):
    merchant: str = Field(min_length=1, max_length=120)
    amount_sen: int = Field(gt=0)
    occurred_on: date
    category: str = Field(default="uncategorised", max_length=40)
    source: str = Field(default="manual", max_length=12)
    confidence: int | None = Field(default=None, ge=0, le=100)
    note: str = Field(default="", max_length=280)


class CorrectTransactionRequest(BaseModel):
    """What the user says a draft should have read. Every field is optional.

    Omitted means "leave it alone", which is why nothing here defaults to a
    value: a body carrying only ``amount_sen`` must not blank the merchant.
    ``confidence`` is absent on purpose — it is the reader's own figure, and a
    corrected amount clears it rather than letting a client restate it.
    """

    merchant: str | None = Field(default=None, min_length=1, max_length=120)
    amount_sen: int | None = Field(default=None, gt=0)
    category: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=280)
