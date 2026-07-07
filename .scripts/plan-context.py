#!/usr/bin/env python3
"""Deterministic planning context gatherer for daily/weekly planning skills.

This script is the gather phase of the Agentic OS pattern: it collects local
planning signals without using token-heavy MCP calls. The AI skill then uses the
structured output for judgment and framing.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _parse_tasks(text: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- [ ]") and not stripped.startswith("- [x]"):
            continue
        title = re.sub(r"^-[ ]\[[ xX]\]\s*", "", stripped)
        tasks.append({"title": title, "completed": "[x]" in stripped})
    return tasks


def _parse_priorities(text: str) -> list[str]:
    priorities: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("1.") or stripped.startswith("2.") or stripped.startswith("3.") or stripped.startswith("4.") or stripped.startswith("5."):
            priorities.append(stripped[2:].strip())
    return priorities


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if isinstance(data, dict):
        for key in ("records", "data", "items", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return []
    if isinstance(data, list):
        return data
    return []


def build_context(vault: Path | str | None = None, mode: str = "weekly") -> dict[str, Any]:
    vault_path = Path(vault or Path(__file__).resolve().parent.parent)
    planning = vault_path / "Planning"
    sf_data = vault_path / ".scripts" / "salesforce-data"

    tasks_text = _read_text(planning / "Tasks.md")
    priorities_text = _read_text(planning / "Week_Priorities.md")
    goals_text = _read_text(planning / "Quarter_Goals.md")

    pipeline = []
    opp_path = sf_data / "opportunities.json"
    opps = _load_records(opp_path)
    pipeline = [
        {
            "name": item.get("Name"),
            "stage": item.get("StageName"),
            "amount": item.get("Amount"),
            "close_date": item.get("CloseDate"),
        }
        for item in opps[:10]
        if not item.get("IsClosed")
    ]

    service_cases = []
    case_path = sf_data / "case_snapshot.json"
    cases = _load_records(case_path)
    service_cases = [
        {
            "case_number": item.get("CaseNumber"),
            "subject": item.get("Subject"),
            "status": item.get("Status"),
            "priority": item.get("Priority"),
        }
        for item in cases[:10]
    ]

    return {
        "mode": mode,
        "tasks": _parse_tasks(tasks_text)[:8],
        "top_priorities": _parse_priorities(priorities_text)[:5],
        "quarter_goals": [line.strip() for line in goals_text.splitlines() if line.strip().startswith("- ")][:5],
        "pipeline": pipeline,
        "service_cases": service_cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Gather local planning context for Dex planning skills")
    parser.add_argument("--mode", default="weekly", choices=["daily", "weekly"])
    parser.add_argument("--vault", default=None)
    args = parser.parse_args()

    context = build_context(args.vault, mode=args.mode)
    print(json.dumps(context, indent=2))
    return 0


if __name__ == "__main__":
    main()
