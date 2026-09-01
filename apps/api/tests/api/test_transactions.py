from kira.seed.demo import DEMO_EMAIL, DEMO_PASSWORD, seed_demo_user


async def demo_token(client, session) -> str:
    await seed_demo_user(session)
    await session.commit()
    response = await client.post(
        "/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestActivityAuth:
    async def test_requires_a_token(self, client):
        assert (await client.get("/v1/transactions")).status_code == 401

    async def test_settling_requires_a_token(self, client):
        response = await client.post(
            "/v1/transactions/00000000-0000-0000-0000-000000000000/confirm"
        )
        assert response.status_code == 401


class TestListTransactions:
    async def test_returns_drafts_and_the_confirmed_ledger(self, client, session):
        token = await demo_token(client, session)
        response = await client.get("/v1/transactions", headers=auth(token))
        assert response.status_code == 200, response.text
        body = response.json()
        assert [draft["merchant"] for draft in body["drafts"]] == [
            "Grab — office to KLCC",
            "Nasi Kandar Pelita",
        ]
        assert body["draft_total_sen"] == 3290
        assert body["spent_this_cycle_sen"] == 63135
        assert body["days"][0]["date"] == "2026-09-02"
        assert body["days"][0]["total_sen"] == 2870
        assert body["days"][0]["transactions"][0]["merchant"] == "Grab — KLCC to home"
        assert body["days"][0]["transactions"][0]["category"] == "transport"
        assert body["days"][0]["transactions"][0]["category_label"] == "Transport"

    async def test_carries_the_confidence_a_draft_was_read_with(self, client, session):
        token = await demo_token(client, session)
        body = (await client.get("/v1/transactions", headers=auth(token))).json()
        pelita = next(d for d in body["drafts"] if d["merchant"] == "Nasi Kandar Pelita")
        assert pelita["category_label"] == "Food & drink"
        assert pelita["confidence"] == 94
        assert pelita["source"] == "receipt"
        assert pelita["note"]

    async def test_never_leaks_a_float(self, client, session):
        token = await demo_token(client, session)
        response = await client.get("/v1/transactions", headers=auth(token))

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


class TestConfirm:
    async def test_confirming_lowers_todays_safe_to_spend(self, client, session):
        token = await demo_token(client, session)
        before = (await client.get("/v1/dashboard/today", headers=auth(token))).json()
        draft = next(
            d
            for d in (await client.get("/v1/transactions", headers=auth(token))).json()["drafts"]
            if d["merchant"] == "Nasi Kandar Pelita"
        )

        response = await client.post(f"/v1/transactions/{draft['id']}/confirm", headers=auth(token))

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "confirmed"
        after = (await client.get("/v1/dashboard/today", headers=auth(token))).json()
        assert before["safe_today_sen"] == 5297
        assert after["safe_today_sen"] == 3321
        assert after["drafts_waiting"] == 1

    async def test_a_confirmed_draft_joins_its_day(self, client, session):
        token = await demo_token(client, session)
        draft = (await client.get("/v1/transactions", headers=auth(token))).json()["drafts"][0]
        await client.post(f"/v1/transactions/{draft['id']}/confirm", headers=auth(token))
        body = (await client.get("/v1/transactions", headers=auth(token))).json()
        assert body["days"][0]["date"] == "2026-09-03"
        assert body["days"][0]["transactions"][0]["merchant"] == draft["merchant"]

    async def test_an_unknown_id_is_a_404(self, client, session):
        token = await demo_token(client, session)
        response = await client.post(
            "/v1/transactions/00000000-0000-0000-0000-000000000000/confirm", headers=auth(token)
        )
        assert response.status_code == 404

    async def test_confirming_twice_is_a_409(self, client, session):
        token = await demo_token(client, session)
        draft = (await client.get("/v1/transactions", headers=auth(token))).json()["drafts"][0]
        await client.post(f"/v1/transactions/{draft['id']}/confirm", headers=auth(token))
        again = await client.post(f"/v1/transactions/{draft['id']}/confirm", headers=auth(token))
        assert again.status_code == 409


class TestDiscard:
    async def test_discarding_leaves_the_money_alone(self, client, session):
        token = await demo_token(client, session)
        before = (await client.get("/v1/dashboard/today", headers=auth(token))).json()
        draft = (await client.get("/v1/transactions", headers=auth(token))).json()["drafts"][0]

        response = await client.post(f"/v1/transactions/{draft['id']}/discard", headers=auth(token))

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "discarded"
        after = (await client.get("/v1/dashboard/today", headers=auth(token))).json()
        assert after["safe_today_sen"] == before["safe_today_sen"]
        assert after["drafts_waiting"] == 1

    async def test_a_discarded_draft_never_reaches_the_ledger(self, client, session):
        token = await demo_token(client, session)
        draft = (await client.get("/v1/transactions", headers=auth(token))).json()["drafts"][0]
        await client.post(f"/v1/transactions/{draft['id']}/discard", headers=auth(token))
        body = (await client.get("/v1/transactions", headers=auth(token))).json()
        assert draft["id"] not in {d["id"] for d in body["drafts"]}
        listed = {txn["id"] for day in body["days"] for txn in day["transactions"]}
        assert draft["id"] not in listed


class TestUnconfirm:
    async def test_gives_the_money_back_to_today(self, client, session):
        token = await demo_token(client, session)
        before = (await client.get("/v1/dashboard/today", headers=auth(token))).json()
        draft = (await client.get("/v1/transactions", headers=auth(token))).json()["drafts"][0]
        await client.post(f"/v1/transactions/{draft['id']}/confirm", headers=auth(token))

        response = await client.post(
            f"/v1/transactions/{draft['id']}/unconfirm", headers=auth(token)
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "draft"
        after = (await client.get("/v1/dashboard/today", headers=auth(token))).json()
        assert after["safe_today_sen"] == before["safe_today_sen"]
        assert after["drafts_waiting"] == before["drafts_waiting"]

    async def test_the_row_rejoins_the_waiting_drafts(self, client, session):
        token = await demo_token(client, session)
        draft = (await client.get("/v1/transactions", headers=auth(token))).json()["drafts"][0]
        await client.post(f"/v1/transactions/{draft['id']}/confirm", headers=auth(token))
        await client.post(f"/v1/transactions/{draft['id']}/unconfirm", headers=auth(token))
        body = (await client.get("/v1/transactions", headers=auth(token))).json()
        assert draft["id"] in {d["id"] for d in body["drafts"]}
        listed = {txn["id"] for day in body["days"] for txn in day["transactions"]}
        assert draft["id"] not in listed

    async def test_unconfirming_a_draft_is_a_409(self, client, session):
        token = await demo_token(client, session)
        draft = (await client.get("/v1/transactions", headers=auth(token))).json()["drafts"][0]
        response = await client.post(
            f"/v1/transactions/{draft['id']}/unconfirm", headers=auth(token)
        )
        assert response.status_code == 409

    async def test_an_unknown_id_is_a_404(self, client, session):
        token = await demo_token(client, session)
        response = await client.post(
            "/v1/transactions/00000000-0000-0000-0000-000000000000/unconfirm", headers=auth(token)
        )
        assert response.status_code == 404

    async def test_requires_a_token(self, client):
        response = await client.post(
            "/v1/transactions/00000000-0000-0000-0000-000000000000/unconfirm"
        )
        assert response.status_code == 401


async def voice_draft(client, token) -> dict:
    """The draft the fake reader is only 71% sure of: RM14.00 heard for RM19.90."""
    body = (await client.get("/v1/transactions", headers=auth(token))).json()
    draft = next(d for d in body["drafts"] if d["merchant"] == "Grab — office to KLCC")
    assert draft["amount_sen"] == 1400
    assert draft["confidence"] == 71
    return draft


class TestCorrect:
    async def test_correcting_requires_a_token(self, client):
        response = await client.patch(
            "/v1/transactions/00000000-0000-0000-0000-000000000000",
            json={"amount_sen": 1990},
        )
        assert response.status_code == 401

    async def test_corrects_a_drafts_amount(self, client, session):
        token = await demo_token(client, session)
        draft = await voice_draft(client, token)

        response = await client.patch(
            f"/v1/transactions/{draft['id']}", json={"amount_sen": 1990}, headers=auth(token)
        )

        assert response.status_code == 200, response.text
        assert response.json()["amount_sen"] == 1990
        assert response.json()["status"] == "draft"

    async def test_correcting_the_amount_nulls_the_confidence(self, client, session):
        token = await demo_token(client, session)
        draft = await voice_draft(client, token)

        response = await client.patch(
            f"/v1/transactions/{draft['id']}", json={"amount_sen": 1990}, headers=auth(token)
        )

        assert response.json()["confidence"] is None
        listed = (await client.get("/v1/transactions", headers=auth(token))).json()
        still_waiting = next(d for d in listed["drafts"] if d["id"] == draft["id"])
        assert still_waiting["confidence"] is None
        assert listed["draft_total_sen"] == 1890 + 1990

    async def test_corrects_the_merchant_category_and_note(self, client, session):
        token = await demo_token(client, session)
        draft = await voice_draft(client, token)

        response = await client.patch(
            f"/v1/transactions/{draft['id']}",
            json={"merchant": "Grab — office to Mid Valley", "category": "fun", "note": "Fixed."},
            headers=auth(token),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["merchant"] == "Grab — office to Mid Valley"
        assert body["category_label"] == "Fun"
        assert body["note"] == "Fixed."
        assert body["amount_sen"] == 1400  # untouched, and so still the reader's
        assert body["confidence"] == 71

    async def test_a_confirmed_transaction_is_a_409(self, client, session):
        token = await demo_token(client, session)
        draft = await voice_draft(client, token)
        await client.post(f"/v1/transactions/{draft['id']}/confirm", headers=auth(token))

        response = await client.patch(
            f"/v1/transactions/{draft['id']}", json={"amount_sen": 1990}, headers=auth(token)
        )

        assert response.status_code == 409
        assert "Unconfirm it first" in response.json()["detail"]

    async def test_a_discarded_transaction_is_a_409(self, client, session):
        token = await demo_token(client, session)
        draft = await voice_draft(client, token)
        await client.post(f"/v1/transactions/{draft['id']}/discard", headers=auth(token))

        response = await client.patch(
            f"/v1/transactions/{draft['id']}", json={"amount_sen": 1990}, headers=auth(token)
        )

        assert response.status_code == 409

    async def test_an_unknown_id_is_a_404(self, client, session):
        token = await demo_token(client, session)
        response = await client.patch(
            "/v1/transactions/00000000-0000-0000-0000-000000000000",
            json={"amount_sen": 1990},
            headers=auth(token),
        )
        assert response.status_code == 404

    async def test_another_users_draft_is_a_404(self, client, session):
        token = await demo_token(client, session)
        draft = await voice_draft(client, token)
        stranger = (
            await client.post(
                "/v1/auth/register",
                json={
                    "email": "stranger@kira.app",
                    "password": "not-your-money",
                    "display_name": "Stranger",
                },
            )
        ).json()["access_token"]

        response = await client.patch(
            f"/v1/transactions/{draft['id']}", json={"amount_sen": 1}, headers=auth(stranger)
        )

        assert response.status_code == 404
        mine = await voice_draft(client, token)
        assert mine["amount_sen"] == 1400

    async def test_a_zero_amount_is_rejected(self, client, session):
        token = await demo_token(client, session)
        draft = await voice_draft(client, token)
        response = await client.patch(
            f"/v1/transactions/{draft['id']}", json={"amount_sen": 0}, headers=auth(token)
        )
        assert response.status_code == 422
        assert (await voice_draft(client, token))["amount_sen"] == 1400

    async def test_a_negative_amount_is_rejected(self, client, session):
        token = await demo_token(client, session)
        draft = await voice_draft(client, token)
        response = await client.patch(
            f"/v1/transactions/{draft['id']}", json={"amount_sen": -1990}, headers=auth(token)
        )
        assert response.status_code == 422
        assert (await voice_draft(client, token))["amount_sen"] == 1400

    async def test_an_empty_correction_is_rejected(self, client, session):
        token = await demo_token(client, session)
        draft = await voice_draft(client, token)
        response = await client.patch(
            f"/v1/transactions/{draft['id']}", json={}, headers=auth(token)
        )
        assert response.status_code == 422

    async def test_the_corrected_amount_is_what_reaches_safe_to_spend(self, client, session):
        token = await demo_token(client, session)
        draft = await voice_draft(client, token)
        before = (await client.get("/v1/dashboard/today", headers=auth(token))).json()

        await client.patch(
            f"/v1/transactions/{draft['id']}", json={"amount_sen": 1990}, headers=auth(token)
        )
        # A draft is not counted, so nothing has moved yet.
        during = (await client.get("/v1/dashboard/today", headers=auth(token))).json()
        await client.post(f"/v1/transactions/{draft['id']}/confirm", headers=auth(token))
        after = (await client.get("/v1/dashboard/today", headers=auth(token))).json()

        assert during["safe_today_sen"] == before["safe_today_sen"] == 5297
        assert after["safe_today_sen"] == 3216
        ledger = (await client.get("/v1/transactions", headers=auth(token))).json()
        counted = next(
            txn
            for day in ledger["days"]
            for txn in day["transactions"]
            if txn["id"] == draft["id"]
        )
        assert counted["amount_sen"] == 1990


class TestFilter:
    async def test_narrows_the_ledger_to_one_category(self, client, session):
        token = await demo_token(client, session)
        body = (
            await client.get("/v1/transactions", params={"category": "health"}, headers=auth(token))
        ).json()
        merchants = {txn["merchant"] for day in body["days"] for txn in day["transactions"]}
        # The seeded ninety days carry their own health spending, so this is a
        # subset check; the cycle total below is what pins the filter's scope.
        assert {"Watsons", "Guardian pharmacy"} <= merchants
        assert body["spent_this_cycle_sen"] == 6040

    async def test_offers_a_chip_for_every_category_present(self, client, session):
        token = await demo_token(client, session)
        body = (await client.get("/v1/transactions", headers=auth(token))).json()
        chips = {chip["slug"]: chip for chip in body["categories"]}
        assert chips["food"]["label"] == "Food & drink"
        assert chips["food"]["count"] == 3
        assert "bills" not in chips

    async def test_the_chips_do_not_move_when_a_filter_is_on(self, client, session):
        token = await demo_token(client, session)
        everything = (await client.get("/v1/transactions", headers=auth(token))).json()
        filtered = (
            await client.get("/v1/transactions", params={"category": "food"}, headers=auth(token))
        ).json()
        assert filtered["categories"] == everything["categories"]

    async def test_a_filter_never_hides_a_waiting_draft(self, client, session):
        token = await demo_token(client, session)
        body = (
            await client.get("/v1/transactions", params={"category": "health"}, headers=auth(token))
        ).json()
        assert len(body["drafts"]) == 2

    async def test_an_unknown_category_is_an_empty_ledger_not_an_error(self, client, session):
        token = await demo_token(client, session)
        response = await client.get(
            "/v1/transactions", params={"category": "pet-grooming"}, headers=auth(token)
        )
        assert response.status_code == 200
        assert response.json()["days"] == []
