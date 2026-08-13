#!/usr/bin/env python3
"""Session boot payload shared by the SessionStart hook and Work MCP.

``boot_today`` is the harness-neutral name. Claude Code still auto-fires
this at session start; Cursor, ChatGPT, and Codex call the MCP tool.
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

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

PILLAR_LIMIT = 5
URGENT_LIMIT = 3
GOAL_HEADER = re.compile(r"^###\s+[0-9]\.\s+")
PROGRESS_LINE = re.compile(r"^\*\*Progress:\*\*")
WEEK_HEADING = re.compile(r"^##\s+(?:🎯\s+)?(?:Top 3 )?This Week")
UNCHECKED_TASK = re.compile(r"^- \[ \] ")
URGENT_HINT = re.compile(r"p0|urgent|today|overdue", re.IGNORECASE)
TEMPLATE_GOAL = "[Goal 1 Title]"


def _today_label(today: date | None = None) -> str:
    stamp = today or date.today()
    return stamp.strftime("%A, %B %d, %Y")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _load_pillars(vault: Path) -> list[dict[str, str]]:
    path = vault / "System" / "pillars.yaml"
    if not path.is_file():
        return []
    text = _read_text(path)
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
            name = str(row.get("name") or "").strip().strip('"')
            description = str(row.get("description") or "").strip().strip('"')
            if name:
                pillars.append({"name": name, "description": description})
            if len(pillars) >= PILLAR_LIMIT:
                break
        return pillars
    # Fallback when PyYAML is missing: same consecutive id/name/description
    # shape the historical awk extractor expected.
    pillars = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not re.match(r"^  - id:", line):
            continue
        name = ""
        description = ""
        if index + 1 < len(lines):
            name = re.sub(r'^\s*name:\s*"?', "", lines[index + 1]).rstrip('"')
        if index + 2 < len(lines):
            description = re.sub(
                r'^\s*description:\s*"?', "", lines[index + 2]
            ).rstrip('"')
        if name:
            pillars.append({"name": name, "description": description})
        if len(pillars) >= PILLAR_LIMIT:
            break
    return pillars


def _load_quarter_goals(vault: Path) -> list[dict[str, str]]:
    path = vault / "01-Quarter_Goals" / "Quarter_Goals.md"
    if not path.is_file():
        return []
    text = _read_text(path)
    if TEMPLATE_GOAL in text:
        return []
    goals: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        if GOAL_HEADER.match(line):
            current = {"title": line.strip(), "progress": ""}
            goals.append(current)
            continue
        if current is not None and PROGRESS_LINE.match(line):
            current["progress"] = line.strip()
            current = None
        if line.strip() == "---" and current is not None:
            current = None
    return goals[:10]


def _load_week_priorities(vault: Path) -> list[str]:
    path = vault / "02-Week_Priorities" / "Week_Priorities.md"
    if not path.is_file():
        return []
    lines = _read_text(path).splitlines()
    in_week = False
    items: list[str] = []
    for line in lines:
        if WEEK_HEADING.match(line):
            in_week = True
            continue
        if in_week and line.strip() == "---":
            break
        if in_week and line.strip() and not line.startswith("##"):
            items.append(line.rstrip())
    return items


def _load_urgent_tasks(vault: Path) -> list[str]:
    path = vault / "03-Tasks" / "Tasks.md"
    if not path.is_file():
        return []
    urgent: list[str] = []
    for line in _read_text(path).splitlines():
        if not UNCHECKED_TASK.match(line):
            continue
        if not URGENT_HINT.search(line):
            continue
        urgent.append(line.rstrip())
        if len(urgent) >= URGENT_LIMIT:
            break
    return urgent


def build_session_boot(
    vault: str | Path,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Return the session-boot facts any harness can call for.

    Keys match the four sections SessionStart historically injected:
    strategic pillars, quarter goals, week priorities, urgent tasks.
    """
    root = Path(vault)
    pillars = _load_pillars(root)
    goals = _load_quarter_goals(root)
    priorities = _load_week_priorities(root)
    urgent = _load_urgent_tasks(root)
    payload = {
        "today": _today_label(today),
        "pillars": pillars,
        "quarter_goals": goals,
        "week_priorities": priorities,
        "urgent_tasks": urgent,
    }
    payload["injected_text"] = format_session_boot_text(payload, include_today=False)
    return payload


def format_session_boot_text(
    payload: dict[str, Any],
    *,
    include_today: bool = False,
) -> str:
    """Render the same section text the SessionStart hook injects."""
    blocks: list[str] = []
    if include_today:
        blocks.append(f"📅 Today: {payload.get('today', '')}")
    pillars = payload.get("pillars") or []
    if pillars:
        lines = ["--- Strategic Pillars ---"]
        for pillar in pillars:
            name = str(pillar.get("name") or "").strip()
            description = str(pillar.get("description") or "").strip()
            if description:
                lines.append(f"• {name} — {description}")
            else:
                lines.append(f"• {name}")
        lines.append("---")
        blocks.append("\n".join(lines))
    goals = payload.get("quarter_goals") or []
    if goals:
        lines = ["--- Quarter Goals ---"]
        for goal in goals:
            title = str(goal.get("title") or "").strip()
            if title:
                lines.append(title)
            progress = str(goal.get("progress") or "").strip()
            if progress:
                lines.append(progress)
        lines.append("---")
        blocks.append("\n".join(lines))
    priorities = payload.get("week_priorities") or []
    if priorities:
        lines = ["--- Weekly Priorities ---", *priorities, "---"]
        blocks.append("\n".join(lines))
    urgent = payload.get("urgent_tasks") or []
    if urgent:
        lines = ["--- Urgent Tasks ---", *urgent, "---"]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print Dex session boot context")
    parser.add_argument("--vault", required=True, help="Vault root")
    parser.add_argument(
        "--format",
        choices=("json", "text", "hook-text"),
        default="hook-text",
    )
    args = parser.parse_args(argv)
    payload = build_session_boot(args.vault)
    if args.format == "json":
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    include_today = args.format == "text"
    text = format_session_boot_text(payload, include_today=include_today)
    if text:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
