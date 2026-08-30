#!/usr/bin/env python3
"""Portable person context shared by the Read hook and Work MCP."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from core.entity_engine import parse_entity_page as _canonical_parse_entity_page
except (ImportError, ModuleNotFoundError):  # standalone plugin has no full entity engine
    _canonical_parse_entity_page = None

from core.paths import DAILY_PLANS_DIR, PEOPLE_DIR, resolve_for_vault

PEOPLE_SUBDIRS = ("Internal", "External", "CPO_Network")
SKIP_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".svg",
    ".pdf", ".zip", ".tar", ".gz", ".mp3", ".mp4", ".mov", ".wav",
    ".pptx", ".xlsx", ".docx",
}
FILE_REF = re.compile(
    r"People/(?:Internal|External|CPO_Network)/([A-Za-z0-9_-]+)(?:\.md)?"
)
OPEN_ITEM = re.compile(r"^- \[ \] (.+)$", re.MULTILINE)
NONE_OPEN_SENTENCE = "No unchecked to-dos on person pages."
NONE_TODAY_PEOPLE_SENTENCE = "Nobody is named in today's plan."
NONE_NOTE_PEOPLE_SENTENCE = "That note does not name anyone from your person pages."
NOTE_MISSING_SENTENCE = "There is no note at that path in your Dex folder."
NOTE_REFUSED_SENTENCE = (
    "That path is not a note this box will read. "
    "It reads only notes inside your own Dex folder."
)
MEETING_HINTS = ("meeting", "attendee", "call with", "met with")
WIKI_LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
PERSON_FIELD = re.compile(
    r"^(?:\|\s*(?:\*\*)?)?(name|role|company|last[_ ]interaction)"
    r"(?:\*\*)?\s*(?:\||:)\s*(.*?)(?:\s*\|)?$",
    re.IGNORECASE,
)


def _coerce_root(vault: str | Path | None) -> Path | None:
    if vault is None:
        return None
    try:
        root = Path(vault).expanduser()
    except (TypeError, ValueError, OSError):
        return None
    try:
        if not root.is_dir():
            return None
        return root.resolve()
    except OSError:
        return None


def _people_dir(vault: Path) -> Path:
    return resolve_for_vault(vault, PEOPLE_DIR)


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _relative_file(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def _index_person_pages(vault: Path) -> dict[str, Path]:
    """Map normalised names to real person-page paths, without symlink escape."""
    index: dict[str, Path] = {}
    people_dir = _people_dir(vault)
    for subdir in PEOPLE_SUBDIRS:
        directory = people_dir / subdir
        try:
            if not directory.is_dir() or not _inside(vault, directory):
                continue
            entries = list(directory.iterdir())
        except OSError:
            continue
        for path in entries:
            if path.suffix.lower() != ".md" or path.name.lower() == "readme.md":
                continue
            try:
                if path.is_symlink() or not path.is_file() or not _inside(vault, path):
                    continue
            except OSError:
                continue
            stem = path.stem
            index[stem.lower()] = path
            index[stem.replace("_", " ").lower()] = path
    return index


def _open_items(content: str) -> list[str]:
    return [match.group(1).replace("**", "").strip() for match in OPEN_ITEM.finditer(content)]


def _portable_person_fields(content: str) -> dict[str, str | None]:
    """Read the small person-context field subset without third-party packages.

    The full Dex runtime still uses the entity engine when it is available. A
    packaged plugin can fall back to this parser for canonical frontmatter and
    the historic table/inline forms without installing PyYAML.
    """
    fields: dict[str, str | None] = {
        "name": None,
        "role": None,
        "company": None,
        "last_interaction": None,
    }
    for raw_line in content.splitlines():
        line = raw_line.strip()
        match = PERSON_FIELD.match(line)
        if not match:
            continue
        key = match.group(1).lower().replace(" ", "_")
        value = match.group(2).strip().strip("|").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1].strip()
        if value.lower() in {"", "null", "none", "~"}:
            value = ""
        fields[key] = value or None
    return fields


def _parse_person_page(path: Path) -> dict[str, Any] | None:
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return None
    entity: dict[str, Any] | None = None
    if _canonical_parse_entity_page is not None:
        try:
            parsed = _canonical_parse_entity_page(path)
            entity = parsed if isinstance(parsed, dict) else None
        except Exception:
            entity = None
    if entity is None:
        entity = _portable_person_fields(content)
    if not isinstance(entity, dict):
        return None
    name = entity.get("name") or path.stem.replace("_", " ")
    return {
        "name": str(name),
        "role": entity.get("role"),
        "company": entity.get("company"),
        "last_interaction": entity.get("last_interaction"),
        "open_items": _open_items(content),
        "path": str(path),
    }


def _unique_people(paths: list[Path]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    people: list[dict[str, Any]] = []
    for path in paths:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        parsed = _parse_person_page(path)
        if parsed:
            people.append(parsed)
    return people


def ask_what_is_still_open_with_people(vault: str | Path | None) -> dict[str, Any]:
    """Return every unchecked to-do from person pages, never raising.

    Each match names the person and the page. Meeting notes and the task list
    are not a substitute. The function never writes and never reaches the
    network. If nothing is open, the payload carries an honest sentence.
    """
    empty = {"found": False, "matches": [], "sentence": NONE_OPEN_SENTENCE}
    root = _coerce_root(vault)
    if root is None:
        return empty
    people = _unique_people(list(_index_person_pages(root).values()))
    matches: list[dict[str, str]] = []
    for person in people:
        name = str(person.get("name") or "").strip()
        raw_path = person.get("path")
        page = ""
        if isinstance(raw_path, str) and raw_path:
            page = _relative_file(root, Path(raw_path))
        items = person.get("open_items")
        if not name or not isinstance(items, list):
            continue
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            matches.append({"item": text, "person": name, "page": page})
    matches.sort(
        key=lambda row: (row.get("person") or "", row.get("page") or "", row.get("item") or "")
    )
    if not matches:
        return empty
    return {"found": True, "matches": matches, "sentence": ""}


def _recorded(value: Any) -> str:
    """Return a stored field as text, or empty. Never invent a placeholder."""
    if value is None:
        return ""
    text = value.strip() if isinstance(value, str) else str(value).strip()
    if not text or text.lower() in {"null", "none", "~"}:
        return ""
    return text


def _today_plan_file(root: Path, today: date | None = None) -> Path | None:
    try:
        stamp = (today or date.today()).strftime("%Y-%m-%d")
    except (AttributeError, OverflowError, ValueError):
        stamp = date.today().strftime("%Y-%m-%d")
    path = resolve_for_vault(root, DAILY_PLANS_DIR) / f"{stamp}.md"
    try:
        if path.is_symlink() or not path.is_file() or not _inside(root, path):
            return None
    except OSError:
        return None
    return path


def _wiki_lookup_keys(raw: str) -> list[str]:
    target = raw.strip()
    stem = Path(target.replace("\\", "/")).name
    if stem.lower().endswith(".md"):
        stem = stem[:-3]
    folded = stem.lower()
    spaced = stem.replace("_", " ").lower()
    keys = [folded]
    if spaced != folded:
        keys.append(spaced)
    return keys


def _unique_index_paths(index: dict[str, Path]) -> list[Path]:
    seen: set[str] = set()
    paths: list[Path] = []
    for path in index.values():
        try:
            ident = str(path.resolve())
        except OSError:
            ident = str(path)
        if ident in seen:
            continue
        seen.add(ident)
        paths.append(path)
    return paths


def _people_named_in_plan(content: str, index: dict[str, Path]) -> list[Path]:
    """Person pages named in the plan, first mention first. Never guessed."""
    content_lower = content.lower()
    hits: list[tuple[int, Path]] = []
    for match in WIKI_LINK.finditer(content):
        for key in _wiki_lookup_keys(match.group(1)):
            if key in index:
                hits.append((match.start(), index[key]))
                break
    for match in FILE_REF.finditer(content):
        key = match.group(1).lower()
        if key in index:
            hits.append((match.start(), index[key]))
    for path in _unique_index_paths(index):
        needle = path.stem.replace("_", " ").lower()
        if " " not in needle:
            continue
        pos = content_lower.find(needle)
        if pos >= 0:
            hits.append((pos, path))
    hits.sort(key=lambda item: item[0])
    ordered: list[Path] = []
    seen: set[str] = set()
    for _offset, path in hits:
        try:
            ident = str(path.resolve())
        except OSError:
            ident = str(path)
        if ident in seen:
            continue
        seen.add(ident)
        ordered.append(path)
    return ordered


def _today_people_row(root: Path, path: Path) -> dict[str, Any]:
    parsed = _parse_person_page(path)
    page = _relative_file(root, path)
    if not parsed:
        return {
            "person": path.stem.replace("_", " "),
            "role": "",
            "company": "",
            "last_interaction": "",
            "open_items": [],
            "page": page,
        }
    raw_items = parsed.get("open_items")
    open_items: list[str] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            text = str(item).strip()
            if text:
                open_items.append(text)
    return {
        "person": _recorded(parsed.get("name")) or path.stem.replace("_", " "),
        "role": _recorded(parsed.get("role")),
        "company": _recorded(parsed.get("company")),
        "last_interaction": _recorded(parsed.get("last_interaction")),
        "open_items": open_items,
        "page": page,
    }


def ask_who_is_in_todays_plan(
    vault: str | Path | None,
    today: date | None = None,
) -> dict[str, Any]:
    """Return each named person in today's plan, never raising.

    Each row carries recorded role, company, last interaction, every open
    item, and the person page, in plan order. Missing fields stay empty.
    Meeting notes and the task list are not a substitute. The function
    never writes and never reaches the network.
    """
    empty = {"found": False, "matches": [], "sentence": NONE_TODAY_PEOPLE_SENTENCE}
    root = _coerce_root(vault)
    if root is None:
        return empty
    plan = _today_plan_file(root, today)
    if plan is None:
        return empty
    try:
        content = plan.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return empty
    index = _index_person_pages(root)
    if not index:
        return empty
    matches = [_today_people_row(root, path) for path in _people_named_in_plan(content, index)]
    if not matches:
        return empty
    return {"found": True, "matches": matches, "sentence": ""}


def _empty_who_in_note(sentence: str) -> dict[str, Any]:
    return {"found": False, "matches": [], "sentence": sentence}


def _note_path_read_fence(
    root: Path, note_path: str | Path | None
) -> tuple[str | None, Path | None]:
    """Reuse find_people_in_file read fences. Never follow a symlink."""
    if note_path is None:
        return NOTE_REFUSED_SENTENCE, None
    try:
        raw_path = str(note_path)
        target = Path(note_path)
    except (TypeError, ValueError, OSError):
        return NOTE_REFUSED_SENTENCE, None
    normalised_raw_path = raw_path.replace("\\", "/")
    if (
        not raw_path.strip()
        or normalised_raw_path == "People"
        or normalised_raw_path.startswith("People/")
        or "/People/" in normalised_raw_path
    ):
        return NOTE_REFUSED_SENTENCE, None
    if target.suffix.lower() in SKIP_EXTS:
        return NOTE_REFUSED_SENTENCE, None
    resolved = target if target.is_absolute() else root / target
    try:
        if resolved.is_symlink():
            return NOTE_REFUSED_SENTENCE, None
    except OSError:
        return NOTE_REFUSED_SENTENCE, None
    try:
        resolved = resolved.resolve()
    except OSError:
        return NOTE_MISSING_SENTENCE, None
    if not _inside(root, resolved):
        return NOTE_REFUSED_SENTENCE, None
    try:
        if not resolved.is_file():
            return NOTE_MISSING_SENTENCE, None
    except OSError:
        return NOTE_MISSING_SENTENCE, None
    return None, resolved


def ask_who_is_named_in_note(
    vault: str | Path | None,
    note_path: str | Path | None,
) -> dict[str, Any]:
    """Return each named person in one note, never raising.

    Each row carries recorded role, company, last interaction, every open
    item, and the person page, in the note's own order of first mention.
    Missing fields stay empty. The function never writes and never
    reaches the network. Paths outside the vault, person-tree recursion,
    binary files, and symlinks are refused. A missing file gets an honest
    sentence. A note that names nobody gets an honest sentence.
    """
    nobody = _empty_who_in_note(NONE_NOTE_PEOPLE_SENTENCE)
    root = _coerce_root(vault)
    if root is None:
        return nobody
    fence, path = _note_path_read_fence(root, note_path)
    if fence is not None:
        return _empty_who_in_note(fence)
    if path is None:
        return _empty_who_in_note(NOTE_REFUSED_SENTENCE)
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return _empty_who_in_note(NOTE_REFUSED_SENTENCE)
    index = _index_person_pages(root)
    if not index:
        return nobody
    matches = [
        _today_people_row(root, person_path)
        for person_path in _people_named_in_plan(content, index)
    ]
    if not matches:
        return nobody
    return {"found": True, "matches": matches, "sentence": ""}


def get_person_context(vault: str | Path | None, name: Any) -> dict[str, Any]:
    """Return the context payload for one person, never raising on bad input."""
    root = _coerce_root(vault)
    # A person query is user-facing text; treating arbitrary objects as their
    # repr can leak implementation details into context, so malformed values
    # are simply an empty lookup.
    query = name.strip() if isinstance(name, str) else ""
    empty = {"found": False, "name": query, "matches": [], "injected_text": ""}
    if root is None or not query:
        return empty
    index = _index_person_pages(root)
    folded = query.lower().replace(" ", "_")
    spaced = query.lower().replace("_", " ")
    paths: list[Path] = []
    for key in (folded, spaced, query.lower()):
        if key in index:
            paths.append(index[key])
    if not paths:
        prefix_hits = [
            path
            for key, path in index.items()
            if (" " in key or "_" in key) and (key.startswith(spaced) or key.startswith(folded))
        ]
        unique_prefix = list(dict.fromkeys(prefix_hits))
        if len(unique_prefix) == 1:
            paths = unique_prefix
    matches = _unique_people(paths)
    empty["found"] = bool(matches)
    empty["matches"] = matches
    empty["injected_text"] = format_person_context_block(matches) if matches else ""
    return empty


def find_people_in_file(vault: str | Path | None, file_path: str | Path | None) -> dict[str, Any]:
    """Detect people referenced in a file, matching the Claude Read hook."""
    root = _coerce_root(vault)
    if root is None:
        return {"skip": "invalid-vault-root", "matches": []}
    if file_path is None:
        return {"skip": "missing-file-path-or-recursive-person-file", "matches": []}
    try:
        raw_path = str(file_path)
        target = Path(file_path)
    except (TypeError, ValueError, OSError):
        return {"skip": "invalid-file-path", "matches": []}
    normalised_raw_path = raw_path.replace("\\", "/")
    if (
        not raw_path.strip()
        or normalised_raw_path == "People"
        or normalised_raw_path.startswith("People/")
        or "/People/" in normalised_raw_path
    ):
        return {"skip": "missing-file-path-or-recursive-person-file", "matches": []}
    if target.suffix.lower() in SKIP_EXTS:
        return {"skip": f"unsupported-extension:{target.suffix.lower()}", "matches": []}
    resolved = target if target.is_absolute() else root / target
    try:
        resolved = resolved.resolve()
    except OSError:
        return {"skip": "target-file-not-found", "matches": []}
    if not _inside(root, resolved):
        return {"skip": f"target-file-outside-vault:{resolved}", "matches": []}
    try:
        if not resolved.is_file():
            return {"skip": f"target-file-not-found:{resolved}", "matches": []}
    except OSError:
        return {"skip": f"target-file-not-found:{resolved}", "matches": []}
    index = _index_person_pages(root)
    if not index:
        return {"skip": "no-person-pages-indexed", "matches": []}
    try:
        content = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return {"skip": f"unexpected-error:{error}", "matches": []}
    found_paths: list[Path] = []
    for match in FILE_REF.finditer(content):
        key = match.group(1).lower()
        if key in index:
            found_paths.append(index[key])
    content_lower = content.lower()
    if any(hint in content_lower for hint in MEETING_HINTS):
        for key, path in index.items():
            if " " not in key and "_" not in key:
                continue
            if key.replace("_", " ") in content_lower:
                found_paths.append(path)
    matches = _unique_people(found_paths)
    if not found_paths:
        return {"skip": "no-person-references-found", "matches": []}
    if not matches:
        return {"skip": "person-context-parse-empty", "matches": []}
    return {"skip": None, "matches": matches, "injected_text": format_person_context_block(matches)}


def format_person_context_block(people: Any) -> str:
    """Render the XML-like context block, ignoring malformed rows."""
    lines = ["<person_context>", "Referenced people:"]
    if isinstance(people, list):
        for person in people:
            if not isinstance(person, dict):
                continue
            name = str(person.get("name") or "").strip()
            if not name:
                continue
            role = str(person.get("role") or "No role")
            company = str(person.get("company") or "Unknown")
            lines.append(f"{name} - {role} @ {company}")
            last_interaction = str(person.get("last_interaction") or "").strip()
            if last_interaction:
                lines.append(f"  Last interaction: {last_interaction}")
            open_items = person.get("open_items")
            if isinstance(open_items, list) and open_items:
                lines.append(f"  Open items: {len(open_items)}")
                for item in open_items[:2]:
                    clipped = str(item)[:60]
                    if len(str(item)) > 60:
                        clipped += "..."
                    lines.append(f"    - {clipped}")
    lines.append("</person_context>")
    return "\n".join(lines)


def inject_person_context_for_file(vault: str | Path | None, file_path: str | Path | None) -> dict[str, Any]:
    """Return the Claude hook-shaped result for a file read."""
    result = find_people_in_file(vault, file_path)
    if result.get("skip"):
        return {"skip": result["skip"]}
    block = result.get("injected_text") or format_person_context_block(result.get("matches") or [])
    return {"additionalContext": "\n" + block}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print Dex person context")
    parser.add_argument("--vault", required=True, help="Vault root")
    parser.add_argument("--name", help="Person name for MCP-style lookup")
    parser.add_argument("--from-file", dest="from_file", help="File to scan")
    parser.add_argument(
        "--still-open",
        action="store_true",
        help="List unchecked to-dos from person pages",
    )
    parser.add_argument(
        "--todays-plan",
        action="store_true",
        help="List people named in today's plan",
    )
    parser.add_argument("--format", choices=("json", "hook-json", "text"), default="json")
    args = parser.parse_args(argv)
    if args.todays_plan:
        payload = ask_who_is_in_todays_plan(args.vault)
    elif args.still_open:
        payload = ask_what_is_still_open_with_people(args.vault)
    elif args.from_file:
        payload = inject_person_context_for_file(args.vault, args.from_file)
    elif args.name is not None:
        payload = get_person_context(args.vault, args.name)
    else:
        parser.error("pass --name, --from-file, --still-open, or --todays-plan")
        return 2
    if args.format == "text":
        if args.todays_plan:
            matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
            if not matches:
                sys.stdout.write(str(payload.get("sentence") or NONE_TODAY_PEOPLE_SENTENCE) + "\n")
                return 0
            for match in matches:
                if not isinstance(match, dict):
                    continue
                sys.stdout.write(f"{match.get('person') or ''}\n")
                sys.stdout.write(f"Role: {match.get('role') or ''}\n")
                sys.stdout.write(f"Company: {match.get('company') or ''}\n")
                sys.stdout.write(f"Last interaction: {match.get('last_interaction') or ''}\n")
                items = match.get("open_items")
                if isinstance(items, list) and items:
                    for item in items:
                        sys.stdout.write(f"Open item: {item}\n")
                else:
                    sys.stdout.write("Open item: \n")
                sys.stdout.write(f"Page: {match.get('page') or ''}\n")
            return 0
        if args.still_open:
            matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
            if not matches:
                sys.stdout.write(str(payload.get("sentence") or NONE_OPEN_SENTENCE) + "\n")
                return 0
            for match in matches:
                if not isinstance(match, dict):
                    continue
                sys.stdout.write(f"{match.get('item') or ''}\n")
                sys.stdout.write(f"Person: {match.get('person') or ''}\n")
                sys.stdout.write(f"Page: {match.get('page') or ''}\n")
            return 0
        text = payload.get("injected_text") or payload.get("additionalContext") or ""
        sys.stdout.write(str(text).lstrip("\n"))
        if text and not str(text).endswith("\n"):
            sys.stdout.write("\n")
        return 0
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
