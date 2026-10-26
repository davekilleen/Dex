"""Single check for whether a message is a correction from the user.

The live prompt hook and the session-end extractor used to each carry their
own copy of the wording, and the cheap bash gate had a third. Those copies
drifted. This module is the check: it reads only the user's own words, then
decides. The bash gate may still over-match so Python starts; it is not the
decision.

A correction is the user telling Dex it got something wrong. Ordinary
negatives ("I don't have that", "no rush"), a paste, a quote, and a plain
question ("Is that not what we discussed?") are not.
"""
from __future__ import annotations

import re

# Harness blocks are lowercase tags with at least one hyphen
# (<system-reminder>, <task-notification>, ...). An unclosed one runs to
# the end of the text. These are never the user's words.
_MACHINE_BLOCK = re.compile(
    r"<([a-z]+(?:-[a-z]+)+)\b[^>]*>.*?(?:</\1>|\Z)",
    re.DOTALL,
)

# User-pasted or quoted wrappers. Claude uses <pasted_content> (underscore);
# a hyphenated alias is included so a future wrapper does not re-open this.
_PASTE_OR_QUOTE_TAG = re.compile(
    r"<(pasted[_-]content|quoted[_-](?:text|content)|quote)\b[^>]*>"
    r".*?(?:</\1>|\Z)",
    re.DOTALL | re.IGNORECASE,
)

_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_BLOCKQUOTE_LINE = re.compile(r"^\s*>")
_PLAIN_QUESTION = re.compile(
    r"(?ix)^\s*"
    r"(?:(?:so|and|but|well|hey|ok|okay)[,.]?\s+)*"
    r"(?:is|isn'?t|are|aren'?t|was|were|do|does|did|can|could|would|should|"
    r"will|have|has|had|am|don'?t|doesn'?t|didn'?t)\b"
)
_ORDINARY_NO = re.compile(
    r"(?i)\b(?:have no|has no|with no|there(?:'s| is) no|"
    r"no,?\s*(?:thanks|thank you)|"
    r"no (?:problem|worries|rush|need|meetings?|idea|clue))\b"
)

# Bare conversational words ("no", "stop", "actually,") are not a correction
# on their own. "no" only counts with a comma, an ellipsis, or a repeat.
# "stop" only counts with a following verb. "don't" only counts when it is
# aimed at Dex ("don't do that", "you don't"), not when it appears anywhere.
# "not what" only counts as "not what I".
_CORRECTION = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9])(?:nope|wrong|incorrect)(?:[^A-Za-z0-9]|$)"
    r"|(?:^|[^A-Za-z0-9])no(?:\s*,|\s*\.\.\.|\s+no\b)"
    r"|(?:^|[^A-Za-z0-9])stop\s+(?:doing|making|writing|over|inferr|that|this)\b"
    r"|don'?t\s+(?:do|write|infer|assume|make|use|say|create|skip|tell|put|add|change|over)\b"
    r"|(?:^|[^A-Za-z0-9])you\s+don'?t\b"
    r"|you did ?n'?t|you'?re not|that'?s not|thats not|not what I\b"
    r"|why (?:did|are|didn'?t) you|again[,.]|i (?:told|said) you"
    r"|keep (?:doing|writing|failing)|stupid|come on",
)

# Machine prose that arrives without a tag. Checked on what is LEFT after
# stripping, so a real correction sent alongside a reminder still counts.
_MACHINE_PHRASES = (
    "[SYSTEM NOTIFICATION - NOT USER INPUT]",
    "automated run of a scheduled task",
    "This is an automated background-task event",
)

_QUOTE_TRANSLATE = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u00b4": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201f": '"',
    }
)


def _strip_blockquotes(text: str) -> str:
    lines = [line for line in text.splitlines() if not _BLOCKQUOTE_LINE.match(line)]
    return "\n".join(lines)


def user_words(text: str) -> str:
    """Return only the user's own typed words, or '' if none remain.

    Harness blocks, pasted wrappers, fenced code, and quoted lines are
    removed first. Leftover machine preambles make the whole text empty so
    they cannot be filed as a correction.
    """
    if not text:
        return ""
    remainder = text.translate(_QUOTE_TRANSLATE)
    remainder = _MACHINE_BLOCK.sub("", remainder)
    remainder = _PASTE_OR_QUOTE_TAG.sub("", remainder)
    remainder = _FENCED_CODE.sub("", remainder)
    remainder = _strip_blockquotes(remainder).strip()
    if any(phrase in remainder for phrase in _MACHINE_PHRASES):
        return ""
    return remainder


def _is_plain_question(text: str) -> bool:
    stripped = text.strip()
    if not stripped.endswith("?"):
        return False
    return bool(_PLAIN_QUESTION.match(stripped))


def _drop_plain_questions(text: str) -> str:
    chunks = re.split(r"(?<=[?])\s+", text.strip())
    kept = [chunk for chunk in chunks if chunk and not _is_plain_question(chunk)]
    return " ".join(kept).strip()


def is_correction(text: str) -> bool:
    """True when the user's own words are telling Dex it got something wrong."""
    words = _drop_plain_questions(user_words(text))
    if not words:
        return False
    remainder = _ORDINARY_NO.sub(" ", words)
    return bool(_CORRECTION.search(remainder))
