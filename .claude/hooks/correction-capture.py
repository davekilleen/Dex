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
import sys
from datetime import datetime
from pathlib import Path

MAX_CHARS = 600
HEADING = "## {time} - Correction from Chris"


def _vault_root() -> Path:
    import os

    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def _prompt(payload: dict) -> str:
    for key in ("prompt", "user_prompt", "message", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


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

    prompt = _prompt(payload)
    if not prompt:
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
        with path.open("a", encoding="utf-8") as handle:
            handle.write(entry)
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
