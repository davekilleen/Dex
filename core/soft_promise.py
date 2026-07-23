"""Shared deterministic detection for soft or implicit commitments."""

from __future__ import annotations

import re


SOFT_PROMISE_PATTERNS = [
    r"\bI(?:['’]ll| will)\s+(?:follow\s+up|get\s+back\s+to|send|circle\s+back|look\s+into|check(?:\s+\w+){0,5}\s+and\s+let\s+you\s+know|reach\s+out\s+to)\b",
    r"\blet\s+me\s+(?:get\s+back\s+to|look\s+into)\b",
    r"\bwe\s+should(?:\s+probably)?\s+(?:revisit|reconnect)\b",
    r"\bI\s+need\s+to\s+(?:follow\s+up\s+with|reach\s+out\s+to)\b",
    r"\bI\s+owe\b",
]

_CLAUSE_PATTERN = re.compile(r"[^.!?;\n]+[.!?]?", re.MULTILINE)
_NEGATIVE_GUARD = re.compile(r"\b(?:might|maybe|could|should\s+we)\b", re.IGNORECASE)
_DUE_PATTERN = re.compile(r"\bby\s+(.+)$", re.IGNORECASE)
_PERSON_AFTER_PREPOSITION = re.compile(
    r"\b(?:with|to)\s+(you|[A-Z][A-Za-z'-]*(?:\s+[A-Z][A-Za-z'-]*)*)\b"
)
_PERSON_AFTER_SEND = re.compile(
    r"\b(?i:send)\s+(you|[A-Z][A-Za-z'-]*(?:\s+[A-Z][A-Za-z'-]*)*)\b"
)
_PERSON_AFTER_OWE = re.compile(
    r"\bI\s+owe\s+(you|[A-Z][A-Za-z'-]*(?:\s+[A-Z][A-Za-z'-]*)*)\b"
)


def _clean_clause(clause: str) -> str:
    return clause.strip().rstrip(".!")


def _extract_person(commitment_tail: str, matched_phrase: str) -> str | None:
    for pattern in (_PERSON_AFTER_PREPOSITION, _PERSON_AFTER_SEND):
        match = pattern.search(commitment_tail)
        if match:
            return match.group(1)
    if matched_phrase.casefold().startswith("i owe"):
        match = _PERSON_AFTER_OWE.search(commitment_tail)
        if match:
            return match.group(1)
    return None


def _extract_due(commitment_tail: str) -> str | None:
    match = _DUE_PATTERN.search(commitment_tail)
    if not match:
        return None
    due = match.group(1).strip().rstrip(".!")
    return due or None


def detect_soft_promises(text: str) -> list[dict]:
    """Return unique soft-commitment candidates found in ``text``."""
    if not isinstance(text, str) or not text.strip():
        return []

    candidates: list[dict] = []
    seen: set[str] = set()
    for clause_match in _CLAUSE_PATTERN.finditer(text):
        raw_clause = clause_match.group(0).strip()
        if not raw_clause or raw_clause.endswith("?"):
            continue
        if _NEGATIVE_GUARD.search(raw_clause):
            continue

        pattern_match = None
        for pattern in SOFT_PROMISE_PATTERNS:
            pattern_match = re.search(pattern, raw_clause, re.IGNORECASE)
            if pattern_match:
                break
        if pattern_match is None:
            continue

        commitment = _clean_clause(raw_clause)
        dedup_key = " ".join(commitment.casefold().split())
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        matched_phrase = pattern_match.group(0)
        commitment_tail = commitment[pattern_match.start() :]
        candidates.append(
            {
                "commitment": commitment,
                "person": _extract_person(commitment_tail, matched_phrase),
                "due": _extract_due(commitment_tail),
                "matched_phrase": matched_phrase,
            }
        )

    return candidates
