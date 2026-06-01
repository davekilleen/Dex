#!/usr/bin/env python3
"""Enforce coverage gates for total and touched Python files."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def normalize_path(path: str, root: Path) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(root.resolve())
        except ValueError:
            p = Path(path)
    return p.as_posix()


def added_line_numbers(merge_base: str, file_path: str) -> set[int]:
    """Return the new-file line numbers ADDED by this PR for file_path."""
    try:
        diff = run(["git", "diff", "--unified=0", f"{merge_base}...HEAD", "--", file_path])
    except subprocess.CalledProcessError:
        return set()
    added: set[int] = set()
    new_lineno = 0
    for line in diff.splitlines():
        if line.startswith("@@"):
            # @@ -old,cnt +new,cnt @@
            seg = line.split("+", 1)
            if len(seg) < 2:
                continue
            try:
                new_lineno = int(seg[1].split(" ", 1)[0].split(",", 1)[0])
            except ValueError:
                continue
        elif line.startswith(("+++", "---")):
            continue
        elif line.startswith("+"):
            added.add(new_lineno)
            new_lineno += 1
        # '-' (old-file) and '\' (no-newline) lines do not advance the new-file counter
    return added


def main() -> int:
    coverage_path = Path(os.environ.get("COVERAGE_JSON", "coverage.json"))
    min_total = float(os.environ.get("COVERAGE_MIN_TOTAL", "15"))
    min_touched = float(os.environ.get("COVERAGE_MIN_TOUCHED", "10"))
    base_ref = os.environ.get("GITHUB_BASE_REF", "main")
    cwd = Path.cwd()

    if not coverage_path.exists():
        print(f"Coverage file not found: {coverage_path}", file=sys.stderr)
        return 1

    data = json.loads(coverage_path.read_text(encoding="utf-8"))
    total = float(data.get("totals", {}).get("percent_covered", 0.0))
    if total < min_total:
        print(f"Total coverage {total:.2f}% is below required {min_total:.2f}%.", file=sys.stderr)
        return 1

    try:
        run(["git", "fetch", "origin", base_ref, "--depth=1"])
    except subprocess.CalledProcessError:
        pass

    merge_base = run(["git", "merge-base", "HEAD", f"origin/{base_ref}"])
    # --diff-filter=ACMR drops deleted (D) files: a deleted module is absent from
    # coverage.json and would otherwise score 0% and fail the gate. Removing code
    # must never fail a coverage gate.
    changed = run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{merge_base}...HEAD"]
    ).splitlines()
    touched = [
        f
        for f in changed
        if f.startswith("core/")
        and f.endswith(".py")
        and not f.startswith("core/tests/")
        and not f.startswith("core/mcp/tests/")
        # Guard against any rename/edge-case path that no longer exists on disk.
        and Path(f).is_file()
    ]

    if not touched:
        print(f"Coverage gate passed. Total coverage: {total:.2f}% (no touched source files).")
        return 0

    # Patch coverage: judge each touched file on the lines it CHANGED, not its
    # whole-file coverage. Editing a line in a historically-untested file no
    # longer inherits that file's pre-existing debt.
    line_coverage: dict[str, tuple[set[int], set[int]]] = {}
    for raw_path, payload in data.get("files", {}).items():
        key = normalize_path(raw_path, cwd)
        executed = set(payload.get("executed_lines", []) or [])
        missing = set(payload.get("missing_lines", []) or [])
        line_coverage[key] = (executed, missing)

    failures: list[str] = []
    for file_path in touched:
        added = added_line_numbers(merge_base, file_path)
        executed, missing = line_coverage.get(file_path, (set(), set()))
        coverable = added & (executed | missing)
        if not coverable:
            # No new executable lines (comments, blanks, docstrings) — nothing to score.
            continue
        covered = added & executed
        pct = len(covered) / len(coverable) * 100.0
        if pct < min_touched:
            failures.append(
                f"{file_path}: {pct:.2f}% of changed lines covered "
                f"({len(covered)}/{len(coverable)}, required {min_touched:.2f}%)"
            )

    if failures:
        print("Touched-file coverage gate failed:", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        return 1

    print(f"Coverage gate passed. Total: {total:.2f}% | touched-file minimum: {min_touched:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
