#!/usr/bin/env python3
"""Append a user correction to today's session-learning file, verbatim.

Reached only when the bash gate has already decided a prompt looks like a
correction, so this pays no cost on an ordinary turn.

Design notes worth keeping:

- **The user's words are stored, not a paraphrase.** An assistant that
  misunderstood a correction will summarise it wrongly, and the summary is what
  would survive. Verbatim text is the only version that stays true regardless
  of whether the correction landed.
- **Status is `pending`**, matching the format CLAUDE.md already specifies, so
  the existing routing step in /daily-review consumes these without change.
- **Long prompts are truncated**, because a correction embedded in a wall of
  pasted context is still a correction and the file should stay readable.
- **Nothing is classified here.** Deciding whether a correction is behavioural,
  a skill defect or a one-off is judgement, and it belongs in the review step
  that has the context to do it.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

MAX_CHARS = 600
HEADING = "## {time} - Correction from the user"


def _vault_root() -> Path:
    import os

    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def _prompt(payload: dict) -> str:
    for key in ("prompt", "user_prompt", "message", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


# Text the harness writes into a submitted prompt is not the user's words. The
# bash gate greps the raw payload, so a long enough machine block trips an
# inclusive correction pattern on its own prose: CI events, task notifications
# and the slide viewer's live state have all been filed as "corrections" this
# way. Naming the offending markers one at a time never kept up, so match the
# CLASS: every harness block is a lowercase tag with at least one hyphen, and
# an unclosed one runs to the end of the text. User-pasted text arrives as
# <pasted_content> (underscore) and is deliberately NOT matched, because a
# pasted correction can be the user's own words.
#
# Stripping here rather than excluding in the gate keeps a REAL correction that
# arrives with a reminder appended: what survives the strip is what is tested
# and recorded. Keep in step with core/utils/session_lesson_extract.py.
MACHINE_BLOCK = re.compile(
    r"<([a-z]+(?:-[a-z]+)+)\b[^>]*>"
    r".*?(?:</\1>|\Z)",
    re.DOTALL,
)


def _strip_machine_blocks(text: str) -> str:
    return MACHINE_BLOCK.sub("", text).strip()


# The same wording the bash gate greps for, applied AFTER machine text is gone.
# The gate reads the raw payload, so a notification that happens to say "wrong"
# or "don't" gets a prompt this far; re-testing here is what stops the user's
# unrelated words ("run the daily plan") being recorded as a correction.
# Keep in step with the grep pattern in correction-capture.sh and
# core/utils/session_lesson_extract.py.
#
# Bare conversational words ("no", "stop", "actually,") are not a correction
# on their own. "no" only counts with a comma, an ellipsis, or a repeat
# ("no, that's not", "no... I meant", "no no no"). "stop" only counts with
# a following verb. "actually," is a discourse marker and is not matched.
CORRECTION = re.compile(
    r"(^|[^0-9A-Za-z])(nope|wrong|incorrect)([^0-9A-Za-z]|$)"
    r"|(^|[^0-9A-Za-z])no(\s*,|\s*\.\.\.|\s+no\b)"
    r"|(^|[^0-9A-Za-z])stop\s+(doing|making|writing|over|inferr|that|this)\b"
    r"|don'?t |you did ?n'?t|you'?re not|that'?s not|thats not|not what"
    r"|why (did|are|didn'?t) you|again[,.]|i (told|said) you"
    r"|keep (doing|writing|failing)|stupid|come on",
    re.IGNORECASE | re.MULTILINE,
)

# Machine prose that does not arrive inside a tag, checked against what is LEFT
# after stripping, so it can never throw away a real correction sent with it.
MACHINE_PHRASES = (
    "[SYSTEM NOTIFICATION - NOT USER INPUT]",
    "automated run of a scheduled task",
    "This is an automated background-task event",
)


def _is_correction(text: str) -> bool:
    if any(phrase in text for phrase in MACHINE_PHRASES):
        return False
    return bool(CORRECTION.search(text))


def _truncate(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    return text[:MAX_CHARS].rstrip() + " […truncated]"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    prompt = _strip_machine_blocks(_prompt(payload))
    if not prompt or not _is_correction(prompt):
        return 0

    vault = _vault_root()
    folder = vault / "System" / "Session_Learnings"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return 0

    now = datetime.now()
    path = folder / f"{now:%Y-%m-%d}.md"
    if not path.exists():
        header = (
            f"# Session Learnings - {now:%Y-%m-%d}\n\n"
            "Automatically captured from Claude Code sessions.\n\n---\n\n"
        )
        try:
            path.write_text(header, encoding="utf-8")
        except OSError:
            return 0

    entry = (
        f"## {now:%H:%M} - Correction\n\n"
        f"**What was said:**\n\n> {_truncate(prompt).replace(chr(10), chr(10) + '> ')}\n\n"
        "**Why it matters:** a correction is the highest-value signal about how this "
        "assistant fails, and it is lost when the session ends.\n\n"
        "**Suggested fix:** classify during /daily-review and route to "
        "`Mistake_Patterns.md`, `Working_Preferences.md`, a memory file, or a skill step.\n"
        "**Status:** pending\n\n---\n\n"
    )
    try:
        with path.open("a+", encoding="utf-8") as handle:
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            handle.write(entry)
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
