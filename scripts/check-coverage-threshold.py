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
    changed = run(["git", "diff", "--name-only", f"{merge_base}...HEAD"]).splitlines()
    touched = [
        f
        for f in changed
        if f.startswith("core/")
        and f.endswith(".py")
        and not f.startswith("core/tests/")
        and not f.startswith("core/mcp/tests/")
    ]

    if not touched:
        print(f"Coverage gate passed. Total coverage: {total:.2f}% (no touched source files).")
        return 0

    file_coverage: dict[str, float] = {}
    for raw_path, payload in data.get("files", {}).items():
        key = normalize_path(raw_path, cwd)
        pct = float(payload.get("summary", {}).get("percent_covered", 0.0))
        file_coverage[key] = pct

    failures: list[str] = []
    for file_path in touched:
        pct = file_coverage.get(file_path, 0.0)
        if pct < min_touched:
            failures.append(f"{file_path}: {pct:.2f}% (required {min_touched:.2f}%)")

    if failures:
        print("Touched-file coverage gate failed:", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        return 1

    print(f"Coverage gate passed. Total: {total:.2f}% | touched-file minimum: {min_touched:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
