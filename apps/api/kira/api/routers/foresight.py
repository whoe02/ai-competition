"""The forecast over HTTP. Reads only; the transport layer does no arithmetic."""

from __future__ import annotations

from fastapi import APIRouter, Query

from kira.api.deps import CurrentUser, SessionDep
from kira.api.schemas import (
    DriverOut,
    ForesightResponse,
    GoalOutlookOut,
    LeverOut,
    MoneyOut,
    ScenarioComparisonResponse,
    ScenarioRequest,
    ScenarioResultOut,
)
from kira.engine.types import GoalOutlook, Lever
from kira.money import Money
from kira.services.clock import today_for
from kira.services.foresight import compare, foresight

router = APIRouter(prefix="/v1/foresight", tags=["foresight"])


def _money(amount: Money) -> MoneyOut:
    return MoneyOut(sen=amount.sen, currency=amount.currency)


def _outlook(outlook: GoalOutlook) -> GoalOutlookOut:
    return GoalOutlookOut(
        goal_id=outlook.goal_id,
        target_date=outlook.target_date,
        probability_bp=outlook.probability_bp,
        median_shortfall=_money(outlook.median_shortfall),
    )


def _lever(lever: Lever) -> LeverOut:
    return LeverOut(kind=lever.kind, target_id=lever.target_id, delta=_money(lever.delta))


@router.get("", response_model=ForesightResponse)
async def get_foresight(
    user: CurrentUser,
    session: SessionDep,
    horizon: int = Query(default=180, ge=1, le=365),
) -> ForesightResponse:
    result = await foresight(session, user, today_for(), horizon_days=horizon)
    return ForesightResponse(
        horizon_days=result.horizon_days,
        dates=[day.on for day in result.bands.bands.days],
        p10=[_money(amount) for amount in result.bands.bands.p10],
        p50=[_money(amount) for amount in result.bands.bands.p50],
        p90=[_money(amount) for amount in result.bands.bands.p90],
        outlooks=[_outlook(outlook) for outlook in result.bands.outlooks],
        drivers=[
            DriverOut(
                lever=_lever(driver.lever),
                probability_bp_before=driver.probability_bp_before,
                probability_bp_after=driver.probability_bp_after,
                bp_per_ringgit=driver.bp_per_ringgit,
            )
            for driver in result.drivers
        ],
        profile_days=result.profile_days,
        assumption=result.assumption,
    )


@router.post("/scenarios", response_model=ScenarioComparisonResponse)
async def post_scenarios(
    user: CurrentUser, session: SessionDep, request: ScenarioRequest
) -> ScenarioComparisonResponse:
    levers = tuple(
        Lever(kind=item.kind, target_id=item.target_id, delta=Money(item.delta_sen, user.currency))
        for item in request.levers
    )
    results = await compare(session, user, today_for(), levers, horizon_days=request.horizon_days)
    return ScenarioComparisonResponse(
        results=[
            ScenarioResultOut(
                lever=_lever(result.lever),
                outlooks=[_outlook(outlook) for outlook in result.outlooks],
                safe_today_after=_money(result.safe_today_after),
            )
            for result in results
        ]
    )
