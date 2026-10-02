"""Shared deterministic detection for soft or implicit commitments."""

from __future__ import annotations

import re

SUPPORTED_LOCALES = ("en", "fr")
UNSUPPORTED_LOCALE_NOTE = (
    "Soft-commitment detection only matches English and French phrasing."
)

SOFT_PROMISE_PATTERNS = [
    r"\bI(?:['’]ll| will)\s+(?:follow\s+up|get\s+back\s+to|send|circle\s+back|look\s+into|check(?:\s+\w+){0,5}\s+and\s+let\s+you\s+know|reach\s+out\s+to)\b",
    r"\blet\s+me\s+(?:get\s+back\s+to|look\s+into)\b",
    r"\bwe\s+should(?:\s+probably)?\s+(?:revisit|reconnect)\b",
    r"\bI\s+need\s+to\s+(?:follow\s+up\s+with|reach\s+out\s+to)\b",
    r"\bI\s+owe\b",
    r"\bje\s+vais(?:\s+(?:te|t['’]|vous))?\s*(?:revenir|recontacter|relancer|envoyer|faire\s+(?:un\s+)?suivi)\b",
    r"\bje\s+reviens\s+vers\s+(?:toi|vous)\b",
    r"\bje\s+(?:te|t['’]|vous)\s*(?:envoie|recontacte|fais\s+(?:un\s+)?(?:suivi|retour))\b",
    r"\blaisse(?:z|-moi|\s+moi)\s+(?:te\s+|vous\s+)?revenir\b",
    r"\bon\s+devrait(?:\s+peut-être)?\s+(?:revenir\s+sur|revoir)\b",
    r"\bje\s+dois\s+(?:relancer|recontacter|faire\s+(?:un\s+)?suivi)\b",
    r"\bje\s+(?:te|vous)\s+dois\b",
]

_CLAUSE_PATTERN = re.compile(r"[^.!?;\n]+[.!?]?", re.MULTILINE)
_NEGATIVE_GUARD = re.compile(
    r"\b(?:might|maybe|could|should\s+we|peut-être)\b",
    re.IGNORECASE,
)
_DUE_PATTERN = re.compile(
    r"\b(?:by|d['’]ici|avant|pour)\s+(.+)$",
    re.IGNORECASE,
)
_PERSON_AFTER_PREPOSITION = re.compile(
    r"\b(?:with|to|avec|vers|relancer|recontacter)\s+"
    r"(you|toi|vous|[A-Z][A-Za-zÀ-ÿ'-]*(?:\s+[A-Z][A-Za-zÀ-ÿ'-]*)*)\b"
)
_PERSON_AFTER_SEND = re.compile(
    r"\b(?i:send|envoie)\s+(you|toi|vous|[A-Z][A-Za-zÀ-ÿ'-]*(?:\s+[A-Z][A-Za-zÀ-ÿ'-]*)*)\b"
)
_PERSON_AFTER_OWE = re.compile(
    r"\bI\s+owe\s+(you|[A-Z][A-Za-z'-]*(?:\s+[A-Z][A-Za-z'-]*)*)\b"
)
_PERSON_AFTER_OWE_FR = re.compile(
    r"\bje\s+(?:te|vous)\s+dois\b",
    re.IGNORECASE,
)
_UNSUPPORTED_LOCALE_HINTS = (
    re.compile(r"\b(?:voy a|te voy a|deberíamos|déjame)\b", re.IGNORECASE),
    re.compile(r"\b(?:ich werde|ich muss|lass mich)\b", re.IGNORECASE),
    re.compile(r"\b(?:devo|ci dovremmo|fammi)\b", re.IGNORECASE),
)


def _clean_clause(clause: str) -> str:
    return clause.strip().rstrip(".!")


def _extract_person(commitment_tail: str, matched_phrase: str) -> str | None:
    for pattern in (_PERSON_AFTER_PREPOSITION, _PERSON_AFTER_SEND):
        match = pattern.search(commitment_tail)
        if match:
            return match.group(1)
    folded = matched_phrase.casefold()
    if folded.startswith("i owe"):
        match = _PERSON_AFTER_OWE.search(commitment_tail)
        if match:
            return match.group(1)
    if _PERSON_AFTER_OWE_FR.search(matched_phrase):
        return "toi" if "te" in folded else "vous"
    if "t'" in folded or "t’" in folded:
        return "toi"
    return None


def _extract_due(commitment_tail: str) -> str | None:
    match = _DUE_PATTERN.search(commitment_tail)
    if not match:
        return None
    due = match.group(1).strip().rstrip(".!")
    return due or None


def looks_like_unsupported_locale(text: str) -> bool:
    """True when the text looks like a soft promise in an unsupported language."""
    if not isinstance(text, str) or not text.strip():
        return False
    return any(pattern.search(text) for pattern in _UNSUPPORTED_LOCALE_HINTS)


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


def detect_soft_promises_report(text: str) -> dict:
    """Return candidates plus honest locale-support metadata."""
    candidates = detect_soft_promises(text)
    unsupported = not candidates and looks_like_unsupported_locale(text)
    report = {
        "candidates": candidates,
        "count": len(candidates),
        "locale_support": list(SUPPORTED_LOCALES),
    }
    if unsupported:
        report["unsupported_locale"] = True
        report["note"] = UNSUPPORTED_LOCALE_NOTE
    else:
        report["unsupported_locale"] = False
    return report
