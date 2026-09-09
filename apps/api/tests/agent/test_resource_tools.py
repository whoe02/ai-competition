from __future__ import annotations

import uuid

from sqlalchemy import select

from kira.agent import events
from kira.agent.run import stream_turn
from kira.agent.tools import REGISTRY, ToolContext
from kira.db.models import Account, Transaction
from kira.seed.demo import DEMO_TODAY
from kira.services.dashboard import today_dashboard
from kira.services.snapshot import load_snapshot
from tests.agent.conftest import scripted_factory


async def context(session, user):
    return ToolContext(
        session=session,
        user=user,
        today=DEMO_TODAY,
        snapshot=await load_snapshot(session, user, DEMO_TODAY),
        dashboard=await today_dashboard(session, user, DEMO_TODAY),
    )


async def test_search_records_combines_merchant_date_amount_and_status(session, butler):
    user, _ = butler
    spec = REGISTRY.get("search_records")
    args = spec.args_model.model_validate(
        {
            "resource": "transactions",
            "filters": [
                {"field": "merchant", "op": "contains", "value": "Village"},
                {"field": "occurred_on", "op": "gte", "value": "2026-09-01"},
                {"field": "amount_sen", "op": "lte", "value": 10000},
                {"field": "status", "op": "eq", "value": "confirmed"},
            ],
        }
    )
    result = await spec.handler(await context(session, user), args)
    assert result.value["resource"] == "transactions"
    assert all("Village" in row["merchant"] for row in result.value["records"])


def test_search_records_refuses_undeclared_fields():
    spec = REGISTRY.get("search_records")
    try:
        spec.args_model.model_validate(
            {"resource": "transactions", "filters": [{"field": "user_id", "value": "x"}]}
        )
    except ValueError:
        pass
    else:
        raise AssertionError("user_id must never become a model-controlled filter")


def test_all_generated_writes_keep_a_human_summary():
    for name in (
        "create_goal",
        "update_goal",
        "record_goal_contribution",
        "create_account",
        "update_account",
        "update_profile",
        "update_transaction",
    ):
        assert REGISTRY.get(name).summarise is not None


async def test_generated_profile_and_account_writes_use_safe_service_paths(session, butler):
    user, _ = butler
    tools = await context(session, user)
    profile = REGISTRY.get("update_profile")
    await profile.handler(tools, profile.args_model.model_validate({"display_name": "Sam"}))
    create = REGISTRY.get("create_account")
    result = await create.handler(
        tools, create.args_model.model_validate({"name": "Travel cash", "kind": "cash"})
    )
    account = (
        await session.execute(select(Account).where(Account.id == uuid.UUID(result.value["id"])))
    ).scalar_one()
    assert user.display_name == "Sam"
    assert account.opening_balance.sen == 0


async def test_update_transaction_keeps_a_confirmed_row_confirmed(session, butler):
    user, _ = butler
    transaction = (
        (
            await session.execute(
                select(Transaction).where(
                    Transaction.user_id == user.id,
                    Transaction.status == "confirmed",
                )
            )
        )
        .scalars()
        .first()
    )
    spec = REGISTRY.get("update_transaction")
    result = await spec.handler(
        await context(session, user),
        spec.args_model.model_validate(
            {"transaction_id": str(transaction.id), "merchant": "Corrected merchant"}
        ),
    )
    assert result.value["status"] == "confirmed"
    assert result.value["merchant"] == "Corrected merchant"


async def test_ui_tool_emits_a_reversible_app_action(session, butler):
    user, thread = butler
    streamed = [
        item
        async for item in stream_turn(
            session,
            user,
            thread,
            text="show my food spending",
            message_id=uuid.uuid4(),
            today=DEMO_TODAY,
            model_factory=scripted_factory(
                ("control_app", {"action": "navigate", "tab": "activity", "category": "food"})
            ),
        )
    ]
    action = next(item for item in streamed if item["type"] == events.APP_ACTION)
    assert action == {
        "type": "app_action",
        "action": "navigate",
        "tab": "activity",
        "category": "food",
    }
