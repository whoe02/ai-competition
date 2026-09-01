"""The track record over HTTP."""

from kira.seed.demo import DEMO_EMAIL, DEMO_PASSWORD, seed_demo_user


async def demo_headers(client, session) -> dict[str, str]:
    await seed_demo_user(session)
    await session.commit()
    response = await client.post(
        "/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_hindsight_requires_a_token(client):
    assert (await client.get("/v1/hindsight")).status_code == 401


async def test_hindsight_returns_a_scored_record(client, session):
    headers = await demo_headers(client, session)

    response = await client.get("/v1/hindsight", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["days"] > 0
    assert 0 <= body["follow_rate_bp"] <= 10000
    assert body["followed"] <= body["days"]
    assert body["mean_abs_deviation"]["currency"] == "MYR"
    assert body["assumption"]


async def test_the_recent_strip_is_the_tail_of_the_window(client, session):
    headers = await demo_headers(client, session)
    body = (await client.get("/v1/hindsight", headers=headers)).json()

    recent = body["recent"]
    assert 0 < len(recent) <= 14
    assert recent == sorted(recent, key=lambda day: day["on"])
    for day in recent:
        assert day["followed"] == (day["actual"]["sen"] <= day["advised"]["sen"])


async def test_the_window_is_validated_at_the_edge(client, session):
    headers = await demo_headers(client, session)
    assert (await client.get("/v1/hindsight?window=0", headers=headers)).status_code == 422
    assert (await client.get("/v1/hindsight?window=999", headers=headers)).status_code == 422


async def test_a_narrow_window_scores_fewer_days(client, session):
    headers = await demo_headers(client, session)
    wide = (await client.get("/v1/hindsight?window=90", headers=headers)).json()
    narrow = (await client.get("/v1/hindsight?window=7", headers=headers)).json()
    assert narrow["days"] <= 7 < wide["days"]
