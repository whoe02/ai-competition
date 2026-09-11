import json
from datetime import UTC, date, datetime

import pytest

from kira.db.models import Account, User
from kira.engine import safe_to_spend
from kira.money import Money
from kira.services import part_time_recommendations as part_time_service
from kira.services.goal_planning import (
    apply_approved_plan_change,
    create_draft_goal,
    current_plan_record,
    definition_from_record,
    plan_from_record,
)
from kira.services.part_time_recommendations import (
    PART_TIME_RECOMMENDER_PROMPT,
    JobListing,
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


async def _candidate_loader(_: str) -> list[JobListing]:
    """Stable source records: the test model may rank them but cannot rewrite them."""
    return [
        JobListing(
            id="remotive:one",
            title="AI Evaluator (contract)",
            company="Source One",
            location="Malaysia",
            job_type="Contract",
            apply_url="https://remotive.com/remote-jobs/one",
            source="remotive",
            description="Evaluate AI outputs against documented quality criteria.",
        ),
        JobListing(
            id="remotive:two",
            title="Technical Documentation Reviewer",
            company="Source Two",
            location="Remote",
            job_type="Freelance",
            apply_url="https://remotive.com/remote-jobs/two",
            source="remotive",
            description="Review developer documentation for accuracy and clarity.",
        ),
        JobListing(
            id="remotive:three",
            title="Online Workshop Facilitator",
            company="Source Three",
            location="Remote",
            job_type="Part-time",
            apply_url="https://remotive.com/remote-jobs/three",
            source="remotive",
            description="Facilitate short online workshops for technical learners.",
        ),
        JobListing(
            id="remotive:four",
            title="AI Content Reviewer",
            company="Source Four",
            location="Remote",
            job_type="Contract",
            apply_url="https://remotive.com/remote-jobs/four",
            source="remotive",
            description="Review technical AI content against clear editorial standards.",
        ),
        JobListing(
            id="remotive:five",
            title="Machine Learning Tutor",
            company="Source Five",
            location="Remote",
            job_type="Part-time",
            apply_url="https://remotive.com/remote-jobs/five",
            source="remotive",
            description="Tutor learners in practical machine learning foundations.",
        ),
        JobListing(
            id="remotive:six",
            title="Technical Course Evaluator",
            company="Source Six",
            location="Remote",
            job_type="Freelance",
            apply_url="https://remotive.com/remote-jobs/six",
            source="remotive",
            description="Evaluate online technical lessons for accuracy and usefulness.",
        ),
    ]


def test_part_time_prompt_explicitly_requests_json_for_dashscope_structured_output():
    """DashScope rejects json_object output unless a message says JSON."""
    assert "json" in PART_TIME_RECOMMENDER_PROMPT.casefold()
    assert "hourly pay range" in PART_TIME_RECOMMENDER_PROMPT.casefold()
    assert "deterministic backend code" in PART_TIME_RECOMMENDER_PROMPT.casefold()
    assert "maximum, not a quota" in PART_TIME_RECOMMENDER_PROMPT.casefold()
    assert "return fewer jobs" in PART_TIME_RECOMMENDER_PROMPT.casefold()


def test_part_time_selection_may_return_fewer_live_jobs_instead_of_forcing_bad_matches():
    candidates = [
        JobListing(
            id="arbeitnow:part-time-hr",
            title="Part-time HR coordinator",
            company="Source Employer",
            location="Remote",
            job_type="Part-time",
            apply_url="https://www.arbeitnow.com/jobs/part-time-hr",
            source="arbeitnow",
            description="Coordinate interviews and maintain candidate records.",
        ),
        JobListing(
            id="remotive:full-time-engineer",
            title="Senior software engineer",
            company="Other Employer",
            location="Europe",
            job_type="Full-time",
            apply_url="https://remotive.com/remote-jobs/full-time-engineer",
            source="remotive",
            description="Build distributed backend systems full time.",
        ),
    ]
    one_match = {
        "recommendations": [
            {
                "source_job_id": "arbeitnow:part-time-hr",
                "role_title": "Part-time HR coordinator",
                "typical_tasks": "Coordinate interviews and maintain candidate records.",
                "why_relevant": (
                    "It directly applies existing human resources coordination experience."
                ),
                "work_arrangement": "Part-time; Remote",
                "first_step": "Review the complete live listing before applying.",
                "cautions": ["Confirm the weekly schedule before accepting."],
                **PAY_ESTIMATE,
            }
        ],
        "overall_guidance": "Only one current listing fits the supplied constraints.",
    }

    selected = part_time_service._validated_job_selection(
        one_match,
        model_candidates=candidates,
        current_job_title="Human resources",
        recommendation_count=2,
    )

    assert [item.source_job_id for item in selected.recommendations] == [
        "arbeitnow:part-time-hr"
    ]


def test_part_time_selection_uses_live_listing_for_pay_basis_when_model_cites_money():
    """Provider compensation wording cannot invalidate an otherwise safe job choice."""
    listing = JobListing(
        id="remotive:task-priced",
        title="Remote task reviewer",
        company="Source Employer",
        location="Remote",
        job_type="Freelance",
        apply_url="https://remotive.com/remote-jobs/task-priced",
        source="remotive",
        description="Review submitted tasks against documented quality requirements.",
    )
    selected = part_time_service._validated_job_selection(
        {
            "recommendations": [
                {
                    "source_job_id": listing.id,
                    "role_title": listing.title,
                    "typical_tasks": listing.description,
                    "why_relevant": "Flexible remote review work suits the supplied availability.",
                    "work_arrangement": "Freelance; Remote",
                    "first_step": "Read the current requirements and submit an application.",
                    "pay_estimate_basis": "Task-based USD compensation depends on approval rates.",
                    "cautions": [],
                    **PAY_ESTIMATE,
                }
            ],
            "overall_guidance": "Compare each live listing before committing your available time.",
        },
        model_candidates=[listing],
        current_job_title="Project coordinator",
        recommendation_count=1,
    )

    assert "USD" not in selected.recommendations[0].pay_estimate_basis
    assert "Remote task reviewer" in selected.recommendations[0].pay_estimate_basis


def test_part_time_selection_can_report_no_suitable_current_listing():
    selected = part_time_service._validated_job_selection(
        {
            "recommendations": [],
            "overall_guidance": "No current listing fits the supplied hours and location.",
        },
        model_candidates=[],
        current_job_title="Human resources",
        recommendation_count=0,
    )

    assert selected.recommendations == []


async def test_part_time_search_queries_are_generated_from_profile_and_constraints():
    class _QueryModel:
        def with_structured_output(self, schema, **kwargs):
            assert schema is part_time_service.JobSearchPlan
            assert kwargs["method"] == "json_mode"
            return self

        async def ainvoke(self, messages):
            assert "json" in messages[0].content.casefold()
            context = json.loads(messages[1].content)
            assert context["current_job_title"] == "Human resource"
            assert context["available_hours_per_week"] == 21
            return {
                "queries": [
                    "Human Resources Coordinator",
                    "Recruitment Coordinator",
                    "Talent Acquisition Assistant",
                ]
            }

    queries = await part_time_service._dynamic_job_queries(
        _QueryModel(),
        job_title="Human resource",
        available_hours_per_week=21,
        work_mode="either",
        transport_limitations="",
    )

    assert queries == [
        "Human resource",
        "Human Resources Coordinator",
        "Recruitment Coordinator",
        "Talent Acquisition Assistant",
    ]


def test_part_time_rejects_an_unreasonably_wide_hourly_estimate() -> None:
    with pytest.raises(ValueError, match="range is too wide"):
        PartTimeJobOption.model_validate(
            {
                "source_job_id": "remotive:wide",
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
                "id": "remotive:one",
                "title": "Technical tutor",
                "typical_work": "Teach beginners practical programming concepts in short sessions.",
                "why_it_fits": "It uses communication skills from the user's technical role.",
                "arrangement": "Remote evening sessions",
                "next_step": "Write one short lesson outline for a beginner topic.",
                "watch_outs": ["Keep preparation time within your weekly limit."],
                **PAY_ESTIMATE,
            },
            "job_2": {
                "id": "remotive:two",
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
                "id": "remotive:three",
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
        "source_job_id": "remotive:one",
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


def test_model_candidate_context_is_size_bounded_and_source_diverse(monkeypatch) -> None:
    settings = part_time_service.get_settings().model_copy(
        update={
            "part_time_job_context_max_characters": 1_000,
            "part_time_job_description_characters": 80,
        }
    )
    monkeypatch.setattr(part_time_service, "get_settings", lambda: settings)
    candidates = [
        JobListing(
            id=f"{source}:{number}",
            title=f"AI Engineer {number}",
            company="Source Employer",
            location="Kuala Lumpur",
            job_type="Part-time",
            apply_url=f"https://example.com/{source}/{number}",
            source=source,
            description="Relevant experience building and evaluating AI systems. " * 10,
        )
        for source in ("remotive", "arbeitnow")
        for number in range(1, 4)
    ]

    selected, payload = part_time_service._model_candidates(candidates)

    assert len(selected) >= 3
    assert {candidate.source for candidate in selected} == {"remotive", "arbeitnow"}
    assert all("apply_url" not in record for record in payload)
    assert all(len(record["description"]) <= 80 for record in payload)


def test_job_relevance_uses_whole_tokens_instead_of_short_substrings() -> None:
    unrelated = JobListing(
        id="remotive:financial",
        title="Inside Sales Contractor",
        company="Example",
        location="Worldwide",
        job_type="Contract",
        apply_url="https://example.com/financial",
        source="remotive",
        description="Help consumers improve their financial profiles.",
    )
    relevant = unrelated.model_copy(
        update={
            "id": "remotive:ai",
            "title": "AI Evaluation Contractor",
            "apply_url": "https://example.com/ai",
        }
    )

    assert part_time_service._query_relevance("AI Engineer", unrelated) == 0
    assert part_time_service._query_relevance("AI Engineer", relevant) > 0


async def test_arbeitnow_source_keeps_an_on_site_listing_and_provider_link(monkeypatch) -> None:
    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "data": [
                    {
                        "slug": "ai-engineer-kuala-lumpur",
                        "company_name": "Source Employer",
                        "title": "AI Engineer",
                        "description": "Build and review production AI systems.",
                        "remote": False,
                        "url": "https://www.arbeitnow.com/jobs/ai-engineer-kuala-lumpur",
                        "location": "Kuala Lumpur",
                        "job_types": ["Part-time"],
                    }
                ]
            }

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def get(self, url: str) -> _Response:
            assert url == part_time_service.ARBEITNOW_JOBS_URL
            return _Response()

    monkeypatch.setattr(part_time_service.httpx, "AsyncClient", lambda **_: _Client())

    candidates = await part_time_service._arbeitnow_candidates("AI Engineer", limit=3)

    assert len(candidates) == 1
    assert candidates[0].id == "arbeitnow:ai-engineer-kuala-lumpur"
    assert candidates[0].source == "arbeitnow"
    assert candidates[0].location == "Kuala Lumpur"
    assert candidates[0].apply_url == "https://www.arbeitnow.com/jobs/ai-engineer-kuala-lumpur"


class _JobModel:
    def with_structured_output(self, schema, **kwargs):
        del schema, kwargs
        return self

    async def ainvoke(self, messages):
        del messages
        return {
            "recommendations": [
                {
                    "source_job_id": "remotive:one",
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
                    "source_job_id": "remotive:two",
                    "role_title": "Technical content reviewer",
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
                    "source_job_id": "remotive:three",
                    "role_title": "Weekend workshop facilitator",
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


class _CandidateAwareJobModel:
    def with_structured_output(self, schema, **kwargs):
        del schema, kwargs
        return self

    async def ainvoke(self, messages):
        context = json.loads(messages[1].content)
        count = context["selection_requirements"]["recommendation_count"]
        return {
            "recommendations": [
                {
                    "source_job_id": item["id"],
                    "role_title": item["title"],
                    "typical_tasks": item["description"],
                    "why_relevant": "It matches the user's current professional experience.",
                    "work_arrangement": item["job_type"],
                    "first_step": "Review the complete live listing before applying.",
                    "cautions": ["Confirm the schedule and contract terms."],
                    **PAY_ESTIMATE,
                }
                for item in context["job_candidates"][:count]
            ],
            "overall_guidance": "Compare the new live options before choosing one.",
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
        job_search=_candidate_loader,
    )

    assert recommendation["status"] == "available"
    assert recommendation["source"] == "job_board_ranked"
    assert recommendation["recommendation_schema_version"] == 5
    assert len(recommendation["recommendations"]) == 3
    assert recommendation["preferences"] == {
        "available_hours_per_week": 8,
        "work_mode": "remote",
        "transport_limitations": "No car",
    }
    assert recommendation["expected_monthly_income_sen"] is None
    assert recommendation["monthly_income_after_sen"] is None
    first = recommendation["recommendations"][0]
    assert first["role_title"] == "AI Evaluator (contract)"
    assert first["job_company"] == "Source One"
    assert first["job_location"] == "Malaysia"
    assert first["job_source"] == "remotive"
    assert first["apply_url"] == "https://remotive.com/remote-jobs/one"
    assert [item["typical_tasks"] for item in recommendation["recommendations"]] == [
        "Evaluate AI outputs against documented quality criteria.",
        "Review developer documentation for accuracy and clarity.",
        "Facilitate short online workshops for technical learners.",
    ]
    assert first["estimated_hourly_rate_min_sen"] == 3_000
    assert first["estimated_daily_income_min_sen"] == 12_000
    assert first["estimated_weekly_income_min_sen"] == 24_000
    assert first["estimated_monthly_income_min_sen"] == 104_000
    assert first["estimated_monthly_income_max_sen"] == 173_333
    assert first["goal_contribution_monthly_before_sen"] == 100_000
    assert first["goal_contribution_monthly_with_job_min_sen"] == 200_000
    assert first["projected_completion_with_min_income"] == "2026-09-10"
    assert first["days_saved_min"] == 30
    assert first["future_daily_safe_to_spend_increase_min_sen"] == 6_800
    stored = await get_stored_part_time_recommendation(session, user, goal.id)
    assert stored == recommendation

    legacy = {
        **recommendation,
        "recommendation_schema_version": 4,
        "safe_to_spend_changes": False,
        "recommendations": [
            {**item, "safe_to_spend_today_change_sen": 0}
            for item in recommendation["recommendations"]
        ],
    }
    record = await current_plan_record(session, user, goal.id)
    record.part_time_recommendation_data = legacy
    await session.commit()

    migrated = await get_stored_part_time_recommendation(session, user, goal.id)
    assert migrated is not None
    assert migrated["recommendation_schema_version"] == 5
    assert "safe_to_spend_changes" not in migrated
    assert all("safe_to_spend_today_change_sen" not in item for item in migrated["recommendations"])
    persisted = await current_plan_record(session, user, goal.id)
    assert persisted.part_time_recommendation_data == migrated

    user.job_title = "Human Resources Manager"
    await session.flush()
    assert await get_stored_part_time_recommendation(session, user, goal.id) is None
    user.job_title = "AI Engineer"
    await session.flush()

    capped = await create_part_time_recommendation(
        session,
        user,
        goal.id,
        AS_OF,
        available_hours_per_week=4,
        work_mode="remote",
        transport_limitations="No car",
        model=_CandidateAwareJobModel(),
        job_search=_candidate_loader,
    )
    assert {item["suggested_hours_per_week"] for item in capped["recommendations"]} == {4}
    assert capped["recommendations"][0]["estimated_weekly_income_min_sen"] == 12_000
    assert {item["source_job_id"] for item in capped["recommendations"]}.isdisjoint(
        item["source_job_id"] for item in recommendation["recommendations"]
    )

    preview = await preview_part_time_recommendation(session, user, goal.id, 100_000, AS_OF)
    after_safe = safe_to_spend(await load_snapshot(session, user, AS_OF.date())).safe_today.sen

    assert preview["expected_monthly_income_sen"] == 100_000
    assert preview["monthly_income_after_sen"] == 620_000
    assert preview["cash_effect"].startswith("Forecast only")
    assert after_safe == before_safe
