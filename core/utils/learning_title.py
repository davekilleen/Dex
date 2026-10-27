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
KNOWN_KINDS = frozenset({"correction", "preference"})

MAX_TITLE_CHARS = 72
MIN_TITLE_CHARS = 8
IDEA_TITLE_CHARS = 80
CONTENT_MATCH_THRESHOLD = 0.75
# Generic fallback titles are not a match signal. Body must be closer.
GENERIC_FALLBACK_THRESHOLD = 0.88
# Short notes only group when the wording is the same. Fuzzy matching on
# "stop that" vs "stop doing that" is how unrelated corrections got one idea.
MIN_FUZZY_CHARS = 24

_GENERIC_TEMPLATE = re.compile(
    r"(?i)(classify during /daily-review|confirm during /daily-review"
    r"|a correction is the highest-value signal"
    r"|a stated preference should survive the session)"
)
_SOFT_FILLER = re.compile(
    r"^(?:wait|um+|uh+|hey|look|okay|ok|please)[,.\s:-]+",
    re.IGNORECASE,
)
_NO_STOP_LEAD = re.compile(
    r"^(?P<lead>(?:no(?:\s+no)*)|stop)(?P<sep>[,.:-]+\s*|\s+[-–—]\s+)(?P<rest>.+)",
    re.IGNORECASE,
)
_VERBISH = re.compile(
    r"(?i)^(?:stop|don'?t|do\s+not|always|never|prefer|use|write|ask|check|"
    r"confirm|keep|leave|skip|run|treat|name|group|split|remember|that'?s)"
)
_SESSION_PREFIX = re.compile(
    r"(?i)^(?:from\s+)?session learning\s*\(\d{4}-\d{2}-\d{2}\):\s*"
    r"(?:correction|preference)?[.]*\s*"
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_MARKUP = re.compile(r"[*_`>#]+")
_WHITESPACE = re.compile(r"\s+")
_FIELD_PREFIX = re.compile(
    r"(?i)^(?:\*\*)?(?:what was said|what happened|why it matters|"
    r"suggested fix|kind)(?:\*\*)?:?\s*"
)
_HEADING_LINE = re.compile(
    r"^(?P<prefix>##\s+)(?P<open>\[)?(?P<time>\d{1,2}:\d{2})(?P<close>\])?"
    r"\s*[-–]\s*(?P<title>.+?)\s*$",
    re.MULTILINE,
)
_KIND_LINE = re.compile(r"^\*\*Kind:\*\*\s*(?P<kind>.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_STATUS_LINE = re.compile(r"\*\*Status:\*\*\s*(?P<status>\w+)", re.IGNORECASE)
_WHAT_SAID = re.compile(
    r"\*\*What was said:\*\*\s*(?P<body>.+?)(?:\n\*\*|\n---|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_WHAT_HAPPENED = re.compile(
    r"\*\*What happened:\*\*\s*(?P<body>.+?)(?:\n\*\*|\n---|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_PREFERENCE_HINT = re.compile(
    r"(?i)\bi prefer\b|\bi['’]d rather\b|\bfrom now on\b|\bgoing forward\b"
    r"|\bi want (?:you|dex) to\b"
)
_CORRECTION_HINT = re.compile(
    r"(?i)\bstop \b|\bdon'?t\b|\bdo not\b|\bthat'?s not\b|\bno,"
)
_FIX_LANGUAGE = re.compile(
    r"(?i)^(?:fix\b|write a (?:rule|check|test)|add (?:a )?(?:rule|check|guard))"
)
_FINISHED = frozenset({"implemented", "dropped"})


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
    cleaned = cleaned.rstrip(".")
    return cleaned in REWRITABLE_GENERIC_TITLES


def is_generic_template(text: str) -> bool:
    """True for the stock why/fix boilerplate auto-capture writes."""
    return bool(text and _GENERIC_TEMPLATE.search(text))


def infer_kind(title: str = "", body: str = "", explicit: str = "") -> str:
    """Correction or Preference from the Kind line, an old heading, or the body."""
    labeled = _canonical_kind(explicit)
    if labeled:
        return labeled
    labeled = _canonical_kind(title)
    if labeled:
        return labeled
    text = f"{title}\n{body}"
    if _PREFERENCE_HINT.search(text):
        return "Preference"
    if _CORRECTION_HINT.search(text):
        return "Correction"
    return ""


def content_fingerprint(text: str) -> str:
    """Stable wording key: markup, quotes, templates, and case do not count."""
    usable = _usable_text(text)
    if not usable:
        return ""
    collapsed = usable.casefold()
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
    if min(len(first), len(second)) < MIN_FUZZY_CHARS:
        return False
    return SequenceMatcher(None, first, second).ratio() >= threshold


def body_match_threshold(*titles: str) -> float:
    """Raise the merge bar when a heading is still a generic fallback."""
    if any(is_generic_title(title) for title in titles):
        return GENERIC_FALLBACK_THRESHOLD
    return CONTENT_MATCH_THRESHOLD


def learning_title_from_text(text: str, kind: str = "") -> str:
    """Build a short heading from the user's words.

    First sentence, or the first 60–72 characters. Leading ``no,`` / ``stop``
    filler is dropped only when a clearer verb phrase follows. Falls back to
    ``kind`` when nothing usable remains or the result is under eight characters.
    """
    sentence = _first_sentence(_usable_text(text))
    if not sentence or len(sentence) < MIN_TITLE_CHARS:
        return _plain(kind)
    titled = sentence[0].upper() + sentence[1:] if sentence[0].islower() else sentence
    titled = titled.replace("\n", " ").replace("#", "").strip()
    titled = _WHITESPACE.sub(" ", titled)
    if len(titled) > MAX_TITLE_CHARS:
        titled = _clip(titled, MAX_TITLE_CHARS)
    if is_generic_title(titled) or len(titled) < MIN_TITLE_CHARS:
        return _plain(kind) or titled
    return titled


def title_from_content(text: str, *, fallback: str = "") -> str:
    """Compatibility wrapper around :func:`learning_title_from_text`."""
    return learning_title_from_text(text, fallback)


def idea_title_from_learning(title: str, suggested_fix: str = "", kind: str = "") -> str:
    """Name a backlog idea from the content title.

    An action prefix is added only when the suggested fix clearly starts with
    fix language. Mass ``Fix: Correction`` never comes out of this path.
    """
    derived = learning_title_from_text(title, kind)
    if not derived or is_generic_title(derived):
        derived = _plain(kind) or "Learning"
    if derived.lower().startswith("fix:"):
        return derived[:IDEA_TITLE_CHARS]
    fix = (suggested_fix or "").strip()
    if fix and not is_generic_template(fix) and _FIX_LANGUAGE.match(fix):
        derived = f"Fix: {derived}"
    return derived[:IDEA_TITLE_CHARS]


def retitle_learning_entry(block: str) -> str:
    """Rewrite one pending generic-titled entry from ``What was said``.

    Pure and idempotent. Implemented or dropped entries are left alone.
    """
    if not block:
        return block
    heading = _HEADING_LINE.search(block)
    if not heading:
        return block
    status_match = _STATUS_LINE.search(block)
    status = (status_match.group("status") if status_match else "pending").lower()
    if status in _FINISHED:
        return block
    title = heading.group("title")
    if not is_rewritable_generic_title(title):
        return block
    said = _said_from_block(block)
    kind = infer_kind(title=title, body=block)
    new_title = learning_title_from_text(said, kind)
    if not new_title or new_title == title or is_generic_title(new_title):
        return block
    open_br = heading.group("open") or ""
    close_br = heading.group("close") or ""
    new_heading = f"{heading.group('prefix')}{open_br}{heading.group('time')}{close_br} - {new_title}"
    updated = block[: heading.start()] + new_heading + block[heading.end() :]
    if kind and not _KIND_LINE.search(updated):
        updated = _insert_kind(updated, kind)
    return updated


def _said_from_block(block: str) -> str:
    said = _WHAT_SAID.search(block)
    if said:
        return said.group("body")
    happened = _WHAT_HAPPENED.search(block)
    if happened:
        return happened.group("body")
    return block


def _insert_kind(block: str, kind: str) -> str:
    heading = _HEADING_LINE.search(block)
    if not heading:
        return block
    insert_at = heading.end()
    rest = block[insert_at:]
    lead = "\r\n" if rest.startswith("\r\n") else "\n" if rest.startswith("\n") else "\n"
    extra = "\r\n" if lead == "\r\n" else "\n"
    return f"{block[:insert_at]}{lead}{extra}**Kind:** {kind}{rest}"


def _canonical_kind(value: str) -> str:
    cleaned = _WHITESPACE.sub(" ", (value or "").strip()).casefold().rstrip(".")
    if cleaned in KNOWN_KINDS:
        return cleaned[:1].upper() + cleaned[1:]
    return ""


def _usable_text(text: str) -> str:
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    kept: list[str] = []
    for raw in cleaned.split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        folded = line.casefold()
        if folded.startswith("**status:**") or folded.startswith("**kind:**"):
            continue
        if is_generic_template(line):
            continue
        if line.startswith("> "):
            line = line[2:]
        elif line == ">":
            continue
        line = _FIELD_PREFIX.sub("", line).strip()
        line = _MARKUP.sub("", line).strip()
        line = _FIELD_PREFIX.sub("", line).strip()
        if not line or line.casefold() in {
            "what was said",
            "what happened",
            "why it matters",
            "suggested fix",
            "status",
            "kind",
            "correction",
            "preference",
        }:
            continue
        kept.append(line)
    return " ".join(kept)


def _first_sentence(text: str) -> str:
    collapsed = _WHITESPACE.sub(" ", (text or "").strip())
    if not collapsed:
        return ""
    collapsed = _SESSION_PREFIX.sub("", collapsed)
    collapsed = _SOFT_FILLER.sub("", collapsed).strip(" -:")
    lead = _NO_STOP_LEAD.match(collapsed)
    if lead:
        rest = lead.group("rest").strip(" -:")
        if rest and (len(rest) >= MIN_TITLE_CHARS or _VERBISH.match(rest)):
            collapsed = rest
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
