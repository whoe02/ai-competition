"""Receipt and voice capture.

Both endpoints read and return; neither writes. What comes back is a proposal
with a confidence on every field, which the client either sends to the Butler
as an attachment or saves as a draft — and a draft is still not the ledger.

The providers are chosen in `kira.adapters.registry`. Today they are the
deterministic fakes; a real OCR or speech vendor drops in behind the same
protocol without touching this file.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from kira.api.deps import CurrentUser
from kira.api.schemas import CaptureAvailability, CaptureResponse
from kira.config import get_settings
from kira.services import capture
from kira.services.clock import today_for

router = APIRouter(prefix="/v1/capture", tags=["capture"])

logger = logging.getLogger(__name__)

DISABLED = HTTPException(
    status.HTTP_503_SERVICE_UNAVAILABLE, "That way of capturing is not switched on"
)


@router.get("", response_model=CaptureAvailability)
async def availability(user: CurrentUser) -> CaptureAvailability:
    """What the client may offer. A dead affordance is worse than none."""
    settings = get_settings()
    return CaptureAvailability(
        receipt=settings.capture_receipt_enabled,
        voice=settings.capture_voice_enabled,
        max_bytes=settings.capture_max_bytes,
    )


def _rejected(kind: str, exc: capture.CaptureRejected) -> HTTPException:
    """Say why, in the log as well as the body.

    The access log records the 422 and nothing else, so a rejection that the
    user saw as a sentence reads afterwards as an unexplained failure. The
    reason is about the upload, not its contents.
    """
    logger.info("capture %s rejected: %s", kind, exc)
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.post("/receipt", response_model=CaptureResponse)
async def read_receipt(
    user: CurrentUser, image: Annotated[UploadFile, File()]
) -> CaptureResponse:
    settings = get_settings()
    if not settings.capture_receipt_enabled:
        raise DISABLED
    try:
        read = capture.read_receipt(
            await image.read(), today=today_for(), max_bytes=settings.capture_max_bytes
        )
    except capture.CaptureRejected as exc:
        raise _rejected("receipt", exc) from exc
    return CaptureResponse.model_validate(read)


@router.post("/voice", response_model=CaptureResponse)
async def read_voice(
    user: CurrentUser, audio: Annotated[UploadFile, File()]
) -> CaptureResponse:
    settings = get_settings()
    if not settings.capture_voice_enabled:
        raise DISABLED
    try:
        read = capture.transcribe(
            await audio.read(), today=today_for(), max_bytes=settings.capture_max_bytes
        )
    except capture.CaptureRejected as exc:
        raise _rejected("voice", exc) from exc
    return CaptureResponse.model_validate(read)
