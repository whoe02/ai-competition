"""Distilling durable facts from a sentence the user just wrote.

Rule-based first, because a fact Kira keeps has to be one the user would
recognise as theirs. When a real model is available the graph asks it too and
merges what it finds; offline, these patterns alone carry the demo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_FACT = 240


@dataclass(frozen=True, slots=True)
class Candidate:
    kind: str
    subject: str
    fact: str
    confidence: int


@dataclass(frozen=True, slots=True)
class Rule:
    kind: str
    subject: str
    pattern: re.Pattern[str]
    confidence: int = 80
    # Keep the sentence rather than the matched clause, where the clause alone
    # would read as a fragment.
    whole_sentence: bool = False


RULES: tuple[Rule, ...] = (
    Rule(
        "constraint",
        "standing rule",
        re.compile(r"\b(?:never|don'?t ever|do not ever)\s+(?P<body>[^.!?]{4,200})", re.I),
        90,
    ),
    Rule(
        "preference",
        "how to answer",
        re.compile(r"\bi (?:prefer|like|want|hate|don'?t like)\s+(?P<body>[^.!?]{3,200})", re.I),
        85,
    ),
    Rule(
        "preference",
        "how to answer",
        re.compile(r"\b(?:from now on|in future|always)\s+(?P<body>[^.!?]{4,200})", re.I),
        85,
    ),
    Rule(
        "pattern",
        "spending habit",
        re.compile(
            r"\bi (?:usually|normally|tend to|always end up)\s+(?P<body>[^.!?]{4,200})", re.I
        ),
        70,
    ),
    Rule(
        "person",
        "someone in their money",
        re.compile(
            r"\bmy (?P<who>housemate|partner|wife|husband|mother|father|mum|dad|brother|sister|"
            r"fianc[ée]e?|flatmate|roommate)\b(?P<body>[^.!?]{0,200})",
            re.I,
        ),
        75,
        whole_sentence=True,
    ),
    Rule(
        "context",
        "life fact",
        re.compile(r"\bi (?:work|live|study|commute)\s+(?P<body>[^.!?]{3,200})", re.I),
        75,
    ),
)


def _tidy(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" ,;:").strip()


def _sentence(text: str, at: int) -> str:
    start = max(text.rfind(mark, 0, at) for mark in (".", "!", "?", "\n")) + 1
    ends = [end for end in (text.find(mark, at) for mark in (".", "!", "?", "\n")) if end != -1]
    return text[start : min(ends) if ends else len(text)]


def candidates(text: str) -> tuple[Candidate, ...]:
    """Facts worth keeping from one message. Empty is the common, correct answer."""
    found: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    for rule in RULES:
        match = rule.pattern.search(text or "")
        if match is None:
            continue
        raw = _sentence(text, match.start()) if rule.whole_sentence else match.group(0)
        fact = _tidy(raw)[:MAX_FACT]
        if len(fact) < 8:
            continue
        subject = rule.subject
        if "who" in (match.groupdict() or {}) and match.group("who"):
            subject = match.group("who").lower()
        key = (rule.kind, subject)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            Candidate(kind=rule.kind, subject=subject, fact=fact, confidence=rule.confidence)
        )
    return tuple(found)
