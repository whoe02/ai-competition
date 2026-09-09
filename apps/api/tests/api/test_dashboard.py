from kira.seed.demo import DEMO_EMAIL, DEMO_PASSWORD, seed_demo_user


async def demo_token(client, session) -> str:
    await seed_demo_user(session)
    await session.commit()
    response = await client.post(
        "/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


class TestDashboardAuth:
    async def test_requires_a_token(self, client):
        assert (await client.get("/v1/dashboard/today")).status_code == 401


class TestDashboardToday:
    async def test_returns_the_seeded_numbers(self, client, session):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/dashboard/today", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["currency"] == "MYR"
        assert body["display_name"] == "Floyd"
        assert body["balance_sen"] == 418040
        assert body["reserved_sen"] == 200300
        assert body["buffer_sen"] == 80000
        assert body["goal_reserve_sen"] == 21200
        assert body["unclaimed_sen"] == 116540
        assert body["per_day_sen"] == 5297
        assert body["spent_today_sen"] == 0
        assert body["safe_today_sen"] == 5297
        assert body["days_to_payday"] == 22

    async def test_lists_the_next_commitment(self, client, session):
        token = await demo_token(client, session)
        body = (
            await client.get("/v1/dashboard/today", headers={"Authorization": f"Bearer {token}"})
        ).json()
        assert body["next_commitment"]["name"] == "Rent"
        assert body["next_commitment"]["amount_sen"] == 120000
        assert body["next_commitment"]["due_date"] == "2026-09-05"
        assert body["next_commitment"]["days_until"] == 2
        assert body["next_commitment"]["protected"] is True
        assert body["commitment_count"] == 5

    async def test_reports_goals_with_their_projection(self, client, session):
        token = await demo_token(client, session)
        body = (
            await client.get("/v1/dashboard/today", headers={"Authorization": f"Bearer {token}"})
        ).json()
        goals = {goal["name"]: goal for goal in body["goals"]}
        assert goals["Emergency top-up"]["target_sen"] == 250000
        assert goals["Emergency top-up"]["saved_sen"] == 115000
        assert goals["Emergency top-up"]["months_left"] == 5
        assert goals["Emergency top-up"]["priority"] == "flexible"
        assert goals["Wedding"]["horizon"] == "long"

    async def test_counts_waiting_drafts_without_counting_their_money(self, client, session):
        token = await demo_token(client, session)
        body = (
            await client.get("/v1/dashboard/today", headers={"Authorization": f"Bearer {token}"})
        ).json()
        assert body["drafts_waiting"] == 2
        assert body["safe_today_sen"] == 5297

    async def test_never_leaks_a_float(self, client, session):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/dashboard/today", headers={"Authorization": f"Bearer {token}"}
        )

        def assert_no_floats(node):
            if isinstance(node, float):
                raise AssertionError(f"float in the response: {node}")
            if isinstance(node, dict):
                for value in node.values():
                    assert_no_floats(value)
            if isinstance(node, list):
                for value in node:
                    assert_no_floats(value)

        assert_no_floats(response.json())
