"""The prompt's logging clause: what turns a statement of spending into a proposal."""

from __future__ import annotations

from kira.agent.prompt import logging_block, system_prompt


class TestLoggingBlock:
    def test_it_is_absent_when_the_model_cannot_log_anything(self):
        assert logging_block(("list_activity", "get_financial_snapshot")) == ""

    def test_it_appears_when_add_transaction_is_on_the_turn(self):
        assert "add_transaction" in logging_block(("add_transaction", "list_activity"))

    def test_it_says_to_ask_rather_than_invent_a_missing_amount(self):
        block = logging_block(("add_transaction",))
        assert "ask" in block.lower()
        assert "invent" in block.lower() or "guess" in block.lower()

    def test_it_says_the_date_defaults_to_today(self):
        assert "today" in logging_block(("add_transaction",)).lower()


class TestAssembly:
    def test_the_clause_reaches_the_assembled_prompt(self):
        text = system_prompt(
            context="", memory="", history="", tool_names=("add_transaction",)
        )
        assert logging_block(("add_transaction",)) in text

    def test_a_read_only_turn_carries_no_logging_clause(self):
        text = system_prompt(context="", memory="", history="", tool_names=("list_goals",))
        assert "already spent" not in text
