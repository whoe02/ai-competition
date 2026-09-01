"""Ninety days of textured spending, so the forecast has a rhythm to learn.

Deterministic: the same dates always produce the same history, so a golden
expectation moves only when this file does.
"""

from __future__ import annotations

from datetime import date, timedelta

from kira.db.models import SOURCE_MANUAL, SOURCE_RECEIPT, SOURCE_VOICE

# (merchant, sen, category, source), drawn by weekday. Sunday is the grocery
# run; Friday is the expensive day; the weekdays are commute and lunch.
WEEKDAY_PATTERN: dict[int, tuple[tuple[str, int, str, str], ...]] = {
    0: (
        ("Grab — home to office", 1380, "transport", SOURCE_MANUAL),
        ("Economy rice — Jalan Ampang", 1150, "food", SOURCE_RECEIPT),
    ),
    1: (
        ("Touch 'n Go reload", 3000, "transport", SOURCE_MANUAL),
        ("Zus Coffee", 1090, "food", SOURCE_RECEIPT),
    ),
    2: (
        ("Nasi Kandar Pelita", 1690, "food", SOURCE_RECEIPT),
        ("Grab — office to home", 1420, "transport", SOURCE_VOICE),
    ),
    3: (
        ("Family Mart", 1250, "groceries", SOURCE_RECEIPT),
        ("Mixue", 890, "food", SOURCE_VOICE),
    ),
    4: (
        ("Village Park Restoran", 2350, "food", SOURCE_RECEIPT),
        ("GSC Mid Valley", 4200, "fun", SOURCE_MANUAL),
        ("Grab — Bangsar", 1980, "transport", SOURCE_MANUAL),
    ),
    5: (
        ("Petronas Setapak", 9000, "transport", SOURCE_RECEIPT),
        ("Watsons", 3560, "health", SOURCE_MANUAL),
    ),
    6: (("Jaya Grocer", 18040, "groceries", SOURCE_RECEIPT),),
}

# Deliberate overspend days, by offset from the start. Without them the track
# record has nothing to say, and a forecast band has nothing to widen around.
SPIKES: tuple[tuple[int, str, int, str, str], ...] = (
    (12, "Uniqlo Mid Valley", 21900, "shopping", SOURCE_RECEIPT),
    (33, "Apple Store — charger and case", 38900, "shopping", SOURCE_RECEIPT),
    (47, "Aida's birthday dinner", 32600, "food", SOURCE_MANUAL),
    (61, "Klinik Mediviron", 18500, "health", SOURCE_RECEIPT),
    (74, "Duit raya — family", 40000, "family", SOURCE_MANUAL),
)


def history_entries(start: date, end: date) -> tuple[tuple[str, int, str, str, date], ...]:
    """Every confirmed transaction from ``start`` up to but excluding ``end``."""
    entries: list[tuple[str, int, str, str, date]] = []

    day = start
    while day < end:
        for merchant, sen, category, source in WEEKDAY_PATTERN[day.weekday()]:
            entries.append((merchant, sen, category, source, day))
        day += timedelta(days=1)

    for offset, merchant, sen, category, source in SPIKES:
        spike_day = start + timedelta(days=offset)
        if start <= spike_day < end:
            entries.append((merchant, sen, category, source, spike_day))

    return tuple(entries)
