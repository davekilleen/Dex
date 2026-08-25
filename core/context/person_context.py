#!/usr/bin/env python3
"""Portable person context shared by the Read hook and Work MCP."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from core.entity_engine import parse_entity_page as _canonical_parse_entity_page
except (ImportError, ModuleNotFoundError):  # standalone plugin has no full entity engine
    _canonical_parse_entity_page = None

from core.paths import PEOPLE_DIR, resolve_for_vault

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
MEETING_HINTS = ("meeting", "attendee", "call with", "met with")
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
    parser.add_argument("--format", choices=("json", "hook-json", "text"), default="json")
    args = parser.parse_args(argv)
    if args.from_file:
        payload = inject_person_context_for_file(args.vault, args.from_file)
    elif args.name is not None:
        payload = get_person_context(args.vault, args.name)
    else:
        parser.error("pass --name or --from-file")
        return 2
    if args.format == "text":
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
