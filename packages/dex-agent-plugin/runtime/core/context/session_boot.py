#!/usr/bin/env python3
"""Portable session-start facts shared by MCP and Claude Code.

``boot_today`` is deliberately a pure, read-only payload.  Claude Code calls
the module from its SessionStart wrapper; other harnesses call the Work MCP
tool.  Missing, unreadable, or malformed vault files produce an empty section
rather than an exception or invented context.
"""

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

from core.paths import (
    PILLARS_FILE,
    QUARTER_GOALS_FILE,
    TASKS_FILE,
    WEEK_PRIORITIES_FILE,
    resolve_for_vault,
)

try:
    import yaml
except ImportError:  # pragma: no cover - exercised in minimal installs
    yaml = None  # type: ignore[assignment]


PILLAR_LIMIT = 5
URGENT_LIMIT = 3
GOAL_LIMIT = 10
GOAL_HEADER = re.compile(r"^###\s+[0-9]+\.\s+")
PROGRESS_LINE = re.compile(r"^\*\*Progress:\*\*")
WEEK_HEADING = re.compile(r"^##\s+(?:🎯\s+)?(?:Top 3 )?This Week\s*$")
UNCHECKED_TASK = re.compile(r"^- \[ \] ")
URGENT_HINT = re.compile(r"p0|urgent|today|overdue", re.IGNORECASE)
TEMPLATE_GOAL = "[Goal 1 Title]"


def _coerce_root(vault: str | Path | None) -> Path | None:
    """Return a usable vault path, or ``None`` for malformed input."""
    if vault is None:
        return None
    try:
        root = Path(vault).expanduser()
    except (TypeError, ValueError, OSError):
        return None
    try:
        if not root.is_dir():
            return None
    except OSError:
        return None
    return root


def _today_label(today: date | None = None) -> str:
    try:
        stamp = today or date.today()
        return stamp.strftime("%A, %B %d, %Y")
    except (AttributeError, OverflowError, ValueError):
        return date.today().strftime("%A, %B %d, %Y")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _load_pillars(vault: Path) -> list[dict[str, str]]:
    path = resolve_for_vault(vault, PILLARS_FILE)
    if not path.is_file():
        return []
    text = _read_text(path)
    if not text:
        return []
    if yaml is not None:
        try:
            data = yaml.safe_load(text) or {}
        except Exception:
            data = {}
        rows = data.get("pillars") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        pillars: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            description = row.get("description")
            if not isinstance(name, str):
                name = "" if name is None else str(name)
            if not isinstance(description, str):
                description = "" if description is None else str(description)
            name = name.strip().strip('"')
            description = description.strip().strip('"')
            if name:
                pillars.append({"name": name, "description": description})
            if len(pillars) >= PILLAR_LIMIT:
                break
        return pillars

    # Minimal fallback for installations without PyYAML.  It intentionally
    # understands only the seeded consecutive id/name/description shape.
    pillars: list[dict[str, str]] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not re.match(r"^\s*- id:\s*", line):
            continue
        name = ""
        description = ""
        if index + 1 < len(lines):
            name = re.sub(r'^\s*name:\s*"?', "", lines[index + 1]).rstrip('"').strip()
        if index + 2 < len(lines):
            description = re.sub(
                r'^\s*description:\s*"?', "", lines[index + 2]
            ).rstrip('"').strip()
        if name:
            pillars.append({"name": name, "description": description})
        if len(pillars) >= PILLAR_LIMIT:
            break
    return pillars


def _load_quarter_goals(vault: Path) -> list[dict[str, str]]:
    path = resolve_for_vault(vault, QUARTER_GOALS_FILE)
    if not path.is_file():
        return []
    text = _read_text(path)
    if not text or TEMPLATE_GOAL in text:
        return []
    goals: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        if GOAL_HEADER.match(line):
            if len(goals) >= GOAL_LIMIT:
                break
            current = {"title": line.strip(), "progress": ""}
            goals.append(current)
            continue
        if current is not None and PROGRESS_LINE.match(line):
            current["progress"] = line.strip()
        if line.strip() == "---":
            current = None
    return goals


def _load_week_priorities(vault: Path) -> list[str]:
    path = resolve_for_vault(vault, WEEK_PRIORITIES_FILE)
    if not path.is_file():
        return []
    lines = _read_text(path).splitlines()
    in_week = False
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if WEEK_HEADING.match(line):
            in_week = True
            continue
        if not in_week:
            continue
        if stripped == "---" or (stripped.startswith("##") and not WEEK_HEADING.match(line)):
            break
        if stripped:
            items.append(line.rstrip())
    return items


def _load_urgent_tasks(vault: Path) -> list[str]:
    path = resolve_for_vault(vault, TASKS_FILE)
    if not path.is_file():
        return []
    urgent: list[str] = []
    for line in _read_text(path).splitlines():
        if not UNCHECKED_TASK.match(line) or not URGENT_HINT.search(line):
            continue
        urgent.append(line.rstrip())
        if len(urgent) >= URGENT_LIMIT:
            break
    return urgent


def build_session_boot(
    vault: str | Path | None,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Return read-only session facts for any harness.

    A malformed or missing vault still yields a stable, serialisable payload;
    this keeps a context helper from breaking an otherwise usable session.
    """
    root = _coerce_root(vault)
    pillars = _load_pillars(root) if root is not None else []
    goals = _load_quarter_goals(root) if root is not None else []
    priorities = _load_week_priorities(root) if root is not None else []
    urgent = _load_urgent_tasks(root) if root is not None else []
    payload: dict[str, Any] = {
        "today": _today_label(today),
        "pillars": pillars,
        "quarter_goals": goals,
        "week_priorities": priorities,
        "urgent_tasks": urgent,
    }
    payload["injected_text"] = format_session_boot_text(payload, include_today=False)
    return payload


def format_session_boot_text(
    payload: dict[str, Any] | None,
    *,
    include_today: bool = False,
) -> str:
    """Render the section text used by SessionStart, tolerating bad rows."""
    if not isinstance(payload, dict):
        return ""
    blocks: list[str] = []
    if include_today:
        blocks.append(f"📅 Today: {str(payload.get('today') or '').strip()}")

    pillars = payload.get("pillars")
    if isinstance(pillars, list):
        lines = ["--- Strategic Pillars ---"]
        for pillar in pillars:
            if not isinstance(pillar, dict):
                continue
            name = str(pillar.get("name") or "").strip()
            description = str(pillar.get("description") or "").strip()
            if not name:
                continue
            lines.append(f"• {name} — {description}" if description else f"• {name}")
        if len(lines) > 1:
            lines.append("---")
            blocks.append("\n".join(lines))

    goals = payload.get("quarter_goals")
    if isinstance(goals, list):
        lines = ["--- Quarter Goals ---"]
        for goal in goals:
            if not isinstance(goal, dict):
                continue
            title = str(goal.get("title") or "").strip()
            progress = str(goal.get("progress") or "").strip()
            if title:
                lines.append(title)
            if progress:
                lines.append(progress)
        if len(lines) > 1:
            lines.append("---")
            blocks.append("\n".join(lines))

    priorities = payload.get("week_priorities")
    if isinstance(priorities, list):
        values = [str(item).rstrip() for item in priorities if str(item).strip()]
        if values:
            blocks.append("\n".join(["--- Weekly Priorities ---", *values, "---"]))

    urgent = payload.get("urgent_tasks")
    if isinstance(urgent, list):
        values = [str(item).rstrip() for item in urgent if str(item).strip()]
        if values:
            blocks.append("\n".join(["--- Urgent Tasks ---", *values, "---"]))
    return "\n\n".join(blocks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print Dex session boot context")
    parser.add_argument("--vault", required=True, help="Vault root")
    parser.add_argument("--format", choices=("json", "text", "hook-text"), default="hook-text")
    args = parser.parse_args(argv)
    payload = build_session_boot(args.vault)
    if args.format == "json":
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    text = format_session_boot_text(payload, include_today=args.format == "text")
    if text:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
