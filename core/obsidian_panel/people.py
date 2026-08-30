"""Read who a person is from local person pages. Never writes. Never sends."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

EMPTY_SENTENCE = "No person in your files matched that name."
PEOPLE_TREES = (
    "05-Areas/People/Internal",
    "05-Areas/People/External",
    "05-Areas/People/CPO_Network",
)
PERSON_FIELD = re.compile(
    r"^(?:\|\s*(?:\*\*)?)?(name|role|company)"
    r"(?:\*\*)?\s*(?:\||:)\s*(.*?)(?:\s*\|)?$",
    re.IGNORECASE,
)
HEADING = re.compile(r"^#\s+(.+)$")
BLANK_VALUES = {"", "null", "none", "~"}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _note_name(relative_path: str) -> str:
    return Path(relative_path).stem


def _clean_value(raw: str) -> str:
    value = str(raw or "").strip().strip("|").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    if value.lower() in BLANK_VALUES:
        return ""
    return value


def collect_person_record(text: str, relative_path: str) -> dict[str, str] | None:
    """Return one identity row from a local person page. Never writes."""
    note = _note_name(relative_path)
    fields = {"name": "", "role": "", "company": ""}
    heading = ""
    for raw in str(text or "").splitlines():
        if not heading:
            marked = HEADING.match(raw)
            if marked:
                heading = marked.group(1).strip()
        match = PERSON_FIELD.match(raw.strip())
        if not match:
            continue
        key = match.group(1).lower()
        value = _clean_value(match.group(2))
        if key in fields:
            fields[key] = value
    name = fields["name"] or heading or note.replace("_", " ")
    if not name:
        return None
    return {
        "name": name,
        "role": fields["role"],
        "company": fields["company"],
        "note": note,
    }


def match_people(
    records: list[dict[str, str]],
    query: str,
) -> list[dict[str, str]]:
    needle = " ".join(str(query or "").split()).lower()
    if not needle:
        return []
    matches: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in records:
        name = str(record.get("name") or "").lower()
        note = str(record.get("note") or "")
        spaced = note.replace("_", " ").lower()
        stem = note.lower()
        folded = needle.replace(" ", "_")
        if needle not in name and needle not in spaced and folded != stem and needle != name:
            continue
        key = note or name
        if key in seen:
            continue
        seen.add(key)
        matches.append(record)
    return matches


def format_person_match(record: dict[str, str]) -> str:
    who = str(record.get("name") or "").strip()
    role = str(record.get("role") or "").strip()
    company = str(record.get("company") or "").strip()
    if role and company:
        who = f"{who} — {role} at {company}"
    elif role:
        who = f"{who} — {role}"
    elif company:
        who = f"{who} — at {company}"
    return f"{who} (note: {record.get('note', '')})"


def iter_person_markdown(vault: Path) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for tree in PEOPLE_TREES:
        root = vault / tree
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.md")):
            try:
                if path.is_symlink() or not path.is_file():
                    continue
            except OSError:
                continue
            relative = path.relative_to(vault)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if path.name.lower() == "readme.md":
                continue
            files.append((relative.as_posix(), _read_text(path)))
    return files


def ask_who_they_are(
    vault: str | Path,
    name: str,
) -> dict[str, Any]:
    """Return who a named person is from local files. Never writes. Never sends."""
    root = Path(vault).expanduser()
    records: list[dict[str, str]] = []
    for relative, text in iter_person_markdown(root):
        record = collect_person_record(text, relative)
        if record:
            records.append(record)
    matches = match_people(records, name)
    public = [
        {
            "name": row["name"],
            "role": row["role"],
            "company": row["company"],
            "note": row["note"],
        }
        for row in matches
    ]
    return {
        "matches": public,
        "empty": None if public else EMPTY_SENTENCE,
        "lines": [format_person_match(row) for row in public],
    }
