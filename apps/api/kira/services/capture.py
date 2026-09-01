"""Receipt and voice capture: turning a photo or a recording into a proposal.

Nothing here writes. A machine read is a proposal, and the only thing a
proposal can become is a draft the user confirms — so this module returns
fields and confidences, and leaves the ledger alone.

The providers behind it are chosen in `kira.adapters.registry`; swapping the
deterministic fakes for a real OCR or speech vendor changes nothing above
this line.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from kira.adapters.registry import get_adapters
from kira.categories import infer, label_for
from kira.db.models import SOURCE_RECEIPT, SOURCE_VOICE
from kira.money import Money

CAPTURE_RECEIPT = "receipt"
CAPTURE_VOICE = "voice"


class CaptureRejected(Exception):
    """The upload is not something a reader can be pointed at."""


@dataclass(frozen=True, slots=True)
class CaptureField:
    """One read field with the confidence the reader had in it.

    The UI underlines low confidence rather than hiding it: the user correcting
    a doubtful field is the point of showing it.
    """

    label: str
    value: str
    confidence: int


@dataclass(frozen=True, slots=True)
class CaptureRead:
    kind: str
    source: str
    merchant: str
    amount_sen: int
    occurred_on: date
    category: str
    confidence: int
    note: str
    transcript: str
    fields: tuple[CaptureField, ...]


def _fields(
    merchant: str, amount_sen: int, occurred_on: date, category: str, confidence: int
) -> tuple[CaptureField, ...]:
    """The reader is least sure of the category: it inferred it, it did not read it."""
    return (
        CaptureField("Merchant", merchant, confidence),
        CaptureField("Total", f"RM{Money(amount_sen).ringgit_str()}", confidence),
        CaptureField("Date", occurred_on.strftime("%-d %b %Y"), confidence),
        CaptureField("Category", label_for(category), max(0, confidence - 11)),
    )


def _guard(payload: bytes, limit: int) -> None:
    if not payload:
        raise CaptureRejected("nothing was uploaded")
    if len(payload) > limit:
        raise CaptureRejected("that file is larger than the reader accepts")


def read_receipt(image: bytes, *, today: date, max_bytes: int) -> CaptureRead:
    _guard(image, max_bytes)
    result = get_adapters().ocr.read_receipt(image)
    occurred_on = result.occurred_on or today
    category = infer(f"{result.merchant} {result.note}")
    return CaptureRead(
        kind=CAPTURE_RECEIPT,
        source=SOURCE_RECEIPT,
        merchant=result.merchant,
        amount_sen=result.amount.sen,
        occurred_on=occurred_on,
        category=category,
        confidence=result.confidence,
        note=result.note,
        transcript="",
        fields=_fields(
            result.merchant, result.amount.sen, occurred_on, category, result.confidence
        ),
    )


def transcribe(audio: bytes, *, today: date, max_bytes: int) -> CaptureRead:
    """Read a spoken note. The transcript is the part the Butler answers from.

    A voice note is as often a question ("can I afford dinner?") as it is a
    transaction, so both are returned and the caller decides which to use.
    """
    _guard(audio, max_bytes)
    result = get_adapters().voice.transcribe(audio)
    category = infer(f"{result.transcript} {result.merchant}")
    return CaptureRead(
        kind=CAPTURE_VOICE,
        source=SOURCE_VOICE,
        merchant=result.merchant,
        amount_sen=result.amount.sen,
        occurred_on=today,
        category=category,
        confidence=result.confidence,
        note=result.note,
        transcript=result.transcript,
        fields=_fields(
            result.merchant, result.amount.sen, today, category, result.confidence
        ),
    )
