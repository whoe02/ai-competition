from kira.adapters.local_capture import (
    _is_transaction_candidate,
    _merchant_from_voice,
    _money_from_text,
)


def test_money_parser_uses_the_largest_receipt_amount():
    assert _money_from_text("Subtotal 12.50\nSST 0.75\nTOTAL 13.25").sen == 1325


def test_money_parser_accepts_thousands_separators():
    assert _money_from_text("TOTAL RM1,234.50").sen == 123450


def test_money_parser_accepts_spoken_ringgit_amounts():
    assert _money_from_text("fourteen ringgit").sen == 1400


def test_voice_merchant_parser_handles_a_simple_at_phrase():
    assert _merchant_from_voice("I spent twelve ringgit at Watsons") == "Watsons"


def test_voice_question_with_an_amount_is_not_a_transaction():
    assert _is_transaction_candidate(
        "Can I afford RM60 dinner tonight?", _money_from_text("RM60")
    ) is False


def test_compact_spoken_expense_is_a_transaction():
    assert _is_transaction_candidate(
        "Grab from the office to KLCC, fourteen ringgit",
        _money_from_text("fourteen ringgit"),
    ) is True
