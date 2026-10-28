"""Retitle generic learnings and split notes that were piled together.

Older vaults saved every correction under ``Correction`` and then merged them
into one backlog idea. This pass is background, fail-open, and idempotent:
it rewrites only generic headings, keeps every word, and is a no-op once
titles already come from content.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    from .learning_routing import _DAY_FILE, LEARNINGS_RELATIVE
    from .learning_title import (
        contents_match,
        is_generic_template,
        is_generic_title,
        learning_title_from_text,
        retitle_learning_entry,
    )
except ImportError:  # invoked as a file
    from learning_routing import _DAY_FILE, LEARNINGS_RELATIVE
    from learning_title import (
        contents_match,
        is_generic_template,
        is_generic_title,
        learning_title_from_text,
        retitle_learning_entry,
    )

RECEIPT_RELATIVE = Path("System") / ".dex" / "learning-title-backfill.json"
BACKLOG_RELATIVE = Path("System") / "Dex_Backlog.md"
RECEIPT_VERSION = 1

_IDEA_LINE = re.compile(r"^(?P<indent>\s*-\s*\*\*\[(?P<id>idea-\d{3})\]\*\*\s*)(?P<title>.+?)\s*$")
_WHY_NOW = re.compile(
    r"^\s*-\s*\*\*[^\n]*Why Now\?[^*]*\*\*\s*(?P<body>.+?)\s*(?:\*\(Source:[^*]*\)\*)?\s*$",
    re.IGNORECASE,
)
_SESSION_LEARNING_EVIDENCE = re.compile(
    r"Session learning\s*\((?P<date>\d{4}-\d{2}-\d{2})\):\s*(?P<rest>.+)",
    re.IGNORECASE,
)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """Hold an exclusive lock while rewriting. Fail-open if lock is missing."""
    handle = path.open("a+b")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        yield
    finally:
        handle.close()


def backfill_vault(vault_root: Path) -> dict[str, Any]:
    """Retitle and split mis-grouped notes. Never deletes. Never raises."""
    result: dict[str, Any] = {
        "retitled": 0,
        "split": 0,
        "unchanged": True,
        "files": [],
    }
    try:
        root = Path(vault_root)
        retitled = _retitle_learnings(root)
        split = _split_generic_backlog(root)
        result["retitled"] = retitled["count"]
        result["split"] = split["count"]
        result["files"] = retitled["files"] + split["files"]
        result["unchanged"] = retitled["count"] == 0 and split["count"] == 0
        _write_receipt(root, result)
    except Exception:
        return result
    return result


def _retitle_learnings(vault_root: Path) -> dict[str, Any]:
    folder = vault_root / LEARNINGS_RELATIVE
    changed_files: list[str] = []
    count = 0
    if not folder.is_dir():
        return {"count": 0, "files": []}
    for path in sorted(folder.glob("*.md")):
        if not _DAY_FILE.match(path.name):
            continue
        rewritten = _retitle_file(path)
        if rewritten:
            count += rewritten
            changed_files.append(str(path.relative_to(vault_root)))
    return {"count": count, "files": changed_files}


def _retitle_file(path: Path) -> int:
    try:
        with _locked(path):
            return _retitle_file_locked(path)
    except OSError:
        return 0


def _retitle_file_locked(path: Path) -> int:
    try:
        original = path.read_bytes()
        text = original.decode("utf-8", errors="replace")
    except OSError:
        return 0
    if text.startswith("\ufeff"):
        bom = True
        text = text[1:]
    else:
        bom = False
    pieces = re.split(r"(\r?\n---\r?\n)", text)
    changed = 0
    rewritten_parts: list[str] = []
    for piece in pieces:
        updated = retitle_learning_entry(piece)
        if updated != piece:
            changed += 1
        rewritten_parts.append(updated)
    if not changed:
        return 0
    rewritten = "".join(rewritten_parts)
    payload = ("\ufeff" if bom else "") + rewritten
    try:
        path.write_text(payload, encoding="utf-8", newline="")
    except OSError:
        return 0
    return changed


def _split_generic_backlog(vault_root: Path) -> dict[str, Any]:
    path = vault_root / BACKLOG_RELATIVE
    if not path.is_file():
        return {"count": 0, "files": []}
    try:
        with _locked(path):
            return _split_generic_backlog_locked(path)
    except OSError:
        return {"count": 0, "files": []}


def _split_generic_backlog_locked(path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return {"count": 0, "files": []}

    ideas = _parse_idea_blocks(content)
    if not ideas:
        return {"count": 0, "files": []}

    next_id = _next_idea_number(ideas)
    replacements: list[tuple[str, str]] = []
    created_blocks: list[str] = []
    split_count = 0

    for idea in ideas:
        if idea["status"] == "implemented":
            continue
        if not is_generic_title(idea["title"]):
            continue
        groups = _group_idea_evidence(idea)
        if not groups:
            new_title = learning_title_from_text(
                f"{idea.get('description', '')}\n{idea.get('evidence_text', '')}",
            )
            if new_title and new_title != idea["title"]:
                replacements.append((idea["raw_title_line"], _retitle_line(idea["raw_title_line"], new_title)))
                split_count += 1
            continue

        first, *rest = groups
        first_title = learning_title_from_text(first["content"])
        if first_title and first_title != idea["title"]:
            replacements.append((idea["raw_title_line"], _retitle_line(idea["raw_title_line"], first_title)))
            split_count += 1
        if rest:
            new_block = idea["block"]
            for extra in rest:
                for line in extra["lines"]:
                    new_block = new_block.replace(line, "", 1)
            if new_block != idea["block"]:
                replacements.append((idea["block"], new_block))
            for extra in rest:
                next_id += 1
                extra_title = learning_title_from_text(extra["content"], f"Learning {next_id:03d}")
                created_blocks.append(
                    _render_split_idea(
                        idea_id=f"idea-{next_id:03d}",
                        title=extra_title or first_title or idea["title"],
                        source_idea=idea,
                        extra=extra,
                    )
                )
                split_count += 1

    if not replacements and not created_blocks:
        return {"count": 0, "files": []}

    updated = content
    for old, new in replacements:
        if old and old in updated:
            updated = updated.replace(old, new, 1)
    if created_blocks:
        updated = _insert_low_priority(updated, created_blocks)
    if updated == content:
        return {"count": 0, "files": []}
    try:
        path.write_text(updated, encoding="utf-8")
    except OSError:
        return {"count": 0, "files": []}
    return {"count": split_count, "files": [BACKLOG_RELATIVE.as_posix()]}


def _parse_idea_blocks(content: str) -> list[dict[str, Any]]:
    ideas: list[dict[str, Any]] = []
    matches = list(re.finditer(r"^-\s*\*\*\[(idea-\d{3})\]\*\*\s*(.+?)\s*$", content, re.MULTILINE))
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else _section_end(content, start)
        block = content[start:end]
        title = match.group(2).strip()
        desc_match = re.search(r"\*\*Description:\*\*\s*(.+?)(?:\n\s*-|\n\s*\*\*|$)", block, re.DOTALL)
        why_lines = [line for line in block.splitlines() if _WHY_NOW.match(line)]
        ideas.append(
            {
                "id": match.group(1),
                "title": title,
                "block": block,
                "raw_title_line": match.group(0),
                "description": desc_match.group(1).strip() if desc_match else "",
                "evidence_text": "\n".join(why_lines),
                "why_lines": why_lines,
                "status": "implemented" if "Archive (Implemented)" in content[:start] else "active",
                "category": _field(block, "Category") or "system",
                "captured": _field(block, "Captured") or "",
                "source": _field(block, "Source") or "Session Learning Synthesis",
            }
        )
    return ideas


def _section_end(content: str, start: int) -> int:
    rest = content[start:]
    boundary = re.search(r"\n(?:### |## )", rest[1:])
    if boundary:
        return start + 1 + boundary.start()
    return len(content)


def _field(block: str, name: str) -> str:
    match = re.search(rf"\*\*{re.escape(name)}:\*\*\s*(.+)", block)
    return match.group(1).strip() if match else ""


def _group_idea_evidence(idea: dict[str, Any]) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    description = (idea.get("description") or "").strip()
    if description and not is_generic_template(description) and not is_generic_title(description):
        snippets.append({"content": description, "lines": []})
    for line in idea.get("why_lines") or []:
        match = _WHY_NOW.match(line)
        body = match.group("body") if match else line
        evidence = _SESSION_LEARNING_EVIDENCE.search(body)
        text = evidence.group("rest") if evidence else body
        if is_generic_title(text) or is_generic_template(text):
            continue
        snippets.append({"content": text, "lines": [line]})

    groups: list[dict[str, Any]] = []
    for snippet in snippets:
        placed = False
        for group in groups:
            if contents_match(snippet["content"], group["content"]):
                group["lines"].extend(snippet["lines"])
                if len(snippet["content"]) > len(group["content"]):
                    group["content"] = snippet["content"]
                placed = True
                break
        if not placed:
            groups.append({"content": snippet["content"], "lines": list(snippet["lines"])})
    return groups


def _retitle_line(raw_title_line: str, new_title: str) -> str:
    match = _IDEA_LINE.match(raw_title_line)
    if not match:
        return raw_title_line
    return f"{match.group('indent')}{new_title}"


def _next_idea_number(ideas: list[dict[str, Any]]) -> int:
    numbers = [int(idea["id"].split("-")[1]) for idea in ideas if idea["id"].startswith("idea-")]
    return max(numbers, default=0)


def _render_split_idea(
    *,
    idea_id: str,
    title: str,
    source_idea: dict[str, Any],
    extra: dict[str, Any],
) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    lines = [
        f"- **[{idea_id}]** {title}",
        "  - **Score:** 0 (not yet ranked - run `/dex-backlog` to calculate)",
        f"  - **Category:** {source_idea.get('category') or 'system'}",
        f"  - **Captured:** {source_idea.get('captured') or today}",
        f"  - **Source:** {source_idea.get('source') or 'Session Learning Synthesis'}",
        f"  - **Description:** {extra['content']}",
    ]
    lines.extend(extra.get("lines") or [])
    lines.append("")
    return "\n".join(lines) + "\n"


def _insert_low_priority(content: str, blocks: list[str]) -> str:
    insertion = "".join(blocks)
    match = re.search(
        r"(### 💡 (?:Low|Lower) Priority \(Score: <60\)\s*\n(?:\s*\*[^*]+\*\s*\n)?)",
        content,
    )
    if match:
        return content[: match.end()] + "\n" + insertion + content[match.end() :]
    fallback = re.search(r"(## Archive|## Summary|---\s*$)", content)
    if fallback:
        return content[: fallback.start()] + insertion + "\n" + content[fallback.start() :]
    return content + "\n" + insertion


def _write_receipt(vault_root: Path, result: dict[str, Any]) -> None:
    path = vault_root / RECEIPT_RELATIVE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": RECEIPT_VERSION,
            "last_run": datetime.now(timezone.utc).isoformat(),
            "retitled": result.get("retitled", 0),
            "split": result.get("split", 0),
            "unchanged": result.get("unchanged", True),
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--vault", default="")
    args, _unknown = parser.parse_known_args(argv)
    vault = Path(args.vault) if args.vault else Path(os.environ.get("VAULT_PATH") or os.getcwd())
    try:
        backfill_vault(vault)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
