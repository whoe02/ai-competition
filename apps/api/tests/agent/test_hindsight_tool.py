"""Kira reviewing her own advice — reachable by the agent, and only readable."""

from kira.agent.tools import REGISTRY, ToolContext
from kira.db.models import DailyAdvice
from kira.seed.demo import DEMO_TODAY, seed_demo_user
from kira.services.dashboard import today_dashboard
from kira.services.snapshot import load_snapshot


def test_the_tool_is_registered_as_a_read():
    spec = REGISTRY.get("review_my_advice")
    assert spec is not None
    assert spec.kind == "read"


async def context(session, user) -> ToolContext:
    return ToolContext(
        session=session,
        user=user,
        today=DEMO_TODAY,
        snapshot=await load_snapshot(session, user, DEMO_TODAY),
        dashboard=await today_dashboard(session, user, DEMO_TODAY),
    )


async def run(session, user, **args):
    spec = REGISTRY.get("review_my_advice")
    return await spec.handler(
        await context(session, user), spec.args_model.model_validate(args)
    )


async def test_the_review_answers_with_checkable_evidence(session):
    user = await seed_demo_user(session)
    await session.flush()

    result = await run(session, user)

    assert result.evidence, "an answer without evidence is a guess"
    labels = " ".join(row.label for row in result.evidence).lower()
    assert "days scored" in labels
    assert "assumption" in labels
    assert result.value["days"] > 0
    assert result.value["followed"] <= result.value["days"]


async def test_the_review_says_so_when_there_is_no_record_yet(session):
    user = await seed_demo_user(session)
    await session.flush()
    await session.execute(DailyAdvice.__table__.delete().where(DailyAdvice.user_id == user.id))

    result = await run(session, user)

    assert result.value["days"] == 0
    assert "no record" in result.value["summary"]
