"""What a read makes of the category, which is the field it is least sure of."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from kira.adapters.protocols import ReceiptRead, VoiceRead
from kira.money import Money
from kira.services import capture

TODAY = date(2026, 9, 3)


@dataclass(frozen=True)
class StubAdapters:
    ocr: object = None
    voice: object = None


class OneReceipt:
    def __init__(self, merchant: str) -> None:
        self.merchant = merchant

    def read_receipt(self, image: bytes) -> ReceiptRead:
        return ReceiptRead(
            merchant=self.merchant,
            amount=Money(1200),
            occurred_on=TODAY,
            confidence=90,
            note="",
        )


class OneNote:
    def __init__(self, transcript: str) -> None:
        self.transcript = transcript

    def transcribe(self, audio: bytes) -> VoiceRead:
        return VoiceRead(
            transcript=self.transcript,
            merchant="Somewhere",
            amount=Money(1200),
            confidence=80,
            note="",
        )


@pytest.fixture
def reading(monkeypatch):
    def use(*, ocr=None, voice=None):
        monkeypatch.setattr(
            capture, "get_adapters", lambda: StubAdapters(ocr=ocr, voice=voice)
        )

    return use


class TestReceiptCategory:
    @pytest.mark.parametrize(
        ("merchant", "expected"),
        [
            ("Nasi Kandar Pelita", "food"),
            ("Watsons Pharmacy", "health"),
            ("Village Grocer", "groceries"),
        ],
    )
    def test_it_reads_the_category_off_the_merchant(self, reading, merchant, expected):
        reading(ocr=OneReceipt(merchant))
        read = capture.read_receipt(b"jpeg", today=TODAY, max_bytes=10_000)
        assert read.category == expected

    def test_an_unrecognisable_merchant_is_not_forced_into_a_category(self, reading):
        reading(ocr=OneReceipt("Syarikat Bin Ahmad"))
        read = capture.read_receipt(b"jpeg", today=TODAY, max_bytes=10_000)
        assert read.category == "uncategorised"


class TestVoiceCategory:
    def test_it_reads_the_category_off_what_was_said(self, reading):
        reading(voice=OneNote("Grab from the office to KLCC, fourteen ringgit"))
        read = capture.transcribe(b"wav", today=TODAY, max_bytes=10_000)
        assert read.category == "transport"

    def test_a_different_note_gets_a_different_category(self, reading):
        reading(voice=OneNote("Bought panadol at the pharmacy"))
        read = capture.transcribe(b"wav", today=TODAY, max_bytes=10_000)
        assert read.category == "health"
