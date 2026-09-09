import json
import uuid
from contextlib import asynccontextmanager
from datetime import date

from sqlalchemy import select

from kira.api.deps import stream_session_factory
from kira.api.schemas import GoalCreateRequest
from kira.db.models import AuditEvent, Goal, GoalPlanRecord
from kira.seed.demo import DEMO_EMAIL, DEMO_PASSWORD, seed_demo_user

from .test_auth import register


def payload(**changes):
    value = {
        "goal_type": "travel",
        "name": "Family trip",
        "target_amount_sen": 120_000,
        "current_saved_sen": 20_000,
        "target_date": "2026-12-02",
        "priority": "important",
        "funding_account_ids": [],
    }
    value.update(changes)
    return value


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestGoalContracts:
    async def test_create_detail_and_plan(self, client):
        token = await register(client)
        created = await client.post("/v1/goals", json=payload(), headers=auth(token))
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["goal"]["status"] == "draft"
        assert body["goal"]["horizon"] == "short"
        assert body["plan"]["version"] == 1
        assert body["plan"]["calculation_version"] == "goal-plan-v1"
        assert body["plan"]["evidence_refs"]
        goal_id = body["goal"]["goal_id"]

        detail = await client.get(f"/v1/goals/{goal_id}", headers=auth(token))
        plan = await client.get(f"/v1/goals/{goal_id}/plan", headers=auth(token))
        assert detail.status_code == 200
        assert detail.json()["goal_type"] == "travel"
        assert plan.status_code == 200
        assert len(plan.json()["milestones"]) == 4

    async def test_scenarios_and_purchase_impact(self, client, session):
        token = await register(client)
        created = await client.post("/v1/goals", json=payload(), headers=auth(token))
        goal_id = created.json()["goal"]["goal_id"]

        scenarios = await client.post(f"/v1/goals/{goal_id}/scenarios", headers=auth(token))
        assert scenarios.status_code == 200, scenarios.text
        assert [item["label"] for item in scenarios.json()["scenarios"]] == [
            "On-time target",
            "Cash-flow-safe",
            "Accelerated",
        ]
        record = (
            await session.execute(
                select(GoalPlanRecord).where(GoalPlanRecord.goal_id == uuid.UUID(goal_id))
            )
        ).scalar_one()
        assert [item["label"] for item in record.scenarios_data] == [
            "On-time target",
            "Cash-flow-safe",
            "Accelerated",
        ]
        record.part_time_recommendation_data = {
            "goal_id": goal_id,
            "plan_version": record.version,
            "status": "available",
            "eligible": True,
            "recommendations": [],
            "source": "llm",
            "preferences": {
                "available_hours_per_week": 8,
                "work_mode": "remote",
                "transport_limitations": "",
            },
            "feasible_before": record.feasible,
            "safe_to_spend_changes": False,
            "cash_effect": "Read-only recommendation.",
        }
        await session.commit()
        stored = await client.get(
            f"/v1/goals/{goal_id}/part-time-recommendation", headers=auth(token)
        )
        assert stored.status_code == 200, stored.text
        assert stored.json()["plan_version"] == record.version
        assert stored.json()["preferences"]["work_mode"] == "remote"

        impact = await client.post(
            f"/v1/goals/{goal_id}/impact",
            json={"proposed_spend_sen": 5_000},
            headers=auth(token),
        )
        assert impact.status_code == 200, impact.text
        assert impact.json()["proposed_spend_sen"] == 5_000
        assert impact.json()["calculation_version"] == "goal-plan-v1"

    async def test_requires_authentication(self, client):
        response = await client.post("/v1/goals", json=payload())
        assert response.status_code == 401

    async def test_soft_delete_preserves_history_and_removes_goal_from_planning(
        self, client, session
    ):
        token = await register(client)
        created = await client.post("/v1/goals", json=payload(), headers=auth(token))
        goal_id = uuid.UUID(created.json()["goal"]["goal_id"])
        goal = await session.get(Goal, goal_id)
        plan = (
            await session.execute(
                select(GoalPlanRecord).where(GoalPlanRecord.goal_id == goal_id)
            )
        ).scalar_one()
        goal.status = "active"
        plan.approval_status = "approved"
        await session.commit()

        preview = await client.get(
            f"/v1/goals/{goal_id}/deletion-impact", headers=auth(token)
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["goal_name"] == "Family trip"
        assert preview.json()["contribution_per_payday_released_sen"] > 0

        deleted = await client.delete(f"/v1/goals/{goal_id}", headers=auth(token))
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "deleted"
        assert deleted.json()["deleted_at"]
        assert deleted.json()["safe_today_after_sen"] >= deleted.json()["safe_today_before_sen"]

        await session.refresh(goal)
        assert goal.status == "deleted"
        assert goal.deleted_at is not None
        assert (
            await session.execute(
                select(GoalPlanRecord).where(GoalPlanRecord.goal_id == goal_id)
            )
        ).scalars().all()
        audit = (
            await session.execute(
                select(AuditEvent).where(AuditEvent.action == "goal.deleted")
            )
        ).scalar_one()
        assert audit.detail["goal_id"] == str(goal_id)

        assert (await client.get(f"/v1/goals/{goal_id}", headers=auth(token))).status_code == 404
        dashboard = await client.get("/v1/dashboard/today", headers=auth(token))
        assert str(goal_id) not in {item["id"] for item in dashboard.json()["goals"]}
        assert (await client.delete(f"/v1/goals/{goal_id}", headers=auth(token))).status_code == 404

    async def test_rejects_float_money_and_past_target(self, client):
        token = await register(client)
        floating = await client.post(
            "/v1/goals", json=payload(target_amount_sen=1200.5), headers=auth(token)
        )
        past = await client.post(
            "/v1/goals", json=payload(target_date="2026-09-02"), headers=auth(token)
        )
        assert floating.status_code == 422
        assert past.status_code == 422


def test_request_contract_keeps_target_date_as_a_date():
    request = GoalCreateRequest.model_validate(payload())
    assert request.target_date == date(2026, 12, 2)


async def test_structured_goal_graph_run_and_approval_resume(client, session):
    @asynccontextmanager
    async def shared():
        yield session

    client._transport.app.dependency_overrides[stream_session_factory] = lambda: shared
    await seed_demo_user(session)
    await session.commit()
    logged_in = await client.post(
        "/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    headers = auth(logged_in.json()["access_token"])
    blocked = await client.post(
        "/v1/goals/runs",
        json={
            "text": "",
            "explain": False,
            "intent": {
                "action": "create",
                "goal_type": "travel",
                "name": "Impossible rush goal",
                "target_amount_sen": 3_000_000,
                "current_saved_sen": 0,
                "target_date": "2027-04-04",
                "priority": "important",
            },
        },
        headers=headers,
    )
    assert blocked.status_code == 200, blocked.text
    blocked_body = blocked.json()
    assert blocked_body["approval"] is None
    assert blocked_body["calculation"]["affordability_status"] == "impossible"
    assert blocked_body["calculation"]["contribution_ratio_bp"] > 7_000
    assert len(blocked_body["scenarios"]) == 3
    assert (
        await client.get(f"/v1/goals/{blocked_body['goal_id']}", headers=headers)
    ).status_code == 404

    started = await client.post(
        "/v1/goals/runs",
        json={
            "text": "",
            "explain": False,
            "intent": {
                "action": "create",
                "goal_type": "travel",
                "name": "Penang trip",
                "target_amount_sen": 100_000,
                "current_saved_sen": 20_000,
                "target_date": "2026-12-31",
                "priority": "important",
            },
        },
        headers=headers,
    )
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["llm_calls"] == 0
    assert body["approval"]["base_plan_version"] == 1

    resumed = await client.post(
        f"/v1/butler/approvals/{body['approval']['approval_id']}/respond",
        json={"action": "accept"},
        headers=headers,
    )
    assert resumed.status_code == 200, resumed.text
    events = [
        json.loads(line.removeprefix("data: "))
        for line in resumed.text.splitlines()
        if line.startswith("data: ")
    ]
    assert events[-1]["type"] == "done"
    assert events[-1]["approval"]["status"] == "applied"

    plan = await client.get(f"/v1/goals/{body['goal_id']}/plan", headers=headers)
    assert plan.json()["version"] == 2
    assert plan.json()["approval_status"] == "approved"
