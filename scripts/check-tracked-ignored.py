#!/usr/bin/env python3
"""Validate Dex's closed tracked-despite-ignored baseline without mutating Git."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.utils.tracked_ignored import (
    PolicyRow,
    TrackedIgnoredError,
    load_exact_policy,
    query_tracked_ignored,
)


def load_policy(path: Path) -> tuple[PolicyRow, ...]:
    """Compatibility wrapper for checker callers and focused tests."""
    return load_exact_policy(path).rows


def check(repo: Path, policy_path: Path) -> dict[str, object]:
    rows = load_policy(policy_path)
    actual = set(query_tracked_ignored(repo))
    policy_paths = {row.path for row in rows}
    expected_tracked = {row.path for row in rows if row.classification != "local-only-must-be-untracked"}
    local_only = {row.path for row in rows if row.classification == "local-only-must-be-untracked"}
    errors: list[dict[str, object]] = []
    if unknown := sorted(actual - policy_paths):
        errors.append({"code": "unknown-tracked-ignored", "paths": unknown})
    if stale := sorted(expected_tracked - actual):
        errors.append({"code": "stale-policy-row", "paths": stale})
    if still_tracked := sorted(actual & local_only):
        errors.append({"code": "local-only-still-tracked", "paths": still_tracked})
    return {
        "ok": not errors,
        "policy_rows": len(rows),
        "expected_tracked": len(expected_tracked),
        "actual_tracked_ignored": len(actual),
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path(__file__).with_name("tracked-ignored-policy.yaml"),
    )
    args = parser.parse_args(argv)
    try:
        result = check(args.repo.resolve(), args.policy.resolve())
    except TrackedIgnoredError as error:
        result = {"ok": False, "errors": [{"code": "check-failed", "detail": str(error)}]}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
