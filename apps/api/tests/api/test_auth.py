REGISTER = {
    "email": "demo@kira.app",
    "password": "correct horse battery staple",
    "display_name": "Floyd",
}


async def register(client) -> str:
    response = await client.post("/v1/auth/register", json=REGISTER)
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


class TestHealth:
    async def test_health_needs_no_auth(self, client):
        response = await client.get("/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestRegister:
    async def test_returns_an_access_token_and_sets_a_refresh_cookie(self, client):
        response = await client.post("/v1/auth/register", json=REGISTER)
        assert response.status_code == 201
        assert response.json()["access_token"]
        assert response.json()["token_type"] == "bearer"
        assert "kira_refresh" in response.cookies

    async def test_never_returns_the_password_hash(self, client):
        response = await client.post("/v1/auth/register", json=REGISTER)
        assert "password" not in response.text
        assert "hash" not in response.text

    async def test_duplicate_email_is_rejected(self, client):
        await client.post("/v1/auth/register", json=REGISTER)
        response = await client.post("/v1/auth/register", json=REGISTER)
        assert response.status_code == 409

    async def test_short_password_is_rejected(self, client):
        response = await client.post("/v1/auth/register", json={**REGISTER, "password": "short"})
        assert response.status_code == 422


class TestLogin:
    async def test_correct_password_succeeds(self, client):
        await register(client)
        response = await client.post(
            "/v1/auth/login", json={"email": REGISTER["email"], "password": REGISTER["password"]}
        )
        assert response.status_code == 200
        assert response.json()["access_token"]

    async def test_wrong_password_fails(self, client):
        await register(client)
        response = await client.post(
            "/v1/auth/login", json={"email": REGISTER["email"], "password": "wrong"}
        )
        assert response.status_code == 401

    async def test_unknown_email_fails_the_same_way(self, client):
        response = await client.post(
            "/v1/auth/login", json={"email": "nobody@kira.app", "password": "whatever"}
        )
        assert response.status_code == 401


class TestMe:
    async def test_returns_the_authenticated_user(self, client):
        token = await register(client)
        response = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["email"] == REGISTER["email"]
        assert response.json()["display_name"] == "Floyd"

    async def test_missing_token_is_401(self, client):
        response = await client.get("/v1/auth/me")
        assert response.status_code == 401

    async def test_garbage_token_is_401(self, client):
        response = await client.get("/v1/auth/me", headers={"Authorization": "Bearer nonsense"})
        assert response.status_code == 401

    async def test_recurring_income_profile_is_forecast_not_cash(self, client):
        token = await register(client)
        headers = {"Authorization": f"Bearer {token}"}
        balance_before = (await client.get("/v1/dashboard/today", headers=headers)).json()[
            "balance_sen"
        ]
        updated = await client.patch(
            "/v1/auth/me",
            headers=headers,
            json={"monthly_income_sen": 500_000, "next_payday": "2026-09-25"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["monthly_income_sen"] == 500_000
        balance_after = (await client.get("/v1/dashboard/today", headers=headers)).json()[
            "balance_sen"
        ]
        assert balance_after == balance_before


class TestRefresh:
    async def test_rotates_the_token(self, client):
        await register(client)
        first_cookie = client.cookies["kira_refresh"]
        response = await client.post("/v1/auth/refresh")
        assert response.status_code == 200
        assert response.json()["access_token"]
        assert client.cookies["kira_refresh"] != first_cookie

    async def test_a_used_token_cannot_be_reused(self, client):
        await register(client)
        used = client.cookies["kira_refresh"]
        await client.post("/v1/auth/refresh")
        response = await client.post("/v1/auth/refresh", headers={"Cookie": f"kira_refresh={used}"})
        assert response.status_code == 401

    async def test_without_a_cookie_is_401(self, client):
        response = await client.post("/v1/auth/refresh")
        assert response.status_code == 401


class TestLogout:
    async def test_revokes_the_refresh_token(self, client):
        await register(client)
        response = await client.post("/v1/auth/logout")
        assert response.status_code == 204
        assert (await client.post("/v1/auth/refresh")).status_code == 401
