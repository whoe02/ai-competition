"""The forecast over HTTP."""

from kira.seed.demo import DEMO_EMAIL, DEMO_PASSWORD, seed_demo_user


async def demo_headers(client, session) -> dict[str, str]:
    await seed_demo_user(session)
    await session.commit()
    response = await client.post(
        "/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_foresight_requires_a_token(client):
    response = await client.get("/v1/foresight")
    assert response.status_code == 401


async def test_foresight_returns_bands_and_drivers(client, session):
    headers = await demo_headers(client, session)

    response = await client.get("/v1/foresight?horizon=90", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["horizon_days"] == 90
    assert len(body["p50"]) == 90
    assert body["p10"][0]["sen"] <= body["p90"][0]["sen"]
    assert body["assumption"]
    assert all(0 <= outlook["probability_bp"] <= 10000 for outlook in body["outlooks"])


async def test_the_horizon_is_validated_at_the_edge(client, session):
    headers = await demo_headers(client, session)
    assert (await client.get("/v1/foresight?horizon=0", headers=headers)).status_code == 422
    assert (await client.get("/v1/foresight?horizon=999", headers=headers)).status_code == 422


async def test_scenarios_compare_the_levers_posted(client, session):
    headers = await demo_headers(client, session)
    listing = (await client.get("/v1/foresight", headers=headers)).json()
    goal_id = listing["outlooks"][0]["goal_id"]

    response = await client.post(
        "/v1/foresight/scenarios",
        headers=headers,
        json={
            "horizon_days": 60,
            "levers": [{"kind": "goal_monthly", "target_id": goal_id, "delta_sen": 5000}],
        },
    )
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["lever"]["target_id"] == goal_id


async def test_an_unknown_lever_kind_is_rejected_before_the_engine(client, session):
    headers = await demo_headers(client, session)
    response = await client.post(
        "/v1/foresight/scenarios",
        headers=headers,
        json={
            "horizon_days": 60,
            "levers": [{"kind": "sell_the_car", "target_id": "x", "delta_sen": 1}],
        },
    )
    assert response.status_code == 422


async def test_the_forecast_writes_nothing(client, session):
    """A read is a read. This endpoint touches no financial table."""
    from sqlalchemy import func, select

    from kira.db.models import Transaction

    headers = await demo_headers(client, session)
    before = (await session.execute(select(func.count()).select_from(Transaction))).scalar_one()

    await client.get("/v1/foresight", headers=headers)

    after = (await session.execute(select(func.count()).select_from(Transaction))).scalar_one()
    assert before == after
