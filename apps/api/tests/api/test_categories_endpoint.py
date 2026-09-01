"""The category vocabulary, published so a client can offer it rather than invent it."""

from __future__ import annotations

import pytest

from kira.categories import slugs
from kira.seed.demo import DEMO_EMAIL, DEMO_PASSWORD, seed_demo_user


@pytest.fixture
async def signed_in(client, session):
    await seed_demo_user(session)
    await session.commit()
    response = await client.post(
        "/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return client


class TestCategoryList:
    async def test_it_needs_a_token(self, client):
        assert (await client.get("/v1/categories")).status_code == 401

    async def test_it_publishes_the_whole_vocabulary(self, signed_in):
        body = (await signed_in.get("/v1/categories")).json()
        assert [item["slug"] for item in body] == list(slugs())

    async def test_each_one_carries_the_label_a_person_reads(self, signed_in):
        body = (await signed_in.get("/v1/categories")).json()
        assert {"slug": "food", "label": "Food & drink"} in body
