"""Read who a person is from local person pages. Never writes. Never sends."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from core.paths import DAILY_PLANS_DIR, resolve_for_vault

EMPTY_SENTENCE = "No person in your files matched that name."
TODAY_HEADING = "Who today's plan names"
NOBODY_NAMED = "Today's plan does not name anyone in your files."
NO_PLAN = "There is no plan for today in your files."
NOTE_HEADING = "Who this note names"
NOTE_NOBODY = "That note does not name anyone from your person pages."
NOTE_MISSING = "There is no note at that path in your Dex folder."
NOTE_REFUSED = (
    "That path is not a note this panel will read. "
    "It reads only notes inside your own Dex folder."
)
PEOPLE_TREES = (
    "05-Areas/People/Internal",
    "05-Areas/People/External",
    "05-Areas/People/CPO_Network",
)
BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".webp",
    ".ico",
    ".svg",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".mp3",
    ".mp4",
    ".mov",
    ".wav",
    ".pptx",
    ".xlsx",
    ".docx",
}
PERSON_FIELD = re.compile(
    r"^(?:\|\s*(?:\*\*)?)?(name|role|company|last[_ ]interaction)"
    r"(?:\*\*)?\s*(?:\||:)\s*(.*?)(?:\s*\|)?$",
    re.IGNORECASE,
)
OPEN_ITEM = re.compile(r"^- \[ \] (.+)$")
HEADING = re.compile(r"^#\s+(.+)$")
WIKI_LINK = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")
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


def _unchecked_items(text: str) -> list[str]:
    """Keep exactly the page's `- [ ]` lines, in page order, bold marks stripped."""
    items: list[str] = []
    for raw in str(text or "").splitlines():
        match = OPEN_ITEM.match(raw)
        if not match:
            continue
        items.append(match.group(1).replace("**", "").strip())
    return items


def collect_person_record(text: str, relative_path: str) -> dict[str, Any] | None:
    """Return one identity row from a local person page. Never writes."""
    note = _note_name(relative_path)
    fields = {"name": "", "role": "", "company": "", "last_interaction": ""}
    heading = ""
    for raw in str(text or "").splitlines():
        if not heading:
            marked = HEADING.match(raw)
            if marked:
                heading = marked.group(1).strip()
        match = PERSON_FIELD.match(raw.strip())
        if not match:
            continue
        key = match.group(1).lower().replace(" ", "_")
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
        "last_interaction": fields["last_interaction"],
        "open_items": _unchecked_items(text),
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


def _is_name_boundary(char: str) -> bool:
    if not char:
        return True
    return not (char.isalnum() or char == "_")


def _first_named_index(haystack: str, needle: str) -> int | None:
    target = str(needle or "").strip()
    if len(target) < 2:
        return None
    lowered = haystack.lower()
    look = target.lower()
    start = 0
    while True:
        index = lowered.find(look, start)
        if index < 0:
            return None
        before = haystack[index - 1] if index else ""
        after_at = index + len(target)
        after = haystack[after_at] if after_at < len(haystack) else ""
        if _is_name_boundary(before) and _is_name_boundary(after):
            return index
        start = index + 1


def _record_needles(record: dict[str, str]) -> list[str]:
    needles: list[str] = []
    seen: set[str] = set()
    for raw in (
        str(record.get("name") or ""),
        str(record.get("note") or "").replace("_", " "),
        str(record.get("note") or ""),
    ):
        value = raw.strip()
        key = value.lower()
        if len(value) < 2 or key in seen:
            continue
        seen.add(key)
        needles.append(value)
    needles.sort(key=len, reverse=True)
    return needles


def _wiki_target_note(raw: str) -> str:
    target = str(raw or "").strip().replace("\\", "/")
    if not target:
        return ""
    base = Path(target).name
    if base.lower().endswith(".md"):
        base = base[:-3]
    return base.strip()


def _record_matches_wiki(record: dict[str, str], target: str) -> bool:
    note = str(record.get("note") or "")
    name = str(record.get("name") or "")
    stem = _wiki_target_note(target)
    if not stem:
        return False
    folded = stem.replace(" ", "_")
    spaced = stem.replace("_", " ")
    return (
        stem.lower() == note.lower()
        or folded.lower() == note.lower()
        or spaced.lower() == note.replace("_", " ").lower()
        or spaced.lower() == name.lower()
        or stem.lower() == name.lower()
    )


def people_named_in_plan(
    records: list[dict[str, str]],
    plan_text: str,
) -> list[dict[str, str]]:
    """Return person pages named in a plan, in plan order. Never invents fields."""
    haystack = str(plan_text or "")
    if not haystack.strip() or not records:
        return []
    hits: list[tuple[int, dict[str, str]]] = []
    for match in WIKI_LINK.finditer(haystack):
        for record in records:
            if _record_matches_wiki(record, match.group(1)):
                hits.append((match.start(), record))
                break
    for record in records:
        earliest: int | None = None
        for needle in _record_needles(record):
            index = _first_named_index(haystack, needle)
            if index is None:
                continue
            if earliest is None or index < earliest:
                earliest = index
        if earliest is not None:
            hits.append((earliest, record))
    hits.sort(key=lambda item: item[0])
    ordered: list[dict[str, str]] = []
    seen: set[str] = set()
    for _index, record in hits:
        key = str(record.get("note") or record.get("name") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(record)
    return ordered


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
    records = _load_person_records(root)
    matches = match_people(records, name)
    public = [_public_person(row) for row in matches]
    return {
        "matches": public,
        "empty": None if public else EMPTY_SENTENCE,
        "lines": [format_person_match(row) for row in public],
    }


def _public_person(record: dict[str, Any]) -> dict[str, str]:
    return {
        "name": record["name"],
        "role": record["role"],
        "company": record["company"],
        "note": record["note"],
    }


def _today_person(record: dict[str, Any]) -> dict[str, Any]:
    items = record.get("open_items")
    open_items = [str(item) for item in items] if isinstance(items, list) else []
    return {
        "name": record["name"],
        "role": record["role"],
        "company": record["company"],
        "note": record["note"],
        "last_interaction": str(record.get("last_interaction") or ""),
        "open_items": open_items,
    }


def _load_person_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, str]] = []
    for relative, text in iter_person_markdown(root):
        record = collect_person_record(text, relative)
        if record:
            records.append(record)
    return records


def people_named_in_today_plan(
    vault: str | Path,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Return who today's plan names from local person pages. Never writes."""
    stamp = today or date.today()
    root = Path(vault).expanduser()
    path = resolve_for_vault(root, DAILY_PLANS_DIR) / f"{stamp.isoformat()}.md"
    if not path.is_file():
        return {
            "matches": [],
            "empty": NO_PLAN,
            "lines": [],
            "plan": False,
        }
    records = _load_person_records(root)
    matches = people_named_in_plan(records, _read_text(path))
    public = [_today_person(row) for row in matches]
    return {
        "matches": public,
        "empty": None if public else NOBODY_NAMED,
        "lines": [format_person_match(row) for row in public],
        "plan": True,
    }


def _inside_vault(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _person_tree_path(raw: str) -> bool:
    normalised = str(raw or "").replace("\\", "/")
    if (
        not normalised
        or normalised == "People"
        or normalised.startswith("People/")
        or "/People/" in normalised
    ):
        return True
    return False


def _resolve_note_path(root: Path, note_path: str | Path) -> tuple[str | None, Path | None]:
    """Resolve a typed path the way today's plan file is resolved.

    Inside the vault, regular file, not a symlink, not a binary extension.
    Never follows a symlink. Never reads outside the vault.
    """
    try:
        raw_path = str(note_path)
        target = Path(note_path)
    except (TypeError, ValueError, OSError):
        return NOTE_REFUSED, None
    if not raw_path.strip() or _person_tree_path(raw_path):
        return NOTE_REFUSED, None
    if target.suffix.lower() in BINARY_EXTENSIONS:
        return NOTE_REFUSED, None
    candidate = target if target.is_absolute() else root / target
    try:
        if candidate.is_symlink():
            return NOTE_REFUSED, None
    except OSError:
        return NOTE_REFUSED, None
    try:
        resolved = candidate.resolve()
    except OSError:
        return NOTE_MISSING, None
    if not _inside_vault(root, resolved):
        return NOTE_REFUSED, None
    try:
        if resolved.is_symlink() or not resolved.is_file():
            if not resolved.is_file():
                return NOTE_MISSING, None
            return NOTE_REFUSED, None
    except OSError:
        return NOTE_MISSING, None
    return None, resolved


def people_named_in_note(
    vault: str | Path,
    note_path: str | Path,
) -> dict[str, Any]:
    """Return who a chosen note names from local person pages. Never writes."""
    root = Path(vault).expanduser()
    reason, path = _resolve_note_path(root, note_path)
    if reason is not None or path is None:
        return {
            "matches": [],
            "empty": reason or NOTE_REFUSED,
            "lines": [],
            "note": False,
        }
    records = _load_person_records(root)
    matches = people_named_in_plan(records, _read_text(path))
    public = [_today_person(row) for row in matches]
    return {
        "matches": public,
        "empty": None if public else NOTE_NOBODY,
        "lines": [format_person_match(row) for row in public],
        "note": True,
    }
