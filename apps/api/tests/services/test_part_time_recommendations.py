from datetime import UTC, date, datetime

from kira.db.models import Account, User
from kira.engine import safe_to_spend
from kira.money import Money
from kira.services.goal_planning import (
    apply_approved_plan_change,
    create_draft_goal,
    definition_from_record,
    plan_from_record,
)
from kira.services.part_time_recommendations import (
    approve_part_time_recommendation,
    create_part_time_recommendation,
)
from kira.services.snapshot import load_snapshot

AS_OF = datetime(2026, 9, 3, tzinfo=UTC)


class _JobModel:
    def with_structured_output(self, schema):
        del schema
        return self

    async def ainvoke(self, messages):
        del messages
        return {
            "role_title": "Event support",
            "summary": "A flexible role may be worth exploring around your existing commitments.",
            "first_step": "Compare suitable options and check the work expectations before applying.",
            "cautions": ["Confirm the schedule works with your essential commitments."],
        }


async def test_part_time_approval_improves_forecast_without_changing_safe_to_spend(session):
    user = User(
        email="part-time@example.com",
        password_hash="unused",
        display_name="Part time",
        currency="MYR",
        buffer=Money(0),
        monthly_income=Money(520_000),
        next_payday=date(2026, 9, 10),
        cycle_start=date(2026, 9, 1),
        cycle_days=30,
    )
    session.add(user)
    await session.flush()
    session.add(
        Account(user_id=user.id, name="Main", kind="bank", opening_balance=Money(1_000_000))
    )
    await session.flush()

    goal, draft = await create_draft_goal(
        session,
        user,
        goal_type="travel",
        name="Penang trip",
        target_amount_sen=1_000_000,
        current_saved_sen=0,
        target_date=date(2026, 9, 20),
        priority="important",
        funding_account_ids=(),
        as_of_utc=AS_OF,
    )
    await apply_approved_plan_change(
        session,
        user,
        definition=definition_from_record(goal),
        plan=plan_from_record(draft),
        base_plan_version=draft.version,
        as_of_utc=AS_OF,
    )
    await session.commit()

    before_safe = safe_to_spend(await load_snapshot(session, user, AS_OF.date())).safe_today.sen
    recommendation = await create_part_time_recommendation(
        session, user, goal.id, AS_OF, model=_JobModel()
    )

    assert recommendation["status"] == "available"
    assert recommendation["source"] == "llm"
    assert recommendation["additional_monthly_income_sen"] > 0
    assert recommendation["contribution_ratio_after_bp"] <= 4_000
    assert recommendation["safe_to_spend_changes"] is False

    approved = await approve_part_time_recommendation(session, user, goal.id, AS_OF)
    after_safe = safe_to_spend(await load_snapshot(session, user, AS_OF.date())).safe_today.sen

    assert approved["status"] == "approved"
    assert approved["feasible_after"] is True
    assert user.part_time_income.sen == recommendation["additional_monthly_income_sen"]
    assert after_safe == before_safe
