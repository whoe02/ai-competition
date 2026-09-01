"""Kira's track record over HTTP. Reads only; the transport does no arithmetic."""

from __future__ import annotations

from fastapi import APIRouter, Query

from kira.api.deps import CurrentUser, SessionDep
from kira.api.schemas import AdviceDayOut, HindsightResponse, MoneyOut
from kira.money import Money
from kira.services.clock import today_for
from kira.services.hindsight import DEFAULT_WINDOW_DAYS, MAX_WINDOW_DAYS, hindsight

router = APIRouter(prefix="/v1/hindsight", tags=["hindsight"])

# The card shows a strip of the last fortnight; the full window stays in the score.
RECENT_DAYS = 14


def _money(amount: Money) -> MoneyOut:
    return MoneyOut(sen=amount.sen, currency=amount.currency)


@router.get("", response_model=HindsightResponse)
async def get_hindsight(
    user: CurrentUser,
    session: SessionDep,
    window: int = Query(default=DEFAULT_WINDOW_DAYS, ge=1, le=MAX_WINDOW_DAYS),
) -> HindsightResponse:
    result = await hindsight(session, user, today_for(), window_days=window)
    return HindsightResponse(
        window_days=result.window_days,
        days=result.record.days,
        followed=result.record.followed,
        follow_rate_bp=result.record.follow_rate_bp,
        mean_abs_deviation=_money(result.record.mean_abs_deviation),
        counterfactual_gain=_money(result.record.counterfactual_gain),
        goal_id=result.goal_id,
        probability_bp_now=result.probability_bp_now,
        probability_bp_if_followed=result.probability_bp_if_followed,
        recent=[
            AdviceDayOut(
                on=day.on,
                advised=_money(day.advised),
                actual=_money(day.actual),
                followed=day.actual <= day.advised,
            )
            for day in result.days[-RECENT_DAYS:]
        ],
        assumption=result.assumption,
    )
