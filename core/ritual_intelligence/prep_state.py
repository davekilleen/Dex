"""Managed prep-block parsing and lock detection."""

from __future__ import annotations

import hashlib
import re

PREP_START = "<!-- dex:prep:start -->"
PREP_END = "<!-- dex:prep:end -->"

PREP_BLOCK_RE = re.compile(
    rf"{re.escape(PREP_START)}\n?(?P<body>.*?){re.escape(PREP_END)}",
    re.DOTALL,
)


def prep_hash(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()


def extract_prep_block(content: str) -> str | None:
    match = PREP_BLOCK_RE.search(content)
    if not match:
        return None
    return match.group("body").strip("\n")


def replace_prep_block(content: str, new_block: str) -> str:
    replacement = f"{PREP_START}\n{new_block.rstrip()}\n{PREP_END}"
    if PREP_BLOCK_RE.search(content):
        return PREP_BLOCK_RE.sub(replacement, content, count=1)
    notes_anchor = "\n## Notes"
    if notes_anchor in content:
        return content.replace(notes_anchor, f"\n{replacement}\n{notes_anchor}", 1)
    return f"{content.rstrip()}\n\n{replacement}\n"
