"""Closed tracked-ignore policy and hardened read-only Git inspection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

TRANSITION_RELATIVE = Path("System/.local-only-preservation-transition.json")
TRANSITION_PHASES = {"bootstrap-v1", "untrack-v1"}
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
LOCAL_ONLY_PATHS = tuple(path for path, kind in APPROVED_ROWS if kind == "local-only-must-be-untracked")
SAFE_PATH = re.compile(r"^[^\x00-\x1f\\]+$")


class TrackedIgnoredError(ValueError):
    """The closed policy or tracked-ignore query could not be verified."""


@dataclass(frozen=True)
class PolicyRow:
    path: str
    classification: str


@dataclass(frozen=True)
class ExactPolicy:
    rows: tuple[PolicyRow, ...]
    sha256: str

    @property
    def paths(self) -> set[str]:
        return {row.path for row in self.rows}

    @property
    def local_only_paths(self) -> set[str]:
        return {row.path for row in self.rows if row.classification == "local-only-must-be-untracked"}


@dataclass(frozen=True)
class PreservationTransition:
    phase: str
    release_version: str


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise TrackedIgnoredError(f"duplicate local-only preservation transition key: {key}")
        payload[key] = value
    return payload


def load_transition_pair(transition_path: Path, package_path: Path) -> PreservationTransition:
    try:
        payload = json.loads(
            transition_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
        package = json.loads(
            package_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (OSError, json.JSONDecodeError, TrackedIgnoredError) as error:
        if isinstance(error, TrackedIgnoredError):
            raise
        raise TrackedIgnoredError(f"could not read local-only preservation transition: {error}") from error
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "phase", "release_version"}:
        raise TrackedIgnoredError("local-only preservation transition has unexpected fields")
    if payload.get("schema_version") != 1 or payload.get("phase") not in TRANSITION_PHASES:
        raise TrackedIgnoredError("local-only preservation transition schema or phase is unsupported")
    version = payload.get("release_version")
    if not isinstance(version, str) or not isinstance(package, dict) or package.get("version") != version:
        raise TrackedIgnoredError("local-only preservation transition version does not match package metadata")
    return PreservationTransition(payload["phase"], version)


def load_transition(repo: Path) -> PreservationTransition:
    return load_transition_pair(repo / TRANSITION_RELATIVE, repo / "package.json")


def _safe_repo_path(value: str) -> bool:
    if not value or not SAFE_PATH.fullmatch(value):
        return False
    candidate = PurePosixPath(value)
    return (
        not candidate.is_absolute() and candidate.parts and all(part not in {"", ".", ".."} for part in candidate.parts)
    )


def load_exact_policy(path: Path) -> ExactPolicy:
    try:
        policy_bytes = path.read_bytes()
        payload = yaml.safe_load(policy_bytes)
    except (OSError, yaml.YAMLError) as error:
        raise TrackedIgnoredError(f"could not read tracked-ignore policy: {error}") from error
    if not isinstance(payload, dict):
        raise TrackedIgnoredError("tracked-ignore policy root must be a mapping")
    if set(payload) != {"schema_version", "baseline_count", "paths"}:
        raise TrackedIgnoredError("tracked-ignore policy must contain only schema_version, baseline_count, and paths")
    if payload.get("schema_version") != 1:
        raise TrackedIgnoredError("tracked-ignore policy must use schema_version 1")
    values = payload.get("paths")
    if payload.get("baseline_count") != len(APPROVED_ROWS) or not isinstance(values, list):
        raise TrackedIgnoredError("tracked-ignore policy must contain the exact 27-row baseline")

    rows: list[PolicyRow] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict) or set(value) != {"path", "classification"}:
            raise TrackedIgnoredError("each tracked-ignore row must contain only path and classification")
        row_path = value.get("path")
        classification = value.get("classification")
        if not isinstance(row_path, str) or not _safe_repo_path(row_path):
            raise TrackedIgnoredError(f"unsafe tracked-ignore policy path: {row_path!r}")
        if row_path in seen:
            raise TrackedIgnoredError(f"duplicate tracked-ignore policy row: {row_path}")
        if not isinstance(classification, str):
            raise TrackedIgnoredError(f"invalid tracked-ignore classification for {row_path}")
        seen.add(row_path)
        rows.append(PolicyRow(row_path, classification))
    if tuple((row.path, row.classification) for row in rows) != APPROVED_ROWS:
        raise TrackedIgnoredError("tracked-ignore policy differs from the exact approved 27-row baseline")
    return ExactPolicy(tuple(rows), hashlib.sha256(policy_bytes).hexdigest())


def sanitized_git_env() -> dict[str, str]:
    environment = os.environ.copy()
    unsafe_exact = {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_PARAMETERS",
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


def git_executable() -> str:
    executable = shutil.which("git")
    if not executable:
        raise TrackedIgnoredError("git is unavailable; tracked-ignore state is UNKNOWN")
    return executable


def query_tracked_ignored(repo: Path) -> tuple[str, ...]:
    try:
        result = subprocess.run(
            [
                git_executable(),
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                f"core.excludesFile={os.devnull}",
                "-C",
                os.fspath(repo),
                "ls-files",
                "-ci",
                "--exclude-standard",
                "-z",
            ],
            capture_output=True,
            env=sanitized_git_env(),
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise TrackedIgnoredError(f"could not inspect tracked-ignore state: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise TrackedIgnoredError(detail or "not a Git worktree; tracked-ignore state is UNKNOWN")
    return tuple(sorted(part.decode("utf-8", "surrogateescape") for part in result.stdout.split(b"\0") if part))
