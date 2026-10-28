#!/usr/bin/env python3
"""Extract candidate session lessons from a recorded transcript.

Session-end calls this so a closed session leaves more than a marker.
Candidates are heuristic — obvious corrections and stated preferences —
written in the same pending format /daily-review already uses.

This module is invoked as a file by the session-end hook, so it imports the
shared correction check as a sibling (no Dex package required at runtime).
It never calls the network. Any failure is silent and exits 0.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, TextIO

try:
    from .correction_detect import is_correction, user_words
    from .learning_title import learning_title_from_text
except ImportError:  # invoked as a file: python core/utils/session_lesson_extract.py
    from correction_detect import is_correction, user_words
    from learning_title import learning_title_from_text

MAX_CHARS = 600
MAX_BYTES_DEFAULT = 2_000_000
MAX_CANDIDATES_DEFAULT = 8
DEADLINE_SECONDS_DEFAULT = 2.0
MAX_USER_MESSAGES = 400

_PREFERENCE = re.compile(
    r"(?i)\bi prefer\b|\bi['’]d rather\b|\bi would rather\b"
    r"|\bfrom now on\b|\bgoing forward,"
    r"|\bremember (?:that|this|to)\b"
    r"|\balways (?:ask|check|confirm|use) (?:me|before|first)\b"
    r"|\bnever assume\b|\bi want (?:you to|dex to)\b"
)
_NO_PREFERENCE = re.compile(r"(?i)\bno preference\b")
_SLASH_ONLY = re.compile(r"^/[A-Za-z][\w:-]*(?:\s.*)?$")
_SECRETISH = re.compile(
    r"(?i)(api[_-]?key|secret|password|passwd|bearer\s+[a-z0-9._-]"
    r"|sk-ant-|sk-proj-|ghp_[A-Za-z0-9]|github_pat_|-----BEGIN"
    r"|xox[baprs]-)"
)
_STATUS_LINE = re.compile(r"^\*\*Status:\*\*", re.IGNORECASE)
_SESSION_MARK = re.compile(r"\*\*Session:\*\*\s*`([^`]+)`", re.IGNORECASE)
_TRANSCRIPT_MARK = re.compile(
    r"\*\*Transcript:\*\*\s*(?:recorded as\s+)?`([^`]+)`",
    re.IGNORECASE,
)
# Windows editors and Notepad "smart" punctuation must not look like a new lesson.
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

def strip_machine_text(text: str) -> str:
    """Return only the user's own words, or '' if nothing of theirs is left."""
    return user_words(text)


def _normalize_text(text: str) -> str:
    """Undo Windows file-shape differences before any comparison.

    Daily learning files on Windows often arrive with CRLF, a UTF-8 BOM, or
    NFC/NFD spelling of the same letters. Comparing the raw strings then
    treats yesterday's correction as new and appends it again.
    """
    if not text:
        return ""
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text)


def _fingerprint_text(text: str) -> str:
    """Stable wording key: line endings, quotes, markup, and case do not count."""
    normalized = _normalize_text(text).translate(_QUOTE_TRANSLATE)
    lines: list[str] = []
    for line in normalized.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("> "):
            stripped = stripped[2:]
        elif stripped == ">":
            stripped = ""
        lines.append(stripped)
    return " ".join("\n".join(lines).casefold().split())


def _normalize_path_key(value: Path | str) -> str:
    """Compare transcript paths across slash, case, and Windows prefix variants."""
    text = _normalize_text(str(value)).strip().replace("\\", "/")
    folded = text.casefold()
    if folded.startswith("//?/unc/"):
        text = "//" + text[8:]
    elif folded.startswith("//?/") or folded.startswith("//./"):
        text = text[4:]
    if len(text) >= 2 and text[1] == ":" and (len(text) == 2 or text[2] != "/"):
        text = f"{text[:2]}/{text[2:]}"
    if text.startswith("//"):
        rest = text[2:]
        while "//" in rest:
            rest = rest.replace("//", "/")
        text = "//" + rest
    else:
        while "//" in text:
            text = text.replace("//", "/")
    return unicodedata.normalize("NFC", text).casefold()


def _decode_learning_bytes(data: bytes) -> str:
    """Read a learning file without assuming UTF-8 or Unix line endings."""
    if not data:
        return ""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class Candidate:
    kind: str
    text: str

    @property
    def fingerprint(self) -> str:
        return _fingerprint_text(self.text)


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
    stripped = user_words(text)
    if not stripped or _NO_PREFERENCE.search(stripped):
        return None
    if _SLASH_ONLY.match(stripped) and not is_correction(stripped):
        return None
    if _SECRETISH.search(stripped):
        return None
    if is_correction(stripped):
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
    # isCompactSummary: the harness's own summary of an earlier conversation,
    # written as a user turn. It quotes the user's past corrections back, so
    # reading it would re-file every one of them as new.
    if record.get("isMeta") or record.get("isSidechain") or record.get("isCompactSummary"):
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
    cleaned = (strip_machine_text(part) for part in texts if isinstance(part, str))
    return [part for part in cleaned if part]


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
    title = learning_title_from_text(candidate.text, candidate.kind)
    return (
        f"## {when:%H:%M} - {title}\n\n"
        f"**Kind:** {candidate.kind}\n\n"
        f"**What was said:**\n\n{_blockquote(candidate.text)}\n\n"
        f"**Why it matters:** {why}\n\n"
        "**Suggested fix:** confirm during /daily-review and route to "
        "`Mistake_Patterns.md`, `Working_Preferences.md`, a memory file, or a skill step.\n"
        "**Status:** pending\n\n---\n\n"
    )


def already_recorded(existing: str, candidate: Candidate) -> bool:
    needle = candidate.fingerprint
    if not needle:
        return True
    return needle in _fingerprint_text(existing)


_HEADER = (
    "# Session Learnings - {date}\n\n"
    "Automatically captured from Claude Code sessions.\n\n---\n\n"
)


@contextmanager
def _locked_learning_file(path: Path) -> Iterator[TextIO]:
    """Open today's file for append and hold an exclusive lock while writing.

    Parallel session-end hooks used to interleave and duplicate. The lock
    serializes writers. A missing lock API (native Windows without fcntl)
    still writes; the hook stays fail-open.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" keeps on-disk CRLF visible so de-dupe can normalise it,
    # and stops Windows text mode turning every write into a new CRLF copy.
    handle = path.open("a+", encoding="utf-8", newline="")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        yield handle
    finally:
        handle.close()


def _read_locked(handle: TextIO) -> str:
    """Read today's file from disk bytes.

    Windows append-mode handles can seek(0)/read() as empty even when the
    file has content. Comparing against that empty string re-appends every
    correction. Bytes + encoding detection is the same file on every OS.
    """
    handle.flush()
    try:
        return _decode_learning_bytes(Path(handle.name).read_bytes())
    except OSError:
        handle.seek(0)
        return _normalize_text(handle.read())


def _write_locked(handle: TextIO, text: str) -> None:
    handle.seek(0, os.SEEK_END)
    handle.write(text)
    handle.flush()


def session_already_recorded(existing: str, *, transcript: Path | None, session_id: str) -> bool:
    """True when this same session already left a marker in today's file."""
    body = _normalize_text(existing)
    if session_id and session_id.strip():
        wanted = session_id.strip().casefold()
        if any(
            match.group(1).strip().casefold() == wanted
            for match in _SESSION_MARK.finditer(body)
        ):
            return True
    if transcript is not None:
        wanted = _normalize_path_key(transcript)
        if wanted and any(
            _normalize_path_key(match.group(1)) == wanted for match in _TRANSCRIPT_MARK.finditer(body)
        ):
            return True
    return False


def render_session_marker(
    *,
    when: datetime,
    transcript: Path | None = None,
    session_id: str = "",
) -> str:
    lines = [f"## {when:%H:%M} - Session completed", "", "**Session ended**"]
    if session_id:
        lines.append(f"**Session:** `{session_id}`")
    if transcript is not None and transcript.is_file():
        lines.append(f"**Transcript:** `{transcript}`")
        lines.append("")
        lines.append(
            "_Note: Obvious corrections and preferences from this session are captured "
            "automatically when they can be spotted, marked pending. Run /daily-review "
            "to confirm them and catch anything the automatic pass missed._"
        )
    elif transcript is not None:
        lines.append(f"**Transcript:** recorded as `{transcript}`, but no file exists there.")
        lines.append("")
        lines.append("_Learnings cannot be extracted automatically. If this session mattered,")
        lines.append("capture them by hand before the detail is gone._")
    else:
        lines.append("**Transcript:** not supplied to this hook.")
        lines.append("")
        lines.append("_Learnings cannot be extracted automatically. If this session mattered,")
        lines.append("capture them by hand before the detail is gone._")
    lines.extend(["", "---", ""])
    return "\n".join(lines) + "\n"


def append_candidates(learning_file: Path, candidates: list[Candidate], *, when: datetime | None = None) -> int:
    """Append unseen candidates. Returns how many were written. Never raises."""
    if not candidates:
        return 0
    stamp = when or datetime.now()
    try:
        with _locked_learning_file(learning_file) as handle:
            existing = _read_locked(handle)
            written = 0
            chunks: list[str] = []
            for candidate in candidates:
                if already_recorded(existing, candidate):
                    continue
                if any(already_recorded(chunk, candidate) for chunk in chunks):
                    continue
                chunks.append(render_entry(candidate, stamp))
                written += 1
            if chunks:
                _write_locked(handle, "".join(chunks))
            return written
    except OSError:
        return 0


def record_session_end(
    learning_file: Path,
    *,
    transcript: Path | None = None,
    session_id: str = "",
    when: datetime | None = None,
) -> int:
    """Write the session marker and any new candidates under one lock.

    Returns how many chunks were written. Never raises. Existing file
    contents are never deleted or rewritten.
    """
    stamp = when or datetime.now()
    candidates = (
        extract_candidates(transcript)
        if transcript is not None and transcript.is_file()
        else []
    )
    try:
        with _locked_learning_file(learning_file) as handle:
            existing = _read_locked(handle)
            chunks: list[str] = []
            if not existing.strip():
                chunks.append(_HEADER.format(date=f"{stamp:%Y-%m-%d}"))
            seen = existing + "".join(chunks)
            if not session_already_recorded(seen, transcript=transcript, session_id=session_id):
                marker = render_session_marker(when=stamp, transcript=transcript, session_id=session_id)
                chunks.append(marker)
                seen += marker
            for candidate in candidates:
                if already_recorded(seen, candidate):
                    continue
                if any(already_recorded(chunk, candidate) for chunk in chunks):
                    continue
                entry = render_entry(candidate, stamp)
                chunks.append(entry)
                seen += entry
            if chunks:
                _write_locked(handle, "".join(chunks))
            return len(chunks)
    except OSError:
        return 0


def extract_and_append(transcript: Path, learning_file: Path, *, when: datetime | None = None) -> int:
    return append_candidates(learning_file, extract_candidates(transcript), when=when)


def main(argv: list[str] | None = None) -> int:
    try:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--transcript", default="")
        parser.add_argument("--learning-file", default="")
        parser.add_argument("--session-id", default="")
        parser.add_argument("--record-session", action="store_true")
        args, _unknown = parser.parse_known_args(argv)
        transcript = Path(args.transcript) if args.transcript else None
        learning_file = Path(args.learning_file) if args.learning_file else None
        if learning_file is None:
            return 0
        if args.record_session:
            record_session_end(
                learning_file,
                transcript=transcript,
                session_id=args.session_id,
            )
            return 0
        if transcript is None:
            return 0
        extract_and_append(transcript, learning_file)
    except Exception:
        return 1 if argv and "--record-session" in argv else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
