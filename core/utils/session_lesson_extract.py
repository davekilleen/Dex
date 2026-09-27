#!/usr/bin/env python3
"""Extract candidate session lessons from a recorded transcript.

Session-end calls this so a closed session leaves more than a marker.
Candidates are heuristic — obvious corrections and stated preferences —
written in the same pending format /daily-review already uses.

This module is self-contained (no Dex imports) so the hook can invoke the
file directly. It never calls the network. Any failure is silent and exits 0.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

MAX_CHARS = 600
MAX_BYTES_DEFAULT = 2_000_000
MAX_CANDIDATES_DEFAULT = 8
DEADLINE_SECONDS_DEFAULT = 2.0
MAX_USER_MESSAGES = 400

# Inclusive on purpose, matching .claude/hooks/correction-capture.sh: a miss
# loses the signal, a false positive costs one pending line.
_CORRECTION = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9])(?:no|nope|stop|wrong|incorrect)(?:[^A-Za-z0-9]|$)"
    r"|don'?t |you did ?n'?t|you'?re not|that'?s not|thats not|not what"
    r"|why (?:did|are|didn'?t) you|i (?:told|said) you"
    r"|keep (?:doing|writing|failing)|come on|actually,"
)
_PREFERENCE = re.compile(
    r"(?i)\bi prefer\b|\bi['’]d rather\b|\bi would rather\b"
    r"|\bfrom now on\b|\bgoing forward,"
    r"|\bremember (?:that|this|to)\b"
    r"|\balways (?:ask|check|confirm|use) (?:me|before|first)\b"
    r"|\bnever assume\b|\bi want (?:you to|dex to)\b"
)
_NO_PREFERENCE = re.compile(r"(?i)\bno preference\b")
_ORDINARY_NO = re.compile(
    r"(?i)\b(?:have no|has no|with no|there(?:'s| is) no|"
    r"no (?:problem|worries|thanks|rush|need|meetings?|idea|clue))\b"
)
_SLASH_ONLY = re.compile(r"^/[A-Za-z][\w:-]*(?:\s.*)?$")
_SECRETISH = re.compile(
    r"(?i)(api[_-]?key|secret|password|passwd|bearer\s+[a-z0-9._-]"
    r"|sk-ant-|sk-proj-|ghp_[A-Za-z0-9]|github_pat_|-----BEGIN"
    r"|xox[baprs]-)"
)
_STATUS_LINE = re.compile(r"^\*\*Status:\*\*", re.IGNORECASE)


@dataclass(frozen=True)
class Candidate:
    kind: str
    text: str

    @property
    def fingerprint(self) -> str:
        return " ".join(self.text.casefold().split())


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def classify(text: str) -> str | None:
    """Return 'Correction' or 'Preference', or None if this is not a lesson."""
    stripped = text.strip()
    if not stripped or _NO_PREFERENCE.search(stripped):
        return None
    if _SLASH_ONLY.match(stripped) and not _CORRECTION.search(stripped):
        return None
    if _SECRETISH.search(stripped):
        return None
    if _CORRECTION.search(stripped) and not _ORDINARY_NO.search(stripped):
        return "Correction"
    if _PREFERENCE.search(stripped):
        return "Preference"
    return None


def _content_texts(content: object) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    texts: list[str] = []
    for item in content:
        if isinstance(item, str):
            texts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if item_type in {"tool_result", "tool_use", "image", "thinking"}:
            continue
        text = item.get("text")
        if isinstance(text, str):
            texts.append(text)
    return texts


def user_texts_from_record(record: object) -> list[str]:
    """Pull user-authored text from one Claude Code / Cursor JSONL record."""
    if not isinstance(record, dict):
        return []
    if record.get("isMeta") or record.get("isSidechain"):
        return []
    typ = str(record.get("type") or "").lower()
    message = record.get("message")
    role = ""
    if isinstance(message, dict):
        role = str(message.get("role") or "").lower()
    texts: list[str] = []
    if typ in {"user", "human"} or role == "user":
        if isinstance(message, dict):
            texts.extend(_content_texts(message.get("content")))
        elif isinstance(message, str):
            texts.append(message)
        texts.extend(_content_texts(record.get("content")))
    prompt = record.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        if typ in {"", "user", "human", "userpromptsubmit"} or role == "user":
            texts.append(prompt)
    return [part.strip() for part in texts if isinstance(part, str) and part.strip()]


def _read_transcript_bytes(path: Path, max_bytes: int) -> bytes:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(-max_bytes, os.SEEK_END)
            data = handle.read(max_bytes)
            # First line may be a partial JSONL record; drop it.
            newline = data.find(b"\n")
            if newline >= 0:
                data = data[newline + 1 :]
            return data
        return handle.read(max_bytes)


def extract_candidates(
    transcript: Path,
    *,
    now: float | None = None,
    max_bytes: int | None = None,
    max_candidates: int | None = None,
    deadline_seconds: float | None = None,
) -> list[Candidate]:
    """Return pending-lesson candidates from a transcript. Never raises."""
    started = time.monotonic()
    deadline = started + (
        deadline_seconds
        if deadline_seconds is not None
        else _float_env("DEX_SESSION_LESSON_DEADLINE_SECONDS", DEADLINE_SECONDS_DEFAULT)
    )
    byte_limit = max_bytes if max_bytes is not None else _int_env(
        "DEX_SESSION_LESSON_MAX_BYTES", MAX_BYTES_DEFAULT
    )
    cap = max_candidates if max_candidates is not None else _int_env(
        "DEX_SESSION_LESSON_MAX_CANDIDATES", MAX_CANDIDATES_DEFAULT
    )
    _ = now  # reserved so tests can pin wall-clock later without a signature change
    try:
        if not transcript.is_file():
            return []
        raw = _read_transcript_bytes(transcript, byte_limit)
    except OSError:
        return []

    found: list[Candidate] = []
    seen: set[str] = set()
    scanned = 0
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return []

    for line in text.splitlines():
        if time.monotonic() >= deadline:
            break
        if scanned >= MAX_USER_MESSAGES:
            break
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        for utterance in user_texts_from_record(record):
            scanned += 1
            kind = classify(utterance)
            if kind is None:
                continue
            candidate = Candidate(kind=kind, text=_truncate(utterance))
            if not candidate.fingerprint or candidate.fingerprint in seen:
                continue
            seen.add(candidate.fingerprint)
            found.append(candidate)
            if len(found) >= cap:
                return found
    return found


def _truncate(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(cleaned) <= MAX_CHARS:
        return cleaned
    return cleaned[:MAX_CHARS].rstrip() + " […truncated]"


def _blockquote(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        if _STATUS_LINE.match(line.strip()):
            line = line.replace("**Status:**", "Status:", 1)
        lines.append(f"> {line}" if line else ">")
    return "\n".join(lines)


def render_entry(candidate: Candidate, when: datetime) -> str:
    why = (
        "a correction is the highest-value signal about how this assistant fails, "
        "and it is lost when nobody writes it down."
        if candidate.kind == "Correction"
        else "a stated preference should survive the session, not wait on a review that may not run."
    )
    return (
        f"## {when:%H:%M} - {candidate.kind}\n\n"
        f"**What was said:**\n\n{_blockquote(candidate.text)}\n\n"
        f"**Why it matters:** {why}\n\n"
        "**Suggested fix:** confirm during /daily-review and route to "
        "`Mistake_Patterns.md`, `Working_Preferences.md`, a memory file, or a skill step.\n"
        "**Status:** pending\n\n---\n\n"
    )


def already_recorded(existing: str, candidate: Candidate) -> bool:
    haystack = " ".join(existing.casefold().split())
    needle = candidate.fingerprint
    if not needle:
        return True
    return needle in haystack


def append_candidates(learning_file: Path, candidates: list[Candidate], *, when: datetime | None = None) -> int:
    """Append unseen candidates. Returns how many were written. Never raises."""
    if not candidates:
        return 0
    stamp = when or datetime.now()
    try:
        existing = learning_file.read_text(encoding="utf-8") if learning_file.is_file() else ""
    except OSError:
        return 0
    written = 0
    chunks: list[str] = []
    for candidate in candidates:
        if already_recorded(existing, candidate):
            continue
        if any(already_recorded(chunk, candidate) for chunk in chunks):
            continue
        chunks.append(render_entry(candidate, stamp))
        written += 1
    if not chunks:
        return 0
    try:
        learning_file.parent.mkdir(parents=True, exist_ok=True)
        with learning_file.open("a", encoding="utf-8") as handle:
            handle.write("".join(chunks))
    except OSError:
        return 0
    return written


def extract_and_append(transcript: Path, learning_file: Path, *, when: datetime | None = None) -> int:
    return append_candidates(learning_file, extract_candidates(transcript), when=when)


def main(argv: list[str] | None = None) -> int:
    try:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--transcript", default="")
        parser.add_argument("--learning-file", default="")
        args, _unknown = parser.parse_known_args(argv)
        transcript = Path(args.transcript) if args.transcript else None
        learning_file = Path(args.learning_file) if args.learning_file else None
        if transcript is None or learning_file is None:
            return 0
        extract_and_append(transcript, learning_file)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
