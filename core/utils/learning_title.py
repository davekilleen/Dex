"""Name a learning from what was said, not from a generic kind label.

Auto-capture used to store every correction under the heading ``Correction``.
Synthesis then built one backlog idea titled ``Fix: Correction`` and piled
unrelated notes onto it. Titles here are rule-based: first useful sentence of
the content, cleaned and shortened. Nothing is sent to a model.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

GENERIC_TITLES = frozenset(
    {
        "correction",
        "preference",
        "fix: correction",
        "fix: preference",
        "session completed",
    }
)

# Headings the backfill may rewrite. Session markers stay as they are.
REWRITABLE_GENERIC_TITLES = frozenset({"correction", "preference"})

MAX_TITLE_CHARS = 72
CONTENT_MATCH_THRESHOLD = 0.65

_GENERIC_TEMPLATE = re.compile(
    r"(?i)(classify during /daily-review|confirm during /daily-review"
    r"|a correction is the highest-value signal"
    r"|a stated preference should survive the session)"
)
_LEAD_FLUFF = re.compile(
    r"^(?:(?:no(?:\s+no)*)|wait|um+|uh+|hey|look|okay|ok|please)[,.\s:-]+",
    re.IGNORECASE,
)
_SESSION_PREFIX = re.compile(
    r"(?i)^(?:from\s+)?session learning\s*\(\d{4}-\d{2}-\d{2}\):\s*"
    r"(?:correction|preference)?[.]*\s*"
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_MARKUP = re.compile(r"[*_`>#]+")
_WHITESPACE = re.compile(r"\s+")


def is_generic_title(title: str) -> bool:
    """True when the heading is a kind label, not a description of the note."""
    cleaned = _WHITESPACE.sub(" ", (title or "").strip()).casefold()
    cleaned = cleaned.rstrip(".")
    if cleaned in GENERIC_TITLES:
        return True
    if cleaned.startswith("fix: ") and cleaned[5:].strip() in GENERIC_TITLES:
        return True
    return False


def is_rewritable_generic_title(title: str) -> bool:
    """True for headings the backfill is allowed to replace from content."""
    cleaned = _WHITESPACE.sub(" ", (title or "").strip()).casefold()
    return cleaned in REWRITABLE_GENERIC_TITLES


def is_generic_template(text: str) -> bool:
    """True for the stock why/fix boilerplate auto-capture writes."""
    return bool(text and _GENERIC_TEMPLATE.search(text))


def content_fingerprint(text: str) -> str:
    """Stable wording key: markup, quotes, and case do not count."""
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for line in cleaned.split("\n"):
        stripped = line.strip()
        if stripped.startswith("> "):
            stripped = stripped[2:]
        elif stripped == ">":
            stripped = ""
        stripped = _MARKUP.sub("", stripped).strip()
        if stripped and not stripped.casefold().startswith("**status:**"):
            lines.append(stripped)
    collapsed = _WHITESPACE.sub(" ", " ".join(lines)).casefold()
    collapsed = _SESSION_PREFIX.sub("", collapsed)
    return " ".join(collapsed.split())


def contents_match(left: str, right: str, *, threshold: float = CONTENT_MATCH_THRESHOLD) -> bool:
    """True when two notes are about the same thing, ignoring their titles."""
    first = content_fingerprint(left)
    second = content_fingerprint(right)
    if not first or not second:
        return False
    if is_generic_title(first) or is_generic_title(second):
        return False
    if first == second:
        return True
    return SequenceMatcher(None, first, second).ratio() >= threshold


def title_from_content(text: str, *, fallback: str = "") -> str:
    """Build a short heading from the note's own words.

    Prefers the first real sentence after dropping leading interjections
    (``no,``, ``wait,``). Falls back to ``fallback`` only when nothing usable
    remains — and never returns another generic kind label if real words exist.
    """
    sentence = _first_sentence(_usable_text(text))
    if not sentence:
        return _plain(fallback)
    titled = sentence[0].upper() + sentence[1:] if sentence[0].islower() else sentence
    if len(titled) > MAX_TITLE_CHARS:
        titled = _clip(titled, MAX_TITLE_CHARS)
    if is_generic_title(titled):
        return _plain(fallback) or titled
    return titled


def _usable_text(text: str) -> str:
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    kept: list[str] = []
    for raw in cleaned.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("**") and line.endswith("**") and line.count("**") == 2:
            # Skip bare field labels such as **What was said:**
            label = line.strip("*").rstrip(":").strip()
            if label.casefold() in {
                "what was said",
                "what happened",
                "why it matters",
                "suggested fix",
                "status",
            }:
                continue
        if line.casefold().startswith("**status:**"):
            continue
        if is_generic_template(line):
            continue
        if line.startswith("> "):
            line = line[2:]
        elif line == ">":
            continue
        line = _MARKUP.sub("", line).strip()
        if line:
            kept.append(line)
    return " ".join(kept)


def _first_sentence(text: str) -> str:
    collapsed = _WHITESPACE.sub(" ", (text or "").strip())
    if not collapsed:
        return ""
    collapsed = _SESSION_PREFIX.sub("", collapsed)
    collapsed = _LEAD_FLUFF.sub("", collapsed).strip(" -:")
    if not collapsed:
        return ""
    parts = _SENTENCE_END.split(collapsed, maxsplit=1)
    sentence = parts[0].strip()
    return sentence.rstrip(".")


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    clipped = text[: limit + 1]
    cut = clipped.rfind(" ")
    if cut < limit // 2:
        cut = limit
    return clipped[:cut].rstrip(" ,;:-") + "…"


def _plain(value: str) -> str:
    return _WHITESPACE.sub(" ", (value or "").strip())
