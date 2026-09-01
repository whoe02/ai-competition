"""A manual run is the same briefing path the worker uses."""

from contextlib import asynccontextmanager

from sqlalchemy import select

from kira.api.deps import stream_session_factory
from kira.db.models import TXN_CONFIRMED, Transaction
from kira.seed.demo import DEMO_EMAIL, DEMO_PASSWORD, seed_demo_user


async def headers(client, session) -> dict[str, str]:
    await seed_demo_user(session)
    await session.commit()
    response = await client.post(
        "/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_a_briefing_run_requires_a_token(client):
    assert (await client.post("/v1/briefings/run")).status_code == 401


async def test_a_manual_run_creates_one_idempotent_briefing(client, session):
    auth = await headers(client, session)
    first = await client.post("/v1/briefings/run", headers=auth)
    second = await client.post("/v1/briefings/run", headers=auth)

    assert first.status_code == 201, first.text
    assert first.json()["created"] is True
    assert first.json()["proposal_count"] == 2
    assert second.status_code == 200, second.text
    assert second.json()["created"] is False

    inbox = await client.get("/v1/briefings/today", headers=auth)
    assert inbox.status_code == 200
    assert inbox.json()["proposal_count"] == 2
    assert inbox.json()["pending_proposal_count"] == 2


async def test_a_worker_proposal_revalidates_then_confirms_only_after_acceptance(client, session):
    @asynccontextmanager
    async def shared():
        yield session

    client._transport.app.dependency_overrides[stream_session_factory] = lambda: shared
    auth = await headers(client, session)
    await client.post("/v1/briefings/run", headers=auth)
    thread = (await client.get("/v1/butler/thread", headers=auth)).json()
    approval_id = thread["pending_approvals"][0]["id"]

    response = await client.post(
        f"/v1/butler/approvals/{approval_id}/respond",
        headers=auth,
        json={"action": "accept"},
    )

    assert response.status_code == 200
    drafts = (
        await session.execute(select(Transaction).where(Transaction.status == TXN_CONFIRMED))
    ).scalars().all()
    assert any(transaction.merchant == "Nasi Kandar Pelita" for transaction in drafts)
