"""The one place the system reads a calendar."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from kira.config import get_settings


def today_for() -> date:
    """Return today's Kuala Lumpur date, or the pinned demo date when configured."""
    settings = get_settings()
    if settings.demo_today is not None:
        return settings.demo_today
    return datetime.now(ZoneInfo(settings.worker_timezone)).date()
