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

from core.paths import (
    ARCHIVES_DIR,
    AREAS_DIR,
    COMPANIES_DIR,
    DAILY_PLANS_DIR,
    EVIDENCE_DIR,
    IDEAS_DIR,
    INBOX_DIR,
    MEETINGS_DIR,
    PEOPLE_DIR,
    PROJECTS_DIR,
    QUARTER_GOALS_FILE,
    TASKS_FILE,
    VAULT_ROOT,
    WEEK_PRIORITIES_FILE,
)


def _vault_relative(path: Path) -> str:
    return path.relative_to(VAULT_ROOT).as_posix()


TRANSITION_RELATIVE = Path("System/.local-only-preservation-transition.json")
APPROVED_ROWS = (
    (_vault_relative(DAILY_PLANS_DIR / "README.md"), "intentional-seed"),
    (_vault_relative(IDEAS_DIR / "README.md"), "intentional-seed"),
    (_vault_relative(MEETINGS_DIR / "README.md"), "intentional-seed"),
    (_vault_relative(INBOX_DIR / "README.md"), "intentional-seed"),
    (_vault_relative(QUARTER_GOALS_FILE), "intentional-seed"),
    (_vault_relative(WEEK_PRIORITIES_FILE), "intentional-seed"),
    (_vault_relative(TASKS_FILE), "intentional-seed"),
    (_vault_relative(PROJECTS_DIR / "README.md"), "intentional-seed"),
    (_vault_relative(EVIDENCE_DIR / "README.md"), "intentional-seed"),
    (_vault_relative(COMPANIES_DIR / "README.md"), "intentional-seed"),
    (_vault_relative(PEOPLE_DIR / "External" / "README.md"), "intentional-seed"),
    (_vault_relative(PEOPLE_DIR / "Internal" / "README.md"), "intentional-seed"),
    (_vault_relative(PEOPLE_DIR / "README.md"), "intentional-seed"),
    (_vault_relative(AREAS_DIR / "README.md"), "intentional-seed"),
    (_vault_relative(ARCHIVES_DIR / "Plans" / "README.md"), "intentional-seed"),
    (_vault_relative(ARCHIVES_DIR / "Projects" / "README.md"), "intentional-seed"),
    (_vault_relative(ARCHIVES_DIR / "README.md"), "intentional-seed"),
    (_vault_relative(ARCHIVES_DIR / "Reviews" / "README.md"), "intentional-seed"),
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
RETIRED_FOUNDER_PATHS = frozenset(
    {
        "System/Beta_Communications/2026-02-04_hardcoded_paths_fix.md",
        "System/Session_Learnings/2026-01-29.md",
        "System/Session_Learnings/2026-01-30.md",
    }
)
FUTURE_APPROVED_ROWS = tuple(row for row in APPROVED_ROWS if row[0] not in RETIRED_FOUNDER_PATHS)
BASELINE_ROWS = {1: APPROVED_ROWS, 2: FUTURE_APPROVED_ROWS}
LOCAL_ONLY_PATHS = tuple(path for path, kind in APPROVED_ROWS if kind == "local-only-must-be-untracked")
FUTURE_LOCAL_ONLY_PATHS = tuple(
    path for path, kind in FUTURE_APPROVED_ROWS if kind == "local-only-must-be-untracked"
)
BASELINE_LOCAL_ONLY_PATHS = {1: LOCAL_ONLY_PATHS, 2: FUTURE_LOCAL_ONLY_PATHS}
TRANSITION_PHASES = {
    1: {"bootstrap-v1", "untrack-v1"},
    2: {"bootstrap-v2", "untrack-v2"},
}
SAFE_PATH = re.compile(r"^[^\x00-\x1f\\]+$")


class TrackedIgnoredError(ValueError):
    """The closed policy or tracked-ignore query could not be verified."""


@dataclass(frozen=True)
class PolicyRow:
    path: str
    classification: str


@dataclass(frozen=True)
class ExactPolicy:
    baseline_version: int
    rows: tuple[PolicyRow, ...]
    baselines: tuple[tuple[int, tuple[PolicyRow, ...]], ...]
    sha256: str

    @property
    def paths(self) -> set[str]:
        return {row.path for row in self.rows}

    @property
    def local_only_paths(self) -> set[str]:
        return {row.path for row in self.rows if row.classification == "local-only-must-be-untracked"}

    def rows_for(self, baseline_version: int) -> tuple[PolicyRow, ...]:
        try:
            return dict(self.baselines)[baseline_version]
        except KeyError as error:
            raise TrackedIgnoredError(
                f"tracked-ignore policy does not declare baseline version {baseline_version}"
            ) from error


@dataclass(frozen=True)
class PreservationTransition:
    schema_version: int
    baseline_version: int
    phase: str
    release_version: str


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise TrackedIgnoredError(f"duplicate local-only preservation transition key: {key}")
        payload[key] = value
    return payload


def load_transition_metadata(transition_path: Path) -> PreservationTransition:
    try:
        payload = json.loads(
            transition_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (OSError, json.JSONDecodeError, TrackedIgnoredError) as error:
        if isinstance(error, TrackedIgnoredError):
            raise
        raise TrackedIgnoredError(f"could not read local-only preservation transition: {error}") from error
    if not isinstance(payload, dict):
        raise TrackedIgnoredError("local-only preservation transition has unexpected fields")
    schema_version = payload.get("schema_version")
    if schema_version not in TRANSITION_PHASES:
        raise TrackedIgnoredError("local-only preservation transition schema or phase is unsupported")
    expected_fields = (
        {"schema_version", "phase", "release_version"}
        if schema_version == 1
        else {"schema_version", "baseline_version", "phase", "release_version"}
        if schema_version == 2
        else None
    )
    if set(payload) != expected_fields:
        raise TrackedIgnoredError("local-only preservation transition has unexpected fields")
    baseline_version = 1 if schema_version == 1 else payload.get("baseline_version")
    if baseline_version != schema_version or payload.get("phase") not in TRANSITION_PHASES[schema_version]:
        raise TrackedIgnoredError("local-only preservation transition schema or phase is unsupported")
    version = payload.get("release_version")
    if not isinstance(version, str) or not version:
        raise TrackedIgnoredError("local-only preservation transition release version is invalid")
    return PreservationTransition(schema_version, baseline_version, payload["phase"], version)


def load_transition_pair(transition_path: Path, package_path: Path) -> PreservationTransition:
    transition = load_transition_metadata(transition_path)
    try:
        package = json.loads(
            package_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (OSError, json.JSONDecodeError, TrackedIgnoredError) as error:
        if isinstance(error, TrackedIgnoredError):
            raise
        raise TrackedIgnoredError(f"could not read local-only preservation transition: {error}") from error
    if not isinstance(package, dict) or package.get("version") != transition.release_version:
        raise TrackedIgnoredError("local-only preservation transition version does not match package metadata")
    return transition


def load_transition(repo: Path) -> PreservationTransition:
    return load_transition_pair(repo / TRANSITION_RELATIVE, repo / "package.json")


def _safe_repo_path(value: str) -> bool:
    if not value or not SAFE_PATH.fullmatch(value):
        return False
    candidate = PurePosixPath(value)
    return (
        not candidate.is_absolute() and candidate.parts and all(part not in {"", ".", ".."} for part in candidate.parts)
    )


def _parse_policy_rows(values: object, expected: tuple[tuple[str, str], ...]) -> tuple[PolicyRow, ...]:
    if not isinstance(values, list):
        raise TrackedIgnoredError("tracked-ignore policy paths must be a list")
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
    if tuple((row.path, row.classification) for row in rows) != expected:
        raise TrackedIgnoredError("tracked-ignore policy differs from an exact approved baseline")
    return tuple(rows)


def load_exact_policy(path: Path) -> ExactPolicy:
    import yaml  # lazy: only YAML-parsing paths need pyyaml; JSON-only callers must not require it

    try:
        policy_bytes = path.read_bytes()
        payload = yaml.safe_load(policy_bytes)
    except (OSError, yaml.YAMLError) as error:
        raise TrackedIgnoredError(f"could not read tracked-ignore policy: {error}") from error
    if not isinstance(payload, dict):
        raise TrackedIgnoredError("tracked-ignore policy root must be a mapping")
    schema_version = payload.get("schema_version")
    if schema_version == 1:
        if set(payload) != {"schema_version", "baseline_count", "paths"}:
            raise TrackedIgnoredError(
                "tracked-ignore policy must contain only schema_version, baseline_count, and paths"
            )
        if payload.get("baseline_count") != len(APPROVED_ROWS):
            raise TrackedIgnoredError("tracked-ignore policy must contain the exact 27-row baseline")
        rows = _parse_policy_rows(payload.get("paths"), APPROVED_ROWS)
        baselines = ((1, rows),)
        active = 1
    elif schema_version == 2:
        if set(payload) != {"schema_version", "active_baseline_version", "baselines"}:
            raise TrackedIgnoredError("dual tracked-ignore policy has unexpected fields")
        active = payload.get("active_baseline_version")
        values = payload.get("baselines")
        if active not in BASELINE_ROWS or not isinstance(values, list) or len(values) != len(BASELINE_ROWS):
            raise TrackedIgnoredError("dual tracked-ignore policy must declare both approved baselines")
        parsed: list[tuple[int, tuple[PolicyRow, ...]]] = []
        for expected_version, value in zip(BASELINE_ROWS, values, strict=True):
            if not isinstance(value, dict) or set(value) != {"baseline_version", "baseline_count", "paths"}:
                raise TrackedIgnoredError("tracked-ignore baseline has unexpected fields")
            if value.get("baseline_version") != expected_version:
                raise TrackedIgnoredError("tracked-ignore baselines must be ordered and versioned exactly")
            expected_rows = BASELINE_ROWS[expected_version]
            if value.get("baseline_count") != len(expected_rows):
                raise TrackedIgnoredError("tracked-ignore baseline count does not match its version")
            parsed.append((expected_version, _parse_policy_rows(value.get("paths"), expected_rows)))
        baselines = tuple(parsed)
        rows = dict(baselines)[active]
    else:
        raise TrackedIgnoredError("tracked-ignore policy schema is unsupported")
    return ExactPolicy(active, rows, baselines, hashlib.sha256(policy_bytes).hexdigest())


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
