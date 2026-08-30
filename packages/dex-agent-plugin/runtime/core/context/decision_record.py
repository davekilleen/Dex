#!/usr/bin/env python3
"""Read-only lookup of a vault's own decision records.

The packed connector box asks this module what was decided about a topic and
returns the choice plus the file it came from. It never writes, never invents a
decision, and never reads meetings or other notes as a substitute.
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

from core.paths import PROJECTS_DIR, RESOURCES_DIR, resolve_for_vault

HEADING = re.compile(r"^##\s+(.+?)\s*$")
DATED_HEADING = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s+[—–-]\s+(?P<title>.+)$"
)
DECISION_LINE = re.compile(
    r"^\*\*Decision:\*\*\s*(.+?)\s*$",
    re.IGNORECASE,
)
TOPIC_WRAPPER = re.compile(
    r"^(?:what(?:\s+was)?\s+)?(?:was\s+)?decided(?:\s+about)?\s+",
    re.IGNORECASE,
)
TOKEN = re.compile(r"[a-z0-9]{3,}")
STOPWORDS = {
    "about",
    "and",
    "decided",
    "decision",
    "for",
    "from",
    "the",
    "this",
    "that",
    "was",
    "what",
    "with",
}
SKIP_NAMES = {"readme.md"}
MAX_MATCHES = 8


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


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _real_file(root: Path, path: Path) -> Path | None:
    try:
        if path.is_symlink() or not path.is_file() or not _inside(root, path):
            return None
        return path
    except OSError:
        return None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _relative_file(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def _decisions_dir(vault: Path) -> Path:
    return resolve_for_vault(vault, RESOURCES_DIR) / "Decisions"


def _projects_dir(vault: Path) -> Path:
    return resolve_for_vault(vault, PROJECTS_DIR)


def _decision_files(vault: Path) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        real = _real_file(vault, path)
        if real is None or real.name.lower() in SKIP_NAMES:
            return
        try:
            key = str(real.resolve())
        except OSError:
            return
        if key in seen:
            return
        seen.add(key)
        files.append(real)

    decisions_dir = _decisions_dir(vault)
    try:
        if decisions_dir.is_dir() and not decisions_dir.is_symlink() and _inside(
            vault, decisions_dir
        ):
            for path in sorted(decisions_dir.rglob("*.md")):
                _add(path)
    except OSError:
        pass

    projects_dir = _projects_dir(vault)
    try:
        if projects_dir.is_dir() and not projects_dir.is_symlink() and _inside(
            vault, projects_dir
        ):
            for path in sorted(projects_dir.rglob("Decisions.md")):
                _add(path)
    except OSError:
        pass
    return files


def _entries(content: str, *, fallback_title: str) -> list[dict[str, str]]:
    lines = content.splitlines()
    starts: list[int] = [
        index for index, line in enumerate(lines) if HEADING.match(line)
    ]
    if not starts:
        body = content.strip()
        if not body:
            return []
        return [
            {
                "title": fallback_title,
                "date": "",
                "decision": _first_decision(body) or _first_sentence(body),
                "body": body,
            }
        ]
    entries: list[dict[str, str]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        heading = HEADING.match(lines[start])
        raw_heading = heading.group(1).strip() if heading else fallback_title
        dated = DATED_HEADING.match(raw_heading)
        title = dated.group("title").strip() if dated else raw_heading
        date = dated.group("date") if dated else ""
        body = "\n".join(lines[start:end]).strip()
        entries.append(
            {
                "title": title,
                "date": date,
                "decision": _first_decision(body) or title,
                "body": body,
            }
        )
    return entries


def _first_decision(body: str) -> str:
    for line in body.splitlines():
        match = DECISION_LINE.match(line.strip())
        if match:
            return match.group(1).strip()
    return ""


def _first_sentence(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def _normalize_topic(topic: Any) -> str:
    if not isinstance(topic, str):
        return ""
    cleaned = TOPIC_WRAPPER.sub("", topic.strip())
    return cleaned.strip(" ?.")


def _tokens(text: str) -> list[str]:
    return [token for token in TOKEN.findall(text.lower()) if token not in STOPWORDS]


def _matches_topic(entry: dict[str, str], topic: str) -> bool:
    haystack = f"{entry.get('title', '')}\n{entry.get('decision', '')}\n{entry.get('body', '')}"
    folded = haystack.lower()
    needle = topic.lower()
    if needle and needle in folded:
        return True
    tokens = _tokens(topic)
    if not tokens:
        return False
    return all(token in folded for token in tokens)


def _empty(topic: str) -> dict[str, Any]:
    return {"found": False, "topic": topic, "matches": []}


def ask_what_was_decided(vault: str | Path | None, topic: Any) -> dict[str, Any]:
    """Return matching decision-record entries for a topic, never raising."""
    query = _normalize_topic(topic)
    empty = _empty(query)
    root = _coerce_root(vault)
    if root is None or not query:
        return empty
    matches: list[dict[str, str]] = []
    for path in _decision_files(root):
        content = _read_text(path)
        if not content:
            continue
        relative = _relative_file(root, path)
        for entry in _entries(content, fallback_title=path.stem.replace("_", " ")):
            if not _matches_topic(entry, query):
                continue
            matches.append(
                {
                    "title": entry["title"],
                    "date": entry["date"],
                    "decision": entry["decision"],
                    "file": relative,
                }
            )
    matches.sort(key=lambda row: (row.get("date") or "", row.get("title") or ""), reverse=True)
    empty["found"] = bool(matches)
    empty["matches"] = matches[:MAX_MATCHES]
    return empty


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ask a Dex folder what was decided")
    parser.add_argument("--vault", required=True, help="Dex folder root")
    parser.add_argument("--topic", required=True, help="Topic to look up")
    parser.add_argument("--format", choices=("json", "text"), default="text")
    args = parser.parse_args(argv)
    payload = ask_what_was_decided(args.vault, args.topic)
    if args.format == "json":
        json.dump(payload, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    if not payload["found"]:
        sys.stdout.write("No matching decision record.\n")
        return 0
    for match in payload["matches"]:
        decision = str(match.get("decision") or "").strip()
        source = str(match.get("file") or "").strip()
        sys.stdout.write(f"{decision}\n")
        sys.stdout.write(f"File: {source}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
