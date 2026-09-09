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
    create_part_time_recommendation,
    get_stored_part_time_recommendation,
    preview_part_time_recommendation,
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
            "recommendations": [
                {
                    "role_title": "AI tutoring assistant",
                    "typical_tasks": (
                        "Help beginners practise prompting and review introductory exercises."
                    ),
                    "why_relevant": (
                        "It uses the communication and technical skills from the user's main role."
                    ),
                    "work_arrangement": "Remote, flexible sessions",
                    "first_step": "Prepare a short outline of topics you can confidently teach.",
                    "cautions": ["Do not share confidential material from your employer."],
                },
                {
                    "role_title": "Technical content reviewer",
                    "typical_tasks": (
                        "Review tutorials for clarity, correctness, and beginner-friendly "
                        "explanations."
                    ),
                    "why_relevant": (
                        "An engineering background supports accurate review without duplicating "
                        "full-time work."
                    ),
                    "work_arrangement": "Remote, asynchronous",
                    "first_step": "Create one sample review using a public technical tutorial.",
                    "cautions": [
                        "Confirm ownership and confidentiality terms before accepting work."
                    ],
                },
                {
                    "role_title": "Weekend workshop facilitator",
                    "typical_tasks": (
                        "Guide small practical workshops and answer questions from learners."
                    ),
                    "why_relevant": (
                        "It turns existing knowledge into scheduled work that fits limited "
                        "availability."
                    ),
                    "work_arrangement": "Remote or nearby on-site",
                    "first_step": (
                        "Draft a one-hour beginner workshop and identify suitable community groups."
                    ),
                    "cautions": ["Check transport and preparation time before committing."],
                },
            ],
            "overall_guidance": (
                "Compare the schedule and boundaries of each option before choosing one to explore."
            ),
        }


async def test_part_time_preview_is_read_only_and_uses_user_income_estimate(session):
    user = User(
        email="part-time@example.com",
        password_hash="unused",
        display_name="Part time",
        job_title="AI Engineer",
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
        target_amount_sen=200_000,
        current_saved_sen=0,
        target_date=date(2026, 10, 20),
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
        session,
        user,
        goal.id,
        AS_OF,
        available_hours_per_week=8,
        work_mode="remote",
        transport_limitations="No car",
        model=_JobModel(),
    )

    assert recommendation["status"] == "available"
    assert recommendation["source"] == "llm"
    assert len(recommendation["recommendations"]) == 3
    assert recommendation["preferences"] == {
        "available_hours_per_week": 8,
        "work_mode": "remote",
        "transport_limitations": "No car",
    }
    assert recommendation["expected_monthly_income_sen"] is None
    assert recommendation["monthly_income_after_sen"] is None
    assert recommendation["safe_to_spend_changes"] is False
    stored = await get_stored_part_time_recommendation(session, user, goal.id)
    assert stored == recommendation

    preview = await preview_part_time_recommendation(session, user, goal.id, 100_000, AS_OF)
    after_safe = safe_to_spend(await load_snapshot(session, user, AS_OF.date())).safe_today.sen

    assert preview["expected_monthly_income_sen"] == 100_000
    assert preview["monthly_income_after_sen"] == 620_000
    assert preview["cash_effect"].startswith("Read-only")
    assert after_safe == before_safe
