"""The overnight briefing records advice and proposals, never a financial change."""

from sqlalchemy import func, select

from kira.db.models import (
    ADVICE_SOURCE_WORKER,
    APPROVAL_PENDING,
    Account,
    Briefing,
    ButlerApproval,
    ButlerMessage,
    Commitment,
    DailyAdvice,
    Goal,
    Transaction,
)
from kira.seed.demo import DEMO_TODAY, seed_demo_user
from kira.services.briefings import nightly_briefing


async def count(session, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_a_briefing_records_todays_advice_and_waiting_draft_proposals(session):
    user = await seed_demo_user(session)
    before_money = tuple(
        [await count(session, model) for model in (Account, Commitment, Goal, Transaction)]
    )

    result = await nightly_briefing(session, user, DEMO_TODAY)

    assert result.created is True
    assert result.proposal_count == 2
    assert await count(session, Briefing) == 1
    assert await count(session, ButlerMessage) == 1
    assert await count(session, ButlerApproval) == 2
    assert tuple(
        [await count(session, model) for model in (Account, Commitment, Goal, Transaction)]
    ) == before_money

    advice = (
        await session.execute(
            select(DailyAdvice).where(
                DailyAdvice.user_id == user.id,
                DailyAdvice.on_date == DEMO_TODAY,
            )
        )
    ).scalar_one()
    assert advice.source == ADVICE_SOURCE_WORKER
    assert advice.snapshot["balance"] > 0

    approvals = (await session.execute(select(ButlerApproval))).scalars().all()
    assert {approval.status for approval in approvals} == {APPROVAL_PENDING}
    assert {approval.tool for approval in approvals} == {"confirm_draft"}


async def test_a_second_run_for_the_same_night_is_a_no_op(session):
    user = await seed_demo_user(session)
    first = await nightly_briefing(session, user, DEMO_TODAY)
    second = await nightly_briefing(session, user, DEMO_TODAY)

    assert first.id == second.id
    assert second.created is False
    assert await count(session, Briefing) == 1
    assert await count(session, ButlerApproval) == first.proposal_count
    assert await count(session, ButlerMessage) == 1
