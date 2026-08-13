#!/usr/bin/env python3
"""Person-context payload shared by the Read hook and Work MCP.

``get_person_context(name)`` is the harness-neutral name. Claude Code still
injects this on file read; Cursor, ChatGPT, and Codex call the MCP tool.
"""

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

from core.entity_engine import parse_entity_page

PEOPLE_SUBDIRS = ("Internal", "External", "CPO_Network")
SKIP_EXTS = {
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
FILE_REF = re.compile(
    r"People/(?:Internal|External|CPO_Network)/([A-Za-z0-9_-]+)(?:\.md)?"
)
OPEN_ITEM = re.compile(r"^- \[ \] (.+)$", re.MULTILINE)
MEETING_HINTS = ("meeting", "attendee", "call with", "met with")


def _people_dir(vault: Path) -> Path:
    return vault / "05-Areas" / "People"


def _index_person_pages(vault: Path) -> dict[str, Path]:
    """Map normalised name variants to person-page paths (hook-compatible)."""
    index: dict[str, Path] = {}
    people_dir = _people_dir(vault)
    for subdir in PEOPLE_SUBDIRS:
        directory = people_dir / subdir
        if not directory.is_dir():
            continue
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for path in entries:
            if path.suffix.lower() != ".md":
                continue
            if path.name.lower() == "readme.md":
                continue
            stem = path.stem
            index[stem.lower()] = path
            index[stem.replace("_", " ").lower()] = path
    return index


def _open_items(content: str) -> list[str]:
    items: list[str] = []
    for match in OPEN_ITEM.finditer(content):
        items.append(match.group(1).replace("**", "").strip())
    return items


def _parse_person_page(path: Path) -> dict[str, Any] | None:
    try:
        entity = parse_entity_page(path)
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    name = entity.get("name") or path.stem.replace("_", " ")
    return {
        "name": name,
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
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        parsed = _parse_person_page(path)
        if parsed:
            people.append(parsed)
    return people


def get_person_context(vault: str | Path, name: str) -> dict[str, Any]:
    """Return the inject payload for one person name.

    Matching follows the hook's filename index (underscore or space, case
    insensitive). A unique first-name prefix is accepted when only one page
    matches.
    """
    root = Path(vault)
    query = (name or "").strip()
    if not query:
        return {
            "found": False,
            "name": query,
            "matches": [],
            "injected_text": "",
        }
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
            if " " in key or "_" in key
            if key.startswith(spaced) or key.startswith(folded)
        ]
        # Index stores two keys per file; unique by path.
        unique_prefix = list(dict.fromkeys(prefix_hits))
        if len(unique_prefix) == 1:
            paths = unique_prefix
    matches = _unique_people(paths)
    injected = format_person_context_block(matches) if matches else ""
    return {
        "found": bool(matches),
        "name": query,
        "matches": matches,
        "injected_text": injected,
    }


def find_people_in_file(vault: str | Path, file_path: str | Path) -> dict[str, Any]:
    """Detect people referenced in a file the same way the Read hook does."""
    root = Path(vault)
    target = Path(file_path)
    if not str(target):
        return {"skip": "missing-file-path-or-recursive-person-file", "matches": []}
    if "/People/" in str(target).replace("\\", "/"):
        return {"skip": "missing-file-path-or-recursive-person-file", "matches": []}
    if target.suffix.lower() in SKIP_EXTS:
        return {"skip": f"unsupported-extension:{target.suffix.lower()}", "matches": []}
    resolved = target if target.is_absolute() else root / target
    if not resolved.is_file():
        return {"skip": f"target-file-not-found:{resolved}", "matches": []}
    index = _index_person_pages(root)
    if not index:
        return {"skip": "no-person-pages-indexed", "matches": []}
    try:
        content = resolved.read_text(encoding="utf-8")
    except OSError as error:
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
            spaced = key.replace("_", " ")
            if spaced in content_lower:
                found_paths.append(path)
    matches = _unique_people(found_paths)
    if not found_paths:
        return {"skip": "no-person-references-found", "matches": []}
    if not matches:
        return {"skip": "person-context-parse-empty", "matches": []}
    return {
        "skip": None,
        "matches": matches,
        "injected_text": format_person_context_block(matches),
    }


def format_person_context_block(people: list[dict[str, Any]]) -> str:
    """Render the ``<person_context>`` block the Read hook injects."""
    lines = ["<person_context>", "Referenced people:"]
    for person in people:
        role = person.get("role") or "No role"
        company = person.get("company") or "Unknown"
        lines.append(f"{person.get('name')} - {role} @ {company}")
        last_interaction = person.get("last_interaction")
        if last_interaction:
            lines.append(f"  Last interaction: {last_interaction}")
        open_items = person.get("open_items") or []
        if open_items:
            lines.append(f"  Open items: {len(open_items)}")
            for item in open_items[:2]:
                clipped = item[:60] + ("..." if len(item) > 60 else "")
                lines.append(f"    - {clipped}")
    lines.append("</person_context>")
    return "\n".join(lines)


def inject_person_context_for_file(
    vault: str | Path, file_path: str | Path
) -> dict[str, Any]:
    """Hook-shaped result: skip reason or additionalContext XML."""
    result = find_people_in_file(vault, file_path)
    if result.get("skip"):
        return {"skip": result["skip"]}
    block = result.get("injected_text") or format_person_context_block(
        result.get("matches") or []
    )
    return {"additionalContext": "\n" + block}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print Dex person context")
    parser.add_argument("--vault", required=True, help="Vault root")
    parser.add_argument("--name", help="Person name for MCP-style lookup")
    parser.add_argument("--from-file", dest="from_file", help="File to scan")
    parser.add_argument(
        "--format",
        choices=("json", "hook-json", "text"),
        default="json",
    )
    args = parser.parse_args(argv)
    if args.from_file:
        payload = inject_person_context_for_file(args.vault, args.from_file)
    elif args.name:
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
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
