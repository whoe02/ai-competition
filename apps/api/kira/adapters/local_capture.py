"""Local OCR and speech adapters for finance capture."""

from __future__ import annotations

import json
import re
import tempfile
from datetime import date
from decimal import Decimal
from io import BytesIO

from kira.adapters.protocols import ReceiptRead, VoiceRead
from kira.money import Money

NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


class CaptureProviderError(RuntimeError):
    """Raised when a local capture provider cannot be used."""


def _money_from_text(text: str) -> Money:
    matches = re.findall(
        r"(?<!\d)((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?)(?!\d)", text
    )
    if not matches:
        words = [word for word in re.findall(r"[a-z]+", text.lower()) if word != "ringgit"]
        values = [NUMBER_WORDS[word] for word in words if word in NUMBER_WORDS]
        if values:
            return Money(sum(values) * 100)
        raise CaptureProviderError("the receipt did not contain a readable total")
    values = [value.replace(",", "") for value in matches]
    amount = max(values, key=Decimal)
    major, _, minor = amount.partition(".")
    return Money(int(major) * 100 + int((minor + "00")[:2]))


def _merchant_from_text(text: str) -> str:
    for line in (line.strip() for line in text.splitlines()):
        if line and not re.search(r"total|subtotal|tax|gst|sst|cash|change|\d{2,}", line, re.I):
            return line[:120]
    return "Unknown merchant"


def _merchant_from_voice(text: str) -> str:
    match = re.search(
        r"\b(?:at|from)\s+([A-Za-z0-9&'. -]+?)"
        r"(?=,|\s+(?:for|cost|was|is)\b|\s+\d|\s+ringgit\b|$)",
        text,
        re.I,
    )
    if match:
        return match.group(1).strip(" .,\")")[:120]
    return text.split()[0][:120] if text.split() else "Unknown merchant"


def _is_transaction_candidate(text: str, amount: Money | None) -> bool:
    """Keep a spoken question out of the transaction-confirmation flow.

    An amount on its own is not evidence of a purchase: ``Can I afford RM60
    dinner?`` contains one, but it belongs in the Butler's reasoning, not in
    the ledger.  A direct past-tense spend statement, or the compact
    ``Grab from A to B, fourteen ringgit`` form, is enough to offer a proposal.
    The user still has to explicitly save and confirm it.
    """
    if amount is None:
        return False
    normalised = text.strip().lower()
    if "?" in normalised or re.search(
        r"^(?:can|could|should|would|will|what|when|where|why|how|do|does|is|are)\b",
        normalised,
    ):
        return False
    if re.search(
        r"\b(?:spent|paid|bought|purchased|cost|costs|fare|topped up|"
        r"belanja|bayar|beli|harga|tambang)\b",
        normalised,
    ):
        return True
    return bool(re.search(r"\b(?:at|from)\s+.+\b(?:ringgit|rm)\b", normalised))


class PaddleOcrAdapter:
    """Read a receipt with PaddleOCR and extract a conservative proposal."""

    def __init__(self, language: str = "en") -> None:
        try:
            import numpy as np
            from paddleocr import PaddleOCR
            from PIL import Image
        except ImportError as exc:
            raise CaptureProviderError(
                "PaddleOCR capture requires the capture dependencies"
            ) from exc
        self._image = Image
        self._numpy = np
        self._ocr = PaddleOCR(
            lang=language,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    def read_receipt(self, image: bytes) -> ReceiptRead:
        try:
            source = self._image.open(BytesIO(image)).convert("RGB")
            result = self._ocr.predict(self._numpy.asarray(source))
            lines: list[str] = []
            for page in result:
                data = page.json if hasattr(page, "json") else page
                if callable(data):
                    data = data()
                if isinstance(data, str):
                    data = json.loads(data)
                texts = data.get("res", {}).get("rec_texts", [])
                lines.extend(str(text) for text in texts if str(text).strip())
            text = "\n".join(lines)
            return ReceiptRead(
                merchant=_merchant_from_text(text),
                amount=_money_from_text(text),
                occurred_on=date.today(),
                confidence=70,
                note="Read locally with PaddleOCR; verify the merchant, total, and date.",
            )
        except CaptureProviderError:
            raise
        except Exception as exc:
            raise CaptureProviderError("PaddleOCR could not read this receipt") from exc


class WhisperVoiceAdapter:
    """Transcribe a voice note locally with faster-whisper."""

    def __init__(self, model: str = "small", language: str = "en") -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise CaptureProviderError(
                "Whisper capture requires the capture dependencies"
            ) from exc
        self._language = language
        self._model = WhisperModel(model, device="cpu", compute_type="int8")

    def transcribe(self, audio: bytes) -> VoiceRead:
        try:
            with tempfile.NamedTemporaryFile(suffix=".audio") as source:
                source.write(audio)
                source.flush()
                segments, info = self._model.transcribe(
                    source.name, language=self._language
                )
                # faster-whisper yields segments lazily. Consume them before the
                # temporary source file is closed underneath the decoder.
                transcript = " ".join(segment.text.strip() for segment in segments).strip()
            if not transcript:
                raise CaptureProviderError("the recording did not contain speech")
            try:
                amount = _money_from_text(transcript)
            except CaptureProviderError:
                amount = None
            is_transaction = _is_transaction_candidate(transcript, amount)
            return VoiceRead(
                transcript=transcript,
                merchant=_merchant_from_voice(transcript) if is_transaction else None,
                amount=amount if is_transaction else None,
                confidence=round(float(info.language_probability) * 100),
                note=(
                    "Transcribed locally with Whisper; verify the merchant and amount."
                    if is_transaction
                    else "Transcribed locally with Whisper; no transaction was inferred."
                ),
                is_transaction=is_transaction,
            )
        except CaptureProviderError:
            raise
        except Exception as exc:
            raise CaptureProviderError("Whisper could not transcribe this recording") from exc
