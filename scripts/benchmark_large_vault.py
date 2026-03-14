#!/usr/bin/env python3
"""Benchmark core file traversal operations on a synthetic large vault."""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

# Ensure `core` package is importable when executing from scripts/.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.paths import (
    ARCHIVES_DIR,
    COMPANIES_DIR,
    DAILY_PLANS_DIR,
    IDEAS_DIR,
    INTEL_DIR,
    LEARNINGS_DIR,
    MEETINGS_DIR,
    PEOPLE_DIR,
    PROJECTS_DIR,
    QUARTER_GOALS_DIR,
    SESSIONS_DIR,
    SYSTEM_DIR,
    TASKS_DIR,
    TASKS_FILE,
    VAULT_ROOT,
    WEEK_PRIORITIES_DIR,
)


def _rel(path: Path) -> Path:
    return path.relative_to(VAULT_ROOT)


MEETINGS_REL = _rel(MEETINGS_DIR)
IDEAS_REL = _rel(IDEAS_DIR)
DAILY_PLANS_REL = _rel(DAILY_PLANS_DIR)
QUARTER_GOALS_REL = _rel(QUARTER_GOALS_DIR)
WEEK_PRIORITIES_REL = _rel(WEEK_PRIORITIES_DIR)
TASKS_DIR_REL = _rel(TASKS_DIR)
TASKS_FILE_REL = _rel(TASKS_FILE)
PROJECTS_REL = _rel(PROJECTS_DIR)
PEOPLE_INTERNAL_REL = _rel(PEOPLE_DIR / "Internal")
PEOPLE_EXTERNAL_REL = _rel(PEOPLE_DIR / "External")
COMPANIES_REL = _rel(COMPANIES_DIR)
EVIDENCE_REL = _rel(SESSIONS_DIR.parent.parent / "Evidence")
MEETING_INTEL_REL = _rel(INTEL_DIR / "Meeting_Intel")
LEARNINGS_REL = _rel(LEARNINGS_DIR)
ARCHIVES_REL = _rel(ARCHIVES_DIR)
SYSTEM_REL = _rel(SYSTEM_DIR)

PARA_DIRS = [
    MEETINGS_REL,
    IDEAS_REL,
    DAILY_PLANS_REL,
    QUARTER_GOALS_REL,
    WEEK_PRIORITIES_REL,
    TASKS_DIR_REL,
    PROJECTS_REL,
    PEOPLE_INTERNAL_REL,
    PEOPLE_EXTERNAL_REL,
    COMPANIES_REL,
    EVIDENCE_REL,
    MEETING_INTEL_REL,
    LEARNINGS_REL,
    ARCHIVES_REL,
    SYSTEM_REL,
]


def create_synthetic_vault(root: Path, file_count: int) -> None:
    for d in PARA_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / TASKS_FILE_REL).write_text("# Tasks\n", encoding="utf-8")

    for idx in range(file_count):
        if idx % 5 == 0:
            path = root / MEETINGS_REL / f"meeting-{idx:05d}.md"
            payload = f"# Meeting {idx}\n- follow-up task task-{idx:05d}\n"
        elif idx % 5 == 1:
            path = root / PROJECTS_REL / f"project-{idx:05d}.md"
            payload = f"# Project {idx}\nReference: {TASKS_FILE_REL.as_posix()}\n"
        elif idx % 5 == 2:
            path = root / PEOPLE_INTERNAL_REL / f"person-{idx:05d}.md"
            payload = f"# Person {idx}\n- [ ] action item {idx}\n"
        elif idx % 5 == 3:
            path = root / LEARNINGS_REL / f"note-{idx:05d}.md"
            payload = f"# Learning {idx}\nkeywords: testing, automation\n"
        else:
            path = root / ARCHIVES_REL / f"archive-{idx:05d}.md"
            payload = f"# Archived {idx}\n"
        path.write_text(payload, encoding="utf-8")


def benchmark_scan(root: Path) -> tuple[float, int]:
    start = time.perf_counter()
    files = list(root.rglob("*.md"))
    # Simulate lightweight parse work used by scripts/tools.
    _ = sum(1 for path in files if "task-" in path.read_text(encoding="utf-8", errors="ignore"))
    elapsed = time.perf_counter() - start
    return elapsed, len(files)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark large-vault operations")
    parser.add_argument("--files", type=int, default=2000, help="Number of synthetic markdown files")
    parser.add_argument("--budget-seconds", type=float, default=5.0, help="Fail if elapsed > budget")
    parser.add_argument("--vault-root", default="", help="Optional existing directory for synthetic vault")
    args = parser.parse_args()

    if args.vault_root:
        vault_root = Path(args.vault_root).resolve()
        vault_root.mkdir(parents=True, exist_ok=True)
        create_synthetic_vault(vault_root, args.files)
        elapsed, scanned = benchmark_scan(vault_root)
    else:
        with tempfile.TemporaryDirectory(prefix="dex-large-vault-") as tmp:
            vault_root = Path(tmp)
            create_synthetic_vault(vault_root, args.files)
            elapsed, scanned = benchmark_scan(vault_root)

    print(f"large-vault benchmark: scanned={scanned} files elapsed={elapsed:.3f}s budget={args.budget_seconds:.3f}s")
    if elapsed > args.budget_seconds:
        print("Performance budget exceeded.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
