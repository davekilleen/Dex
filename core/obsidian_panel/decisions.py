"""Read recorded decisions from local vault files. Never writes. Never sends."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

EMPTY_SENTENCE = "No recorded decision in your files matched that topic."
LATELY_EMPTY = "No recorded decision in your files lately."
LATELY_LIMIT = 3
NO_DATE = "no date in that note"
DATE_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}$")
USER_TREES = (
    "00-Inbox",
    "04-Projects",
    "05-Areas",
    "06-Resources",
    "07-Archives",
)

DECISION_HEADING = re.compile(r"^##\s+(?:Key\s+)?Decisions\s*$", re.IGNORECASE)
DECISION_LOG_HEADING = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s+[—–-]\s+(.+)$")
DECISION_FIELD = re.compile(r"^\*\*Decision:\*\*\s*(.+?)\s*$", re.IGNORECASE)
BULLET = re.compile(r"^[-*]\s+(?:\[[ xX]\]\s+)?(.+)$")
DATE_IN_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})")
FRONTMATTER_DATE = re.compile(
    r"^date:\s*['\"]?(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE | re.MULTILINE,
)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _note_name(relative_path: str) -> str:
    return Path(relative_path).stem


def _file_date(relative_path: str, text: str) -> str:
    named = DATE_IN_NAME.match(_note_name(relative_path))
    if named:
        return named.group(1)
    frontmatter = FRONTMATTER_DATE.search(text)
    if frontmatter:
        return frontmatter.group(1)
    return ""


def _clean_words(raw: str) -> str:
    text = str(raw or "").strip()
    text = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return text.strip()


def collect_decision_records(text: str, relative_path: str) -> list[dict[str, str]]:
    """Return recorded decision rows from one local markdown file."""
    note = _note_name(relative_path)
    from_file = _file_date(relative_path, text)
    records: list[dict[str, str]] = []
    in_decisions = False
    heading_date = ""
    heading_title = ""
    for raw in str(text or "").splitlines():
        log = DECISION_LOG_HEADING.match(raw)
        if log:
            in_decisions = False
            heading_date = log.group(1)
            heading_title = log.group(2).strip()
            continue
        if DECISION_HEADING.match(raw):
            in_decisions = True
            heading_date = ""
            heading_title = ""
            continue
        if raw.startswith("## "):
            in_decisions = False
            heading_date = ""
            heading_title = ""
            continue
        field = DECISION_FIELD.match(raw)
        if field:
            words = _clean_words(field.group(1))
            if words:
                records.append(
                    {
                        "words": words,
                        "note": note,
                        "date": heading_date or from_file or NO_DATE,
                        "title": heading_title,
                    }
                )
            continue
        if not in_decisions:
            continue
        bullet = BULLET.match(raw)
        if not bullet:
            continue
        words = _clean_words(bullet.group(1))
        if words:
            records.append(
                {
                    "words": words,
                    "note": note,
                    "date": from_file or heading_date or NO_DATE,
                    "title": heading_title,
                }
            )
    return records


def match_decisions(
    records: list[dict[str, str]],
    topic: str,
) -> list[dict[str, str]]:
    needle = " ".join(str(topic or "").split()).lower()
    if not needle:
        return []
    matches: list[dict[str, str]] = []
    for record in records:
        hay = f"{record.get('words', '')} {record.get('note', '')} {record.get('title', '')}"
        if needle in hay.lower():
            matches.append(record)
    return matches


def format_decision_match(record: dict[str, str]) -> str:
    return (
        f"{record.get('words', '')} "
        f"(note: {record.get('note', '')}, date: {record.get('date', NO_DATE)})"
    )


def recent_decisions(
    records: list[dict[str, str]],
    *,
    limit: int = LATELY_LIMIT,
) -> list[dict[str, str]]:
    """Return the latest dated records. No topic. Never writes."""
    dated: list[dict[str, str]] = []
    for record in records:
        stamp = str(record.get("date") or "")
        if not DATE_STAMP.match(stamp):
            continue
        dated.append(record)
    dated.sort(key=lambda row: str(row.get("date") or ""), reverse=True)
    return dated[: max(0, int(limit))]


def iter_user_markdown(vault: Path) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for tree in USER_TREES:
        root = vault / tree
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.md")):
            relative = path.relative_to(vault)
            if any(part.startswith(".") for part in relative.parts):
                continue
            files.append((relative.as_posix(), _read_text(path)))
    return files


def ask_recorded_decisions(
    vault: str | Path,
    topic: str,
) -> dict[str, Any]:
    """Return matching recorded decisions. Never writes. Never sends."""
    root = Path(vault).expanduser()
    records: list[dict[str, str]] = []
    for relative, text in iter_user_markdown(root):
        records.extend(collect_decision_records(text, relative))
    matches = match_decisions(records, topic)
    public = [
        {"words": row["words"], "note": row["note"], "date": row["date"]}
        for row in matches
    ]
    return {
        "matches": public,
        "empty": None if public else EMPTY_SENTENCE,
        "lines": [format_decision_match(row) for row in public],
    }


def recent_recorded_decisions(
    vault: str | Path,
    *,
    limit: int = LATELY_LIMIT,
) -> dict[str, Any]:
    """Return the latest dated recorded decisions. Never writes. Never sends."""
    root = Path(vault).expanduser()
    records: list[dict[str, str]] = []
    for relative, text in iter_user_markdown(root):
        records.extend(collect_decision_records(text, relative))
    matches = recent_decisions(records, limit=limit)
    public = [
        {"words": row["words"], "note": row["note"], "date": row["date"]}
        for row in matches
    ]
    return {
        "matches": public,
        "empty": None if public else LATELY_EMPTY,
        "lines": [format_decision_match(row) for row in public],
    }
