from datetime import UTC, date, datetime

import pytest

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
    PART_TIME_RECOMMENDER_PROMPT,
    PartTimeJobOption,
    _normalise_job_payload,
    create_part_time_recommendation,
    get_stored_part_time_recommendation,
    preview_part_time_recommendation,
)
from kira.services.snapshot import load_snapshot

AS_OF = datetime(2026, 9, 3, tzinfo=UTC)
PAY_ESTIMATE = {
    "estimated_hourly_rate_min_sen": 3_000,
    "estimated_hourly_rate_max_sen": 5_000,
    "suggested_hours_per_week": 8,
    "suggested_work_days_per_week": 2,
    "pay_estimate_basis": "Specialised technical work with flexible freelance delivery.",
}


def test_part_time_prompt_explicitly_requests_json_for_dashscope_structured_output():
    """DashScope rejects json_object output unless a message says JSON."""
    assert "json" in PART_TIME_RECOMMENDER_PROMPT.casefold()
    assert "hourly pay range" in PART_TIME_RECOMMENDER_PROMPT.casefold()
    assert "deterministic backend code" in PART_TIME_RECOMMENDER_PROMPT.casefold()


def test_part_time_rejects_an_unreasonably_wide_hourly_estimate() -> None:
    with pytest.raises(ValueError, match="range is too wide"):
        PartTimeJobOption.model_validate(
            {
                "role_title": "Technical tutor",
                "typical_tasks": "Teach practical programming skills in short sessions.",
                "why_relevant": "It uses existing engineering knowledge and communication skills.",
                "work_arrangement": "Remote scheduled sessions",
                "first_step": "Prepare one concise public lesson outline.",
                "estimated_hourly_rate_min_sen": 1_000,
                "estimated_hourly_rate_max_sen": 4_000,
                "suggested_hours_per_week": 8,
                "suggested_work_days_per_week": 2,
                "pay_estimate_basis": "Specialised teaching delivered through flexible sessions.",
                "cautions": [],
            }
        )


def test_part_time_normalises_qwen_numbered_jobs_without_accepting_an_invalid_schema():
    result = _normalise_job_payload(
        {
            "job_1": {
                "title": "Technical tutor",
                "typical_work": "Teach beginners practical programming concepts in short sessions.",
                "why_it_fits": "It uses communication skills from the user's technical role.",
                "arrangement": "Remote evening sessions",
                "next_step": "Write one short lesson outline for a beginner topic.",
                "watch_outs": ["Keep preparation time within your weekly limit."],
                **PAY_ESTIMATE,
            },
            "job_2": {
                "title": "Documentation reviewer",
                "typical_work": "Review public technical guides for clarity and accuracy.",
                "why_it_fits": (
                    "It applies existing engineering judgement without duplicating "
                    "full-time responsibilities."
                ),
                "arrangement": "Remote asynchronous work",
                "next_step": "Prepare one public writing sample for a portfolio.",
                **PAY_ESTIMATE,
            },
            "job_3": {
                "title": "AI quality reviewer",
                "typical_work": "Assess model responses against concise quality standards.",
                "why_it_fits": "It builds on the user's AI engineering experience.",
                "arrangement": "Remote task-based work",
                "next_step": "Create a small evaluation checklist using public examples.",
                **PAY_ESTIMATE,
            },
        }
    )

    assert [item.role_title for item in result.recommendations] == [
        "Technical tutor",
        "Documentation reviewer",
        "AI quality reviewer",
    ]
    assert result.overall_guidance.startswith("Compare time commitments")


def test_part_time_compacts_valid_but_overlong_provider_prose() -> None:
    job = {
        "role_title": "Technical tutor",
        "typical_tasks": "Teach practical programming concepts in short remote sessions.",
        "why_relevant": "It applies existing engineering and communication skills.",
        "work_arrangement": "Remote evening sessions",
        "first_step": "Prepare one short beginner lesson outline.",
        "cautions": ["Keep preparation time within the available weekly hours."],
        **PAY_ESTIMATE,
    }
    result = _normalise_job_payload(
        {
            "recommendations": [job, job, job],
            "overall_guidance": " ".join(["Choose sustainable work"] * 20),
        }
    )

    assert len(result.overall_guidance) <= 150
    assert result.overall_guidance.endswith("…")


class _JobModel:
    def with_structured_output(self, schema, **kwargs):
        del schema, kwargs
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
                    **PAY_ESTIMATE,
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
                    **PAY_ESTIMATE,
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
                    **PAY_ESTIMATE,
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
    assert recommendation["recommendation_schema_version"] == 2
    assert len(recommendation["recommendations"]) == 3
    assert recommendation["preferences"] == {
        "available_hours_per_week": 8,
        "work_mode": "remote",
        "transport_limitations": "No car",
    }
    assert recommendation["expected_monthly_income_sen"] is None
    assert recommendation["monthly_income_after_sen"] is None
    assert recommendation["safe_to_spend_changes"] is False
    first = recommendation["recommendations"][0]
    assert first["estimated_hourly_rate_min_sen"] == 3_000
    assert first["estimated_daily_income_min_sen"] == 12_000
    assert first["estimated_weekly_income_min_sen"] == 24_000
    assert first["estimated_monthly_income_min_sen"] == 104_000
    assert first["estimated_monthly_income_max_sen"] == 173_333
    assert first["goal_contribution_monthly_before_sen"] == 100_000
    assert first["goal_contribution_monthly_with_job_min_sen"] == 200_000
    assert first["projected_completion_with_min_income"] == "2026-09-10"
    assert first["days_saved_min"] == 30
    assert first["safe_to_spend_today_change_sen"] == 0
    assert first["future_daily_safe_to_spend_increase_min_sen"] == 6_800
    stored = await get_stored_part_time_recommendation(session, user, goal.id)
    assert stored == recommendation

    capped = await create_part_time_recommendation(
        session,
        user,
        goal.id,
        AS_OF,
        available_hours_per_week=4,
        work_mode="remote",
        transport_limitations="No car",
        model=_JobModel(),
    )
    assert {item["suggested_hours_per_week"] for item in capped["recommendations"]} == {4}
    assert capped["recommendations"][0]["estimated_weekly_income_min_sen"] == 12_000

    preview = await preview_part_time_recommendation(session, user, goal.id, 100_000, AS_OF)
    after_safe = safe_to_spend(await load_snapshot(session, user, AS_OF.date())).safe_today.sen

    assert preview["expected_monthly_income_sen"] == 100_000
    assert preview["monthly_income_after_sen"] == 620_000
    assert preview["cash_effect"].startswith("Forecast only")
    assert after_safe == before_safe
