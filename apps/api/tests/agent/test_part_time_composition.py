from __future__ import annotations

from langchain_core.messages import ToolMessage

from kira.agent.nodes.compose import _part_time_reply
from kira.agent.nodes.guard import route_after_tools


def test_successful_work_search_uses_the_verified_display_contract_only():
    reply = _part_time_reply([
        ToolMessage(
            name="recommend_part_time_jobs",
            tool_call_id="work-search",
            content=(
                '{"status":"available","goal_name":"Home deposit",'
                '"recommendations":[{"role_title":"Verified role"}]}'
            ),
        )
    ])

    assert reply == "Verified live work ideas for Home deposit."


def test_unsuccessful_work_search_does_not_create_unverified_alternatives():
    reply = _part_time_reply([
        ToolMessage(
            name="recommend_part_time_jobs",
            tool_call_id="work-search",
            content=(
                '{"status":"not_available","goal_name":"Home deposit",'
                '"reason":"No live listings matched the selected availability."}'
            ),
        )
    ])

    assert reply is not None
    assert "No live listings matched the selected availability." in reply
    assert "haven’t listed unverified alternatives" in reply


def test_incomplete_work_search_asks_once_instead_of_retrying_without_inputs():
    message = ToolMessage(
        name="recommend_part_time_jobs",
        tool_call_id="work-search",
        content=(
            '{"status":"needs_input","goal_name":"Home deposit",'
            '"missing_fields":["goal_reference","available_hours_per_week","work_mode"]}'
        ),
    )

    reply = _part_time_reply([message])

    assert reply is not None
    assert "which goal" in reply
    assert "how many hours" in reply
    assert "remote, on-site, or either" in reply
    assert route_after_tools(
        {"tools_used": ["recommend_part_time_jobs"], "messages": [message]}
    ) == "compose"
