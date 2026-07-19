#!/usr/bin/env python3
"""Validate Dex's closed tracked-despite-ignored baseline without mutating Git."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

ALLOWED_CLASSIFICATIONS = {
    "intentional-seed",
    "release-doc",
    "local-only-must-be-untracked",
}
EXPECTED_CLASSIFICATION_COUNTS = {
    "intentional-seed": 23,
    "release-doc": 1,
    "local-only-must-be-untracked": 3,
}
APPROVED_ROWS = (
    ("00-Inbox/Daily_Plans/README.md", "intentional-seed"),
    ("00-Inbox/Ideas/README.md", "intentional-seed"),
    ("00-Inbox/Meetings/README.md", "intentional-seed"),
    ("00-Inbox/README.md", "intentional-seed"),
    ("01-Quarter_Goals/Quarter_Goals.md", "intentional-seed"),
    ("02-Week_Priorities/Week_Priorities.md", "intentional-seed"),
    ("03-Tasks/Tasks.md", "intentional-seed"),
    ("04-Projects/README.md", "intentional-seed"),
    ("05-Areas/Career/Evidence/README.md", "intentional-seed"),
    ("05-Areas/Companies/README.md", "intentional-seed"),
    ("05-Areas/People/External/README.md", "intentional-seed"),
    ("05-Areas/People/Internal/README.md", "intentional-seed"),
    ("05-Areas/People/README.md", "intentional-seed"),
    ("05-Areas/README.md", "intentional-seed"),
    ("07-Archives/Plans/README.md", "intentional-seed"),
    ("07-Archives/Projects/README.md", "intentional-seed"),
    ("07-Archives/README.md", "intentional-seed"),
    ("07-Archives/Reviews/README.md", "intentional-seed"),
    ("System/Dex_Backlog.md", "intentional-seed"),
    ("System/Session_Learnings/README.md", "intentional-seed"),
    ("System/pillars.yaml", "intentional-seed"),
    ("System/usage_log.md", "intentional-seed"),
    ("System/user-profile.yaml", "intentional-seed"),
    ("System/Beta_Communications/2026-02-04_hardcoded_paths_fix.md", "release-doc"),
    ("System/Session_Learnings/2026-01-29.md", "local-only-must-be-untracked"),
    ("System/Session_Learnings/2026-01-30.md", "local-only-must-be-untracked"),
    ("System/integrations/slack.yaml", "local-only-must-be-untracked"),
)
SAFE_PATH = re.compile(r"^[^\x00-\x1f\\]+$")


class PolicyError(ValueError):
    """The closed policy is malformed or internally inconsistent."""


@dataclass(frozen=True)
class PolicyRow:
    path: str
    classification: str


def load_policy(path: Path) -> tuple[PolicyRow, ...]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise PolicyError(f"could not read tracked-ignore policy: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise PolicyError("tracked-ignore policy must use schema_version 1")
    rows_payload = payload.get("paths")
    if not isinstance(rows_payload, list):
        raise PolicyError("tracked-ignore policy paths must be an array")
    if payload.get("baseline_count") != 27 or len(rows_payload) != 27:
        raise PolicyError("tracked-ignore policy must contain the exact 27-row baseline")

    rows: list[PolicyRow] = []
    seen: set[str] = set()
    counts = {classification: 0 for classification in ALLOWED_CLASSIFICATIONS}
    for value in rows_payload:
        if not isinstance(value, dict) or set(value) != {"path", "classification"}:
            raise PolicyError("each tracked-ignore row must contain only path and classification")
        row_path = value.get("path")
        classification = value.get("classification")
        if not isinstance(row_path, str) or not _safe_repo_path(row_path):
            raise PolicyError(f"unsafe tracked-ignore policy path: {row_path!r}")
        if row_path in seen:
            raise PolicyError(f"duplicate tracked-ignore policy row: {row_path}")
        if classification not in ALLOWED_CLASSIFICATIONS:
            raise PolicyError(f"unknown tracked-ignore classification for {row_path}")
        seen.add(row_path)
        counts[classification] += 1
        rows.append(PolicyRow(row_path, classification))
    if counts != EXPECTED_CLASSIFICATION_COUNTS:
        raise PolicyError(
            "tracked-ignore policy classification counts differ from the approved 23/1/3 baseline"
        )
    if tuple((row.path, row.classification) for row in rows) != APPROVED_ROWS:
        raise PolicyError("tracked-ignore policy differs from the exact approved 27-row baseline")
    return tuple(rows)


def _safe_repo_path(value: str) -> bool:
    if not value or not SAFE_PATH.fullmatch(value):
        return False
    candidate = PurePosixPath(value)
    return not candidate.is_absolute() and candidate.parts and all(
        part not in {"", ".", ".."} for part in candidate.parts
    )


def _git_executable() -> str:
    executable = shutil.which("git")
    if not executable:
        raise RuntimeError("git is unavailable; tracked-ignore state is UNKNOWN")
    return executable


def _sanitized_git_env() -> dict[str, str]:
    environment = os.environ.copy()
    unsafe_exact = {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_OPTIONAL_LOCKS",
        "GIT_WORK_TREE",
    }
    for key in tuple(environment):
        if key in unsafe_exact or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            environment.pop(key, None)
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_LITERAL_PATHSPECS"] = "1"
    return environment


def query_tracked_ignored(repo: Path) -> tuple[str, ...]:
    command = [
        _git_executable(),
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-C",
        os.fspath(repo),
        "ls-files",
        "-ci",
        "--exclude-standard",
        "-z",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            env=_sanitized_git_env(),
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"could not inspect tracked-ignore state: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(detail or "not a Git worktree; tracked-ignore state is UNKNOWN")
    values = result.stdout.decode("utf-8", "surrogateescape").split("\0")
    return tuple(sorted(value for value in values if value))


def check(repo: Path, policy_path: Path) -> dict[str, object]:
    rows = load_policy(policy_path)
    actual = set(query_tracked_ignored(repo))
    policy_paths = {row.path for row in rows}
    expected_tracked = {
        row.path
        for row in rows
        if row.classification != "local-only-must-be-untracked"
    }
    local_only = {
        row.path
        for row in rows
        if row.classification == "local-only-must-be-untracked"
    }
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
    except (PolicyError, RuntimeError) as error:
        result = {"ok": False, "errors": [{"code": "check-failed", "detail": str(error)}]}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
