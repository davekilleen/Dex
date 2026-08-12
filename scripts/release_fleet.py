#!/usr/bin/env python3
"""Discover immutable historic Dex release trees for fleet acceptance."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.paths import INBOX_DIR, TASKS_FILE, USER_PROFILE_FILE, VAULT_ROOT
from core.update.journey_protocol import (
    PROTOCOL_RELATIVE,
    JourneyProtocolError,
    UpdateJourneyProtocol,
    load_update_journey_protocol,
)
from scripts import dex_update_bridge

UPDATE_JOURNEY_RELATIVE = PROTOCOL_RELATIVE
RELEASE_TAG = re.compile(
    r"^dist/release/v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)-(?P<short>[0-9a-f]{7,64})$"
)
ARCHIVE_RELEASE_TAG = re.compile(
    r"^dist/archive/v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)-(?P<short>[0-9a-f]{7,64})$"
)
# The journey executor accepts an archived start only in the canonical
# seven-character form (`_ARCHIVE_RELEASE_TAG` in scripts/release_fleet_executor.py).
# Discovery above is deliberately wider so a non-canonical tag is still seen rather
# than silently ignored; this pattern is what lets discovery reject it up front
# instead of letting the fleet refuse it hours later, mid-run.
EXECUTOR_ARCHIVE_RELEASE_TAG = re.compile(
    r"^dist/archive/v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)-(?P<short>[0-9a-f]{7})$"
)
LEGACY_RELEASE_TAG = re.compile(r"^v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)$")
USER_FIXTURES = {
    str(INBOX_DIR.relative_to(VAULT_ROOT) / "keep.md"): b"# User note\nThis must survive updates.\n",
    str(TASKS_FILE.relative_to(VAULT_ROOT)): b"# My task\n- Keep this task exactly.\n",
    str(USER_PROFILE_FILE.relative_to(VAULT_ROOT)): b"updates:\n  channel: stable\n",
    ".claude/skills/my-weekly-review/SKILL.md": (
        b"---\nname: my-weekly-review\ndescription: User-authored weekly review.\n"
        b"---\n# User skill\n"
    ),
}
REPORT_KEYS = frozenset({"foundation_tag", "follow_up_tag", "platforms", "cases"})
STARTING_MANIFEST_KEYS = frozenset({"schema_version", "case_count", "cases"})
STARTING_RELEASE_KEYS = frozenset({"tag", "version", "commit", "tree"})
CASE_RESULT_KEYS = frozenset(
    {
        "starting_tag",
        "reached_foundation",
        "reached_follow_up",
        "foundation_doctor_healthy",
        "follow_up_doctor_healthy",
        "user_hashes_before",
        "user_hashes_after_foundation",
        "user_hashes_after_follow_up",
        "transcript_path",
        "foundation_receipt_path",
        "follow_up_receipt_path",
        "foundation_doctor_path",
        "follow_up_doctor_path",
        "follow_up_smoke_path",
        "platform",
        "evidence_manifest_path",
        "evidence_manifest_sha256",
    }
)
# Archive tags are historic starting evidence only.  A hop target must be the
# still-published immutable distribution tag that the release channel can prove.
IMMUTABLE_TARGET_TAGS = (RELEASE_TAG,)
_HEX = re.compile(r"^[0-9a-f]{40}$")
UPDATE_SKILL_RELATIVE = ".claude/skills/dex-update/SKILL.md"
UPDATE_RESCUE_RELATIVE = "docs/UPDATE-RESCUE.md"
EVIDENCE_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "executor",
        "starting_release",
        "foundation_release",
        "follow_up_release",
        "events",
        "artifacts",
    }
)
RUNNER_ARTIFACT_KEYS = frozenset(
    {
        "transcript",
        "historic_update_surface",
        "foundation_update_surface",
        "foundation_receipt",
        "follow_up_receipt",
        "foundation_doctor",
        "follow_up_doctor",
        "follow_up_smoke",
    }
)
DISCOVERY_SCHEMA_VERSION = 1
DISCOVERY_OUTPUT_NAME = "historic-discovery-map.json"
DISCOVERY_WORK_NAME = ".historic-discovery-fixtures"
DISCOVERY_MAX_WORKERS = 4
DISCOVERY_DEFAULT_INSTALL_TIMEOUT_SECONDS = 180
DISCOVERY_DEFAULT_DOCTOR_TIMEOUT_SECONDS = 90
OFFICIAL_REPOSITORY_URL = "https://github.com/davekilleen/Dex.git"
OFFICIAL_RELEASE_REF = "refs/remotes/upstream/release"
# Discovery fixtures deliberately do not inherit the caller's PATH.  Keep the
# capability needed by old installers explicit, reviewable, and narrow.
TRUSTED_NODE_CANDIDATES = (Path("/opt/homebrew/bin/node"),)
TRUSTED_NODE_ROOTS = (Path("/opt/homebrew"),)
MINIMUM_SUPPORTED_NODE_MAJOR = 20
TRUSTED_PYTHON_CANDIDATES = (Path("/opt/homebrew/bin/python3"),)
TRUSTED_PYTHON_ROOTS = (Path("/opt/homebrew"),)
MINIMUM_SUPPORTED_PYTHON = (3, 10)
PROCESS_GROUP_TERMINATION_GRACE_SECONDS = 1.0
FIXTURE_REQUIRED_PYTHON_DEPENDENCIES = ("mcp", "yaml")
PRE_BRIDGE_REQUIRED_PYTHON_DEPENDENCIES = ("yaml",)
# The journeys drive the bridge's lifecycle functions in-process, so nothing in
# the fleet ever started the published bridge the way a stuck user starts it:
# as a top-level process that has to scrub its environment and relaunch itself
# inside the vault's own virtualenv before it may load any foundation code. Two
# consecutive user-blocking defects lived entirely in that entry path -- an
# unbounded relaunch loop that burned CPU in silence, then a clean-runtime
# refusal that could never pass -- and both shipped through a green fleet.
BRIDGE_PROCESS_ENTRY_NOTICE = "Relaunching inside Dex's installed runtime..."
BRIDGE_PROCESS_ENTRY_REFUSAL = "could not be entered cleanly"
BRIDGE_PROCESS_ENTRY_TIMEOUT_SECONDS = 600
BRIDGE_PROCESS_ENTRY_RETAINED_BYTES = 256 * 1024
BRIDGE_PROCESS_ENTRY_SUFFIX = ".bridge-process-entry"
SEALED_INSTALLER_ENVIRONMENT_KEYS = frozenset(
    {
        "HOME",
        "TMPDIR",
        "PATH",
        "PIP_CACHE_DIR",
        "LANG",
        "LC_ALL",
        "PYTHONNOUSERSITE",
        "PYTHONDONTWRITEBYTECODE",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_TERMINAL_PROMPT",
        "VAULT_PATH",
    }
)
FIXTURE_PYTHON_PROBE = """
import importlib.util
import json
import platform
import sys

origins = {}
for name in ("mcp", "yaml"):
    spec = importlib.util.find_spec(name)
    locations = list(spec.submodule_search_locations or ()) if spec else []
    origins[name] = spec.origin if spec and spec.origin else (str(locations[0]) if locations else "")
print(json.dumps({
    "version": "Python " + platform.python_version(),
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "executable": sys.executable,
    "dependencies": origins,
}, sort_keys=True))
"""

class FleetError(RuntimeError):
    """The historic release fleet could not be built safely."""


class CaseJourneyFailure(FleetError):
    """One isolated historic journey failed after case execution began."""

    def __init__(self, starting_tag: str, detail: str) -> None:
        if not isinstance(starting_tag, str) or not starting_tag:
            raise ValueError("case journey failure requires a starting tag")
        if not isinstance(detail, str) or not detail:
            raise ValueError("case journey failure requires a detail")
        super().__init__(f"{starting_tag}: {detail}")
        self.starting_tag = starting_tag
        self.detail = detail


@dataclass(frozen=True)
class NodeRuntime:
    """An explicitly selected Node/npm capability for disposable fixtures."""

    requested_node: Path
    resolved_node: Path
    node_version: str
    node_sha256: str
    requested_npm: Path
    resolved_npm: Path
    npm_version: str
    npm_sha256: str

    @property
    def bin_dir(self) -> Path:
        return self.resolved_node.parent

    def identity(self) -> dict[str, str]:
        return {
            "requested_node": str(self.requested_node),
            "resolved_node": str(self.resolved_node),
            "node_version": self.node_version,
            "node_sha256": self.node_sha256,
            "requested_npm": str(self.requested_npm),
            "resolved_npm": str(self.resolved_npm),
            "npm_version": self.npm_version,
            "npm_sha256": self.npm_sha256,
        }


@dataclass(frozen=True)
class PythonRuntime:
    """An explicitly selected Python capability for disposable fixtures."""

    requested_python: Path
    resolved_python: Path
    python_version: str
    python_sha256: str

    @property
    def bin_dir(self) -> Path:
        return self.resolved_python.parent

    def identity(self) -> dict[str, str]:
        return {
            "requested_python": str(self.requested_python),
            "resolved_python": str(self.resolved_python),
            "python_version": self.python_version,
            "python_sha256": self.python_sha256,
        }


@dataclass(frozen=True)
class FixturePython:
    """The installed fixture venv interpreter bound to its trusted base Python."""

    requested_python: Path
    resolved_python: Path
    python_version: str
    python_sha256: str
    pyvenv_cfg: Path
    pyvenv_cfg_sha256: str
    venv_prefix: Path
    base_prefix: Path
    dependency_origins: tuple[tuple[str, str], ...]

    def identity(self) -> dict[str, object]:
        return {
            "requested_python": str(self.requested_python),
            "resolved_python": str(self.resolved_python),
            "python_version": self.python_version,
            "python_sha256": self.python_sha256,
            "pyvenv_cfg": str(self.pyvenv_cfg),
            "pyvenv_cfg_sha256": self.pyvenv_cfg_sha256,
            "venv_prefix": str(self.venv_prefix),
            "base_prefix": str(self.base_prefix),
            "dependency_origins": dict(self.dependency_origins),
        }


@dataclass(frozen=True)
class DistributionRelease:
    """One immutable published release tree that a user may be running."""

    tag: str
    version: str
    commit: str
    tree: str


@dataclass(frozen=True)
class FleetCase:
    """A fresh historic install plus the user content that must survive it."""

    release: DistributionRelease
    vault: Path
    user_hashes: dict[str, str]


@dataclass(frozen=True)
class CaseResult:
    """Evidence from one historic installation's two-release journey."""

    starting_tag: str
    reached_foundation: bool
    reached_follow_up: bool
    foundation_doctor_healthy: bool
    follow_up_doctor_healthy: bool
    user_hashes_before: dict[str, str]
    user_hashes_after_foundation: dict[str, str]
    user_hashes_after_follow_up: dict[str, str]
    transcript_path: str
    foundation_receipt_path: str = ""
    follow_up_receipt_path: str = ""
    foundation_doctor_path: str = ""
    follow_up_doctor_path: str = ""
    follow_up_smoke_path: str = ""
    platform: str = ""
    evidence_manifest_path: str = ""
    evidence_manifest_sha256: str = ""


@dataclass(frozen=True)
class AcceptanceReport:
    """The complete evidence set required before claiming fleet acceptance."""

    foundation_tag: str
    follow_up_tag: str
    cases: tuple[CaseResult, ...]
    platforms: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImmutableRelease:
    """A closed tag identity suitable for an explicitly requested journey hop."""

    tag: str
    tag_object: str
    commit: str
    tree: str
    version: str

    def identity(self) -> dict[str, str]:
        return {
            "tag": self.tag,
            "tag_object": self.tag_object,
            "commit": self.commit,
            "tree": self.tree,
            "version": self.version,
            "channel": "stable",
        }


def _git(repo: Path, *arguments: str, environment: Mapping[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        text=True,
        env=dict(environment) if environment is not None else None,
    )
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "Git command failed"
        raise FleetError(message)
    return result.stdout.strip()


def _git_lines(repo: Path, *arguments: str) -> tuple[str, ...]:
    output = _git(repo, *arguments)
    return tuple(line for line in output.splitlines() if line)


def _git_directory(
    git_directory: Path,
    *arguments: str,
    environment: Mapping[str, str] | None = None,
) -> str:
    result = subprocess.run(
        ["git", f"--git-dir={git_directory}", *arguments],
        capture_output=True,
        text=True,
        env=dict(environment) if environment is not None else None,
    )
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "Git command failed"
        raise FleetError(message)
    return result.stdout.strip()


def resolve_immutable_release(repo: Path, tag: str) -> ImmutableRelease:
    """Resolve one annotated immutable release tag, never a moving ref."""

    match = next((pattern.fullmatch(tag) for pattern in IMMUTABLE_TARGET_TAGS if pattern.fullmatch(tag)), None)
    if match is None:
        raise FleetError("journey targets must be immutable dist/release tags")
    tag_object = _git(repo, "rev-parse", "--verify", tag)
    if _git(repo, "cat-file", "-t", tag) != "tag":
        raise FleetError(f"{tag}: journey target must be an annotated tag")
    commit = _git(repo, "rev-parse", f"{tag}^{{commit}}")
    tree = _git(repo, "rev-parse", f"{tag}^{{tree}}")
    if any(_HEX.fullmatch(value) is None for value in (tag_object, commit, tree)):
        raise FleetError(f"{tag}: journey target identity is malformed")
    if not commit.startswith(match.group("short")):
        raise FleetError(f"{tag}: tag suffix does not match its commit")
    return ImmutableRelease(tag, tag_object, commit, tree, match.group("version"))


def _tag_file(repo: Path, tag: str, relative: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{tag}:{relative}"],
        capture_output=True,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise FleetError(
            detail or f"{tag} has no required {relative} publication record"
        )
    return result.stdout


def _tag_file_if_present(repo: Path, tag: str, relative: str) -> bytes | None:
    """Read one tag path, distinguishing confirmed absence from Git failure."""

    result = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-z", tag, "--", relative],
        capture_output=True,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise FleetError(
            detail or f"{tag}: could not inspect required publication path {relative}"
        )
    if not result.stdout:
        return None
    return _tag_file(repo, tag, relative)


def _strict_object(source: bytes, context: str, keys: frozenset[str]) -> dict[str, object]:
    try:
        value = json.loads(source)
    except json.JSONDecodeError as error:
        raise FleetError(f"{context} is not valid JSON") from error
    if not isinstance(value, Mapping) or set(value) != keys:
        raise FleetError(f"{context} has an invalid shape")
    return dict(value)


def _released_protocol_source_commit(repo: Path, tag: str) -> str:
    """Read the immutable source commit named by one distribution catalog."""

    catalog = _strict_object(
        _tag_file(repo, tag, "System/.release-catalog.json"),
        f"{tag} release catalog",
        frozenset({"catalog_version", "release", "items", "integrity"}),
    )
    release = catalog["release"]
    if not isinstance(release, Mapping):
        raise FleetError(f"{tag}: release catalog has no release identity")
    source_commit = release.get("source_commit")
    if not isinstance(source_commit, str) or _HEX.fullmatch(source_commit) is None:
        raise FleetError(f"{tag}: release catalog has no valid source commit")
    try:
        resolved = _git(repo, "rev-parse", "--verify", f"{source_commit}^{{commit}}")
    except FleetError as error:
        raise FleetError(
            f"{tag}: release-owned journey source commit is unavailable"
        ) from error
    if resolved != source_commit:
        raise FleetError(f"{tag}: release-owned journey source commit is ambiguous")
    return source_commit


def _verify_protocol_source_artifacts(
    repo: Path,
    *,
    release_tag: str,
    source_commit: str,
    protocol: UpdateJourneyProtocol,
) -> None:
    """Prove protocol adapter hashes against one exact source commit."""

    for label, artifact in (
        ("fleet runner", protocol.runner),
        ("journey executor", protocol.executor),
        ("foundation bridge", protocol.bridge.artifact),
    ):
        try:
            source = _tag_file(repo, source_commit, artifact.source_path)
        except FleetError as error:
            raise FleetError(
                f"{release_tag}: released journey {label} source is unavailable"
            ) from error
        if hashlib.sha256(source).hexdigest() != artifact.sha256:
            raise FleetError(
                f"{release_tag}: released journey {label} does not match its protocol hash"
            )


def _verify_released_protocol_artifacts(
    repo: Path,
    release: DistributionRelease | ImmutableRelease,
    protocol: UpdateJourneyProtocol,
) -> str:
    """Bind protocol adapters to the exact publisher source commit bytes."""

    source_commit = _released_protocol_source_commit(repo, release.tag)
    _verify_protocol_source_artifacts(
        repo,
        release_tag=release.tag,
        source_commit=source_commit,
        protocol=protocol,
    )
    return source_commit


def _unbound_semantic_protocol_source(
    repo: Path,
    release: DistributionRelease | ImmutableRelease,
    protocol: UpdateJourneyProtocol,
) -> str | None:
    """Prove catalog-less semantic bytes without granting execution authority."""

    pinned = dex_update_bridge.exact_unbound_journey_source(repo, release.tag)
    if pinned is not None:
        return pinned
    if release.tag == dex_update_bridge.V181_UNBOUND_JOURNEY_SOURCE.release.tag:
        return None
    if LEGACY_RELEASE_TAG.fullmatch(release.tag) is None:
        return None
    catalog = _tag_file_if_present(repo, release.tag, "System/.release-catalog.json")
    if catalog is not None:
        return None
    _verify_protocol_source_artifacts(
        repo,
        release_tag=release.tag,
        source_commit=release.commit,
        protocol=protocol,
    )
    return release.commit


def shipped_update_surface(repo: Path, release: DistributionRelease | ImmutableRelease) -> dict[str, object]:
    """Bind the human-facing `/dex-update` contract to exact released bytes.

    Skills are Markdown instructions, not an executable API.  This evidence is
    deliberately read-only: it proves what the installed release told a person
    to do, but cannot turn prose into a synthetic update command.
    """

    skill = _tag_file(repo, release.tag, UPDATE_SKILL_RELATIVE)
    rescue: bytes | None
    try:
        rescue = _tag_file(repo, release.tag, UPDATE_RESCUE_RELATIVE)
    except FleetError:
        rescue = None
    text = skill.decode("utf-8", "strict")
    required = {
        "service": "core.lifecycle.service" in text,
        "preview": "preview" in text.lower(),
        "approval": "approval" in text.lower() and "Apply this exact update?" in text,
        "receipt": "receipt" in text.lower(),
    }
    delivery = {
        "deliver_latest_release": "deliver_latest_release" in text,
        "build_and_preview_delivered_release": "build_and_preview_delivered_release" in text,
        "execute_approved_delivered_release": "execute_approved_delivered_release" in text,
    }
    protocol_bytes = _optional_tag_file(repo, release.tag, UPDATE_JOURNEY_RELATIVE)
    protocol_surface: dict[str, object] = {
        "path": UPDATE_JOURNEY_RELATIVE,
        "status": "missing",
        "sha256": None,
        "schema_version": None,
        "controller": None,
        "executor": None,
    }
    unbound_source: str | None = None
    if protocol_bytes is not None:
        try:
            protocol = load_update_journey_protocol(protocol_bytes)
        except JourneyProtocolError as error:
            raise FleetError(
                f"{release.tag}: released journey protocol is invalid: {error}"
            ) from error
        unbound_source = _unbound_semantic_protocol_source(repo, release, protocol)
        source_commit = unbound_source or _verify_released_protocol_artifacts(
            repo, release, protocol
        )
        protocol_surface = {
            "path": UPDATE_JOURNEY_RELATIVE,
            "status": "present-unbound" if unbound_source else "present",
            "sha256": hashlib.sha256(protocol_bytes).hexdigest(),
            "schema_version": protocol.schema_version,
            "controller": protocol.controller,
            "executor": {
                "source_path": protocol.executor.source_path,
                "sha256": protocol.executor.sha256,
            },
            "source_commit": source_commit,
        }
    identity = release.identity() if isinstance(release, ImmutableRelease) else {
        "tag": release.tag,
        "tag_object": _git(repo, "rev-parse", "--verify", release.tag),
        "commit": release.commit,
        "tree": release.tree,
        "version": release.version,
        "channel": "stable",
    }
    return {
        "release": identity,
        "skill_path": UPDATE_SKILL_RELATIVE,
        "skill_sha256": hashlib.sha256(skill).hexdigest(),
        "rescue_path": UPDATE_RESCUE_RELATIVE if rescue is not None else None,
        "rescue_sha256": hashlib.sha256(rescue).hexdigest() if rescue is not None else None,
        "preview_approval_receipt": required,
        "delivery_operations": delivery,
        "journey_protocol": protocol_surface,
        # This describes released capability, not successful execution.
        # Acceptance still requires a live, process-local ExecutorRun.
        "machine_executable": protocol_bytes is not None and unbound_source is None,
    }


def _has_transaction_receipt(value: object) -> bool:
    """Recognize the service envelope while rejecting a prose-only success claim."""

    if not isinstance(value, Mapping):
        return False
    if isinstance(value.get("transaction_id"), str) and value["transaction_id"]:
        return True
    return any(
        _has_transaction_receipt(nested)
        for nested in value.values()
        if isinstance(nested, Mapping)
    )


def _valid_foundation_bridge_receipt(
    value: object,
    *,
    expected_foundation: Mapping[str, object],
    approval_count: int,
) -> bool:
    """Accept either the exact resume receipt or an approved lifecycle mutation."""

    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "foundation",
            "topology_receipt",
            "delivery_receipt",
            "mcp_registration_receipt",
        }
        or value["foundation"] != expected_foundation
    ):
        return False
    already_installed = {"skipped": "foundation-already-installed"}
    foundation_completed = (
        value["topology_receipt"] == already_installed
        and value["delivery_receipt"] == already_installed
    )
    registration = value["mcp_registration_receipt"]
    registration_current = registration == {"skipped": "mcp-already-registered"}
    registration_completed = _has_transaction_receipt(registration)
    if foundation_completed:
        return (
            (registration_current and approval_count == 0)
            or (registration_completed and approval_count == 1)
        )
    return (
        approval_count > 0
        and _has_transaction_receipt(value["delivery_receipt"])
        and (registration_current or registration_completed)
    )


def _trusted_runtime_path(path: Path, *, label: str, roots: Sequence[Path]) -> Path:
    """Resolve an allowlisted runtime file without accepting an ambient executable."""

    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise FleetError(f"trusted {label} runtime is unavailable: {path}") from error
    if not resolved.is_file():
        raise FleetError(f"trusted {label} runtime is not a regular file: {path}")
    for root in roots:
        try:
            resolved.relative_to(root.resolve(strict=True))
            return resolved
        except (OSError, ValueError):
            continue
    raise FleetError(f"trusted {label} runtime resolves outside the approved Node roots: {path}")


def _runtime_command_output(command: Sequence[str], *, path: str) -> str:
    """Run a fixed runtime binary with a minimal non-inherited environment."""

    result = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        env={"PATH": path, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise FleetError(f"trusted runtime command failed: {' '.join(command)}: {detail}")
    return result.stdout.strip()


def resolve_trusted_node_runtime() -> NodeRuntime:
    """Select one fixed, supported Node installation; never consult ambient PATH."""

    errors: list[str] = []
    for requested_node in TRUSTED_NODE_CANDIDATES:
        try:
            resolved_node = _trusted_runtime_path(
                requested_node, label="Node", roots=TRUSTED_NODE_ROOTS
            )
            requested_npm = requested_node.parent / "npm"
            resolved_npm = _trusted_runtime_path(requested_npm, label="npm", roots=TRUSTED_NODE_ROOTS)
            runtime_path = f"{resolved_node.parent}:/usr/bin:/bin:/usr/sbin:/sbin"
            node_version = _runtime_command_output([str(resolved_node), "--version"], path=runtime_path)
            match = re.fullmatch(r"v(?P<major>[0-9]+)\.[0-9]+\.[0-9]+", node_version)
            if match is None or int(match.group("major")) < MINIMUM_SUPPORTED_NODE_MAJOR:
                raise FleetError(
                    f"trusted Node runtime must be v{MINIMUM_SUPPORTED_NODE_MAJOR} or newer: {node_version!r}"
                )
            npm_version = _runtime_command_output([str(resolved_npm), "--version"], path=runtime_path)
            if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", npm_version) is None:
                raise FleetError(f"trusted npm runtime has an invalid version: {npm_version!r}")
            return NodeRuntime(
                requested_node=requested_node,
                resolved_node=resolved_node,
                node_version=node_version,
                node_sha256=hashlib.sha256(resolved_node.read_bytes()).hexdigest(),
                requested_npm=requested_npm,
                resolved_npm=resolved_npm,
                npm_version=npm_version,
                npm_sha256=hashlib.sha256(resolved_npm.read_bytes()).hexdigest(),
            )
        except FleetError as error:
            errors.append(str(error))
    raise FleetError("no trusted supported Node runtime is available: " + "; ".join(errors))


def resolve_trusted_python_runtime() -> PythonRuntime:
    """Select one fixed, supported Python installation; never consult ambient PATH."""

    errors: list[str] = []
    for requested_python in TRUSTED_PYTHON_CANDIDATES:
        try:
            resolved_python = _trusted_runtime_path(
                requested_python, label="Python", roots=TRUSTED_PYTHON_ROOTS
            )
            runtime_path = f"{resolved_python.parent}:/usr/bin:/bin:/usr/sbin:/sbin"
            version = _runtime_command_output([str(resolved_python), "--version"], path=runtime_path)
            match = re.fullmatch(r"Python (?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.[0-9]+", version)
            if match is None or (int(match.group("major")), int(match.group("minor"))) < MINIMUM_SUPPORTED_PYTHON:
                raise FleetError(
                    "trusted Python runtime must be "
                    f"{MINIMUM_SUPPORTED_PYTHON[0]}.{MINIMUM_SUPPORTED_PYTHON[1]} or newer: {version!r}"
                )
            return PythonRuntime(
                requested_python=requested_python,
                resolved_python=resolved_python,
                python_version=version,
                python_sha256=hashlib.sha256(resolved_python.read_bytes()).hexdigest(),
            )
        except FleetError as error:
            errors.append(str(error))
    raise FleetError("no trusted supported Python runtime is available: " + "; ".join(errors))


def resolve_fixture_python(
    vault: Path,
    *,
    trusted_python: PythonRuntime,
    required_dependencies: Sequence[str] = FIXTURE_REQUIRED_PYTHON_DEPENDENCIES,
) -> FixturePython:
    """Prove a fixture interpreter and the phase-required dependencies are local."""

    venv_root = vault / ".venv"
    requested_python = venv_root / "bin" / "python"
    pyvenv_cfg = venv_root / "pyvenv.cfg"
    if pyvenv_cfg.is_symlink() or not pyvenv_cfg.is_file():
        raise FleetError(f"fixture venv pyvenv.cfg is unavailable: {pyvenv_cfg}")
    try:
        config_raw = pyvenv_cfg.read_bytes()
        config_text = config_raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise FleetError(f"fixture venv pyvenv.cfg is unreadable: {pyvenv_cfg}") from error
    if re.search(
        r"(?im)^include-system-site-packages\s*=\s*false\s*$", config_text
    ) is None:
        raise FleetError("fixture venv must not inherit system site-packages")

    try:
        resolved_python = requested_python.resolve(strict=True)
    except OSError as error:
        raise FleetError(f"fixture venv Python is unavailable: {requested_python}") from error
    if not requested_python.is_file() or not resolved_python.is_file():
        raise FleetError(f"fixture venv Python is not a regular file: {requested_python}")
    digest = hashlib.sha256(resolved_python.read_bytes()).hexdigest()
    if digest != trusted_python.python_sha256:
        raise FleetError("fixture venv Python does not bind the trusted Python runtime")
    runtime_path = f"{requested_python.parent}:/usr/bin:/bin:/usr/sbin:/sbin"
    probe_result = subprocess.run(
        [str(requested_python), "-I", "-c", FIXTURE_PYTHON_PROBE],
        capture_output=True,
        text=True,
        env={
            "PATH": runtime_path,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONNOUSERSITE": "1",
        },
        check=False,
    )
    if probe_result.returncode:
        raise FleetError("fixture venv Python provenance probe failed")
    try:
        provenance = json.loads(probe_result.stdout)
    except json.JSONDecodeError as error:
        raise FleetError("fixture venv Python provenance probe was not valid JSON") from error
    if not isinstance(provenance, Mapping):
        raise FleetError("fixture venv Python provenance probe was malformed")
    version = provenance.get("version")
    if version != trusted_python.python_version:
        raise FleetError("fixture venv Python version does not match the trusted Python runtime")
    try:
        venv_prefix = Path(str(provenance["prefix"])).resolve(strict=True)
        base_prefix = Path(str(provenance["base_prefix"])).resolve(strict=True)
        executable = Path(str(provenance["executable"])).resolve(strict=True)
    except (KeyError, OSError) as error:
        raise FleetError("fixture venv Python provenance paths were invalid") from error
    expected_venv = venv_root.resolve(strict=True)
    expected_base = trusted_python.resolved_python.parent.parent
    if venv_prefix != expected_venv or venv_prefix == base_prefix:
        raise FleetError("fixture Python is not running inside the fixture venv")
    if base_prefix != expected_base or executable != trusted_python.resolved_python:
        raise FleetError("fixture venv Python base does not match the trusted Python runtime")
    raw_dependencies = provenance.get("dependencies")
    if not isinstance(raw_dependencies, Mapping):
        raise FleetError("fixture venv dependency provenance was malformed")
    dependency_origins: list[tuple[str, str]] = []
    for dependency in required_dependencies:
        origin = raw_dependencies.get(dependency)
        if not isinstance(origin, str) or not origin:
            raise FleetError(f"fixture venv dependency is unavailable: {dependency}")
        try:
            resolved_origin = Path(origin).resolve(strict=True)
            resolved_origin.relative_to(expected_venv)
        except (OSError, ValueError) as error:
            raise FleetError(
                f"fixture venv dependency escapes the fixture: {dependency}"
            ) from error
        dependency_origins.append((dependency, str(resolved_origin)))
    return FixturePython(
        requested_python=requested_python,
        resolved_python=resolved_python,
        python_version=str(version),
        python_sha256=digest,
        pyvenv_cfg=pyvenv_cfg,
        pyvenv_cfg_sha256=hashlib.sha256(config_raw).hexdigest(),
        venv_prefix=venv_prefix,
        base_prefix=base_prefix,
        dependency_origins=tuple(dependency_origins),
    )


def _case_environment(
    vault: Path,
    runtime_root: Path,
    *,
    node_runtime: NodeRuntime | None = None,
    python_runtime: PythonRuntime | None = None,
    pip_cache_dir: Path | None = None,
    controller_root: Path | None = None,
) -> dict[str, str]:
    """Return the sealed fixture environment owned by one private controller.

    The fleet controller creates this root before running first-party historic
    installers. Fleet execution is serialized; this boundary is not intended
    to defend against a hostile concurrent process replacing controller files.
    """

    controller = controller_root or runtime_root
    if controller.is_symlink() or (
        controller.exists() and not controller.is_dir()
    ):
        raise FleetError("fixture controller root must be a private directory")
    controller.mkdir(parents=True, mode=0o700, exist_ok=True)
    controller_status = controller.stat()
    if (
        controller_status.st_uid != os.getuid()
        or stat.S_IMODE(controller_status.st_mode) != 0o700
    ):
        raise FleetError(
            "fixture controller root must be owned by the controller with mode 0700"
        )
    home = runtime_root / "home"
    temporary = runtime_root / "tmp"
    pip_cache = pip_cache_dir or runtime_root / "pip-cache"
    try:
        pip_cache.resolve().relative_to(controller.resolve(strict=True))
    except ValueError as error:
        raise FleetError(
            "fixture pip cache must stay inside the private controller root"
        ) from error
    try:
        pip_cache.resolve().relative_to(vault.resolve())
    except ValueError:
        pass
    else:
        raise FleetError("fixture pip cache must stay outside the vault")
    home.mkdir(parents=True, exist_ok=False)
    temporary.mkdir(parents=True, exist_ok=False)
    if pip_cache.is_symlink() or (pip_cache.exists() and not pip_cache.is_dir()):
        raise FleetError("fixture pip cache must be a private directory")
    pip_cache.mkdir(parents=True, mode=0o700, exist_ok=True)
    cache_status = pip_cache.stat()
    if (
        cache_status.st_uid != os.getuid()
        or stat.S_IMODE(cache_status.st_mode) != 0o700
    ):
        raise FleetError(
            "fixture pip cache must be owned by the controller with mode 0700"
        )
    environment = {
        "HOME": str(home),
        "TMPDIR": str(temporary),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "PIP_CACHE_DIR": str(pip_cache.resolve(strict=True)),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "VAULT_PATH": str(vault),
    }
    if node_runtime is not None:
        environment["PATH"] = f"{node_runtime.bin_dir}:{environment['PATH']}"
    if python_runtime is not None:
        environment["PATH"] = f"{python_runtime.bin_dir}:{environment['PATH']}"
    return environment


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_evidence_manifest(
    evidence_root: Path,
    *,
    start: dict[str, object],
    foundation: ImmutableRelease,
    follow_up: ImmutableRelease,
    events: Sequence[Mapping[str, object]],
    artifacts: Mapping[str, Path],
) -> tuple[str, str]:
    """Write the runner-owned, content-addressed index that report checking consumes."""

    artifact_index: dict[str, dict[str, str]] = {}
    for name, artifact in artifacts.items():
        try:
            relative = artifact.resolve().relative_to(evidence_root.parent.resolve())
        except ValueError as error:
            raise FleetError(f"evidence artifact escapes its case directory: {name}") from error
        if artifact.is_symlink() or not artifact.is_file():
            raise FleetError(f"evidence artifact is missing or unsafe: {name}")
        artifact_index[name] = {
            "path": str(relative),
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }

    manifest = {
        "schema_version": 1,
        "starting_release": start,
        "foundation_release": foundation.identity(),
        "follow_up_release": follow_up.identity(),
        "events": [dict(event) for event in events],
        "artifacts": artifact_index,
    }
    path = evidence_root / "evidence-manifest.json"
    _write_json(path, manifest)
    return f"{evidence_root.name}/evidence-manifest.json", hashlib.sha256(path.read_bytes()).hexdigest()


def _version_key(version: str) -> tuple[int, int, int]:
    parts = tuple(int(part) for part in version.split("."))
    if len(parts) != 3:
        raise FleetError(f"distribution tag has an invalid semantic version: {version}")
    return parts  # type: ignore[return-value]


def discover_distribution_releases(repo: Path) -> tuple[DistributionRelease, ...]:
    """Return every distinct tree behind immutable and legacy public release tags."""

    seen_trees: set[str] = set()
    immutable_identities: dict[tuple[str, str], str] = {}
    discovered: list[DistributionRelease] = []
    candidates: list[tuple[int, str, re.Match[str]]] = []
    for tag in _git_lines(repo, "tag", "--list"):
        distribution_match = RELEASE_TAG.fullmatch(tag)
        if distribution_match is not None:
            candidates.append((0, tag, distribution_match))
            continue
        archive_match = ARCHIVE_RELEASE_TAG.fullmatch(tag)
        if archive_match is not None:
            candidates.append((1, tag, archive_match))
            continue
        legacy_match = LEGACY_RELEASE_TAG.fullmatch(tag)
        if legacy_match is not None:
            candidates.append((2, tag, legacy_match))

    for priority, tag, match in sorted(candidates, key=lambda item: (item[0], item[1])):
        commit = _git(repo, "rev-parse", f"{tag}^{{commit}}")
        if priority < 2 and not commit.startswith(match.group("short")):
            raise FleetError(f"{tag}: tag suffix does not match its commit")
        if priority < 2:
            identity = (match.group("version"), match.group("short"))
            existing_commit = immutable_identities.setdefault(identity, commit)
            if existing_commit != commit:
                raise FleetError(
                    f"{tag}: ambiguous immutable distribution identity "
                    f"v{identity[0]}-{identity[1]}"
                )
        tree = _git(repo, "rev-parse", f"{tag}^{{tree}}")
        if tree in seen_trees:
            continue
        seen_trees.add(tree)
        discovered.append(
            DistributionRelease(
                tag=tag,
                version=match.group("version"),
                commit=commit,
                tree=tree,
            )
        )
    for release in discovered:
        if not release.tag.startswith("dist/archive/"):
            continue
        if EXECUTOR_ARCHIVE_RELEASE_TAG.fullmatch(release.tag) is not None:
            continue
        raise FleetError(
            f"{release.tag}: archived start tag is not in the canonical "
            f"seven-character form, so the journey executor would refuse it "
            f"part-way through a run. Add the canonical tag for commit "
            f"{release.commit} alongside it; nothing needs deleting, because "
            f"discovery keeps one start per tree and prefers the shorter tag."
        )
    return tuple(sorted(discovered, key=lambda item: (_version_key(item.version), item.tag)))


def safe_case_name(release: DistributionRelease) -> str:
    """Return a filesystem-safe, immutable name for one historic release case."""

    return f"v{release.version}-{release.commit[:12]}"


def hash_user_owned_files(vault: Path) -> dict[str, str]:
    """Hash the fixture files whose bytes an update may never change."""

    hashes: dict[str, str] = {}
    for relative in USER_FIXTURES:
        path = vault / relative
        if path.is_symlink() or not path.is_file():
            raise FleetError(f"user fixture is not a regular file: {relative}")
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _create_fixture_vault(
    repo: Path,
    release: DistributionRelease,
    output: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Clone one historic release without inheriting later release metadata."""

    if output.exists() and not output.is_dir():
        raise FleetError(f"fleet output is not a directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    vault = output / safe_case_name(release)
    if vault.exists():
        raise FleetError(f"fleet case directory must be empty: {vault}")

    _git(
        repo,
        "clone",
        "--quiet",
        "--no-checkout",
        "--no-local",
        "--no-tags",
        str(repo),
        str(vault),
        environment=environment,
    )
    _git(vault, "fetch", "--quiet", "--no-tags", "origin", f"refs/tags/{release.tag}:refs/tags/{release.tag}", environment=environment)
    _git(vault, "checkout", "--quiet", "--detach", release.tag, environment=environment)
    _git(vault, "remote", "rename", "origin", "upstream", environment=environment)
    _disable_fixture_remotes(vault, environment)

    _git(vault, "config", "user.name", "Dex Fleet Fixture", environment=environment)
    _git(vault, "config", "user.email", "fleet@example.com", environment=environment)
    return vault


def _disable_fixture_remotes(
    vault: Path, environment: Mapping[str, str] | None = None
) -> None:
    """Keep historic installers from fetching or pushing a moving revision."""

    remotes = tuple(_git(vault, "remote", environment=environment).splitlines())
    for remote in remotes:
        _git(vault, "remote", "remove", remote, environment=environment)
        _git(vault, "remote", "add", remote, "DISABLED", environment=environment)
        _git(
            vault,
            "remote",
            "set-url",
            "--push",
            remote,
            "DISABLED",
            environment=environment,
        )
    for remote in remotes:
        fetch_urls = tuple(
            _git(vault, "remote", "get-url", "--all", remote, environment=environment).splitlines()
        )
        push_urls = tuple(
            _git(
                vault,
                "remote",
                "get-url",
                "--push",
                "--all",
                remote,
                environment=environment,
            ).splitlines()
        )
        if fetch_urls != ("DISABLED",) or push_urls != ("DISABLED",):
            raise FleetError(f"fixture remote {remote!r} could not be disabled")


def _disable_git_directory_remotes(
    git_directory: Path,
    environment: Mapping[str, str] | None = None,
) -> None:
    if git_directory.is_symlink() or not git_directory.is_dir():
        return
    remotes = tuple(
        line
        for line in _git_directory(
            git_directory, "remote", environment=environment
        ).splitlines()
        if line
    )
    for remote in remotes:
        _git_directory(
            git_directory,
            "remote",
            "set-url",
            remote,
            "DISABLED",
            environment=environment,
        )
        _git_directory(
            git_directory,
            "remote",
            "set-url",
            "--push",
            remote,
            "DISABLED",
            environment=environment,
        )


def _disable_all_fixture_remotes(
    vault: Path,
    environment: Mapping[str, str] | None = None,
) -> None:
    _disable_fixture_remotes(vault, environment)
    for relative in (".dex/brain.git", ".dex/pre-split-archive.git"):
        _disable_git_directory_remotes(vault / relative, environment)


def _prepare_installer_release_remote(
    repo: Path,
    vault: Path,
    release: DistributionRelease,
    environment: Mapping[str, str],
) -> tuple[str, str]:
    """Expose the exact historic release as the official ref during installation."""

    try:
        release_commit = _git(
            repo,
            "rev-parse",
            "--verify",
            f"{release.commit}^{{commit}}",
        )
        release_tree = _git(
            repo,
            "rev-parse",
            "--verify",
            f"{release.commit}^{{tree}}",
        )
    except FleetError as error:
        raise FleetError("historic release is unavailable for fixture setup") from error
    if release_commit != release.commit or release_tree != release.tree:
        raise FleetError("historic release identity changed before fixture setup")
    _git(
        vault,
        "fetch",
        "--quiet",
        "--no-tags",
        str(repo),
        f"+{release_commit}:{OFFICIAL_RELEASE_REF}",
        environment=environment,
    )
    _git(
        vault,
        "remote",
        "set-url",
        "upstream",
        OFFICIAL_REPOSITORY_URL,
        environment=environment,
    )
    _git(
        vault,
        "remote",
        "set-url",
        "--push",
        "upstream",
        "DISABLED",
        environment=environment,
    )
    if (
        _git(vault, "remote", "get-url", "upstream", environment=environment)
        != OFFICIAL_REPOSITORY_URL
        or _git(
            vault,
            "rev-parse",
            "--verify",
            f"{OFFICIAL_RELEASE_REF}^{{commit}}",
            environment=environment,
        )
        != release_commit
    ):
        raise FleetError("fixture could not prove the official release ref")
    return release_commit, release_tree


def _seed_user_content(vault: Path, environment: Mapping[str, str] | None = None) -> dict[str, str]:
    """Place fixed user-owned content only after the historic install is ready."""
    for relative, content in USER_FIXTURES.items():
        path = vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    _git(vault, "add", "-f", "--", *USER_FIXTURES, environment=environment)
    _git(vault, "commit", "--quiet", "-m", "test: simulated user content", environment=environment)
    return hash_user_owned_files(vault)


def build_fixture(repo: Path, release: DistributionRelease, output: Path) -> FleetCase:
    """Create a structural historic-release fixture without running its installer."""
    vault = _create_fixture_vault(repo, release, output)
    return FleetCase(release=release, vault=vault, user_hashes=_seed_user_content(vault))


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _run_bounded_process_group(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    stdin: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one trusted fixture command and leave no same-group timeout descendants."""

    if os.name != "posix":
        raise FleetError("historic fixture commands require POSIX process groups")
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=dict(environment),
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + PROCESS_GROUP_TERMINATION_GRACE_SECONDS
        while True:
            process.poll()
            if not _process_group_exists(process.pid):
                break
            if process.returncode is not None:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.02, remaining))
        if _process_group_exists(process.pid):
            kill_deadline = time.monotonic() + PROCESS_GROUP_TERMINATION_GRACE_SECONDS
            permission_error: PermissionError | None = None
            while _process_group_exists(process.pid):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    permission_error = None
                except ProcessLookupError:
                    break
                except PermissionError as error:
                    permission_error = error
                remaining = kill_deadline - time.monotonic()
                if remaining <= 0:
                    if _process_group_exists(process.pid):
                        raise FleetError(
                            "timed-out fixture process group could not be killed"
                        ) from permission_error
                    break
                time.sleep(min(0.02, remaining))
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            list(command),
            timeout_seconds,
            output=stdout,
            stderr=stderr,
        )
    return subprocess.CompletedProcess(
        list(command),
        process.returncode,
        stdout,
        stderr,
    )


def _historic_installer_command(
    installer: Path,
    release: DistributionRelease,
) -> list[str]:
    command = ["bash", "install.sh"]
    try:
        source = installer.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise FleetError("historic install.sh is unreadable") from error
    if release.version == "1.75.0" and "--allow-synced-folder" in source:
        command.append("--allow-synced-folder")
    return command


def _stamp_v175_transition(
    vault: Path,
    environment: Mapping[str, str],
    *,
    timeout_seconds: int,
) -> None:
    """Use v1.75's own publisher command to repair its stale generated stamp."""

    transition_path = vault / "System/.local-only-preservation-transition.json"
    package_path = vault / "package.json"
    try:
        before = json.loads(transition_path.read_text(encoding="utf-8"))
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FleetError("v1.75 transition metadata could not be inspected") from error
    if (
        not isinstance(before, Mapping)
        or set(before) != {"schema_version", "phase", "release_version"}
        or before.get("schema_version") != 1
        or before.get("phase") != "untrack-v1"
        or before.get("release_version") != "1.74.0"
        or not isinstance(package, Mapping)
        or package.get("version") != "1.75.0"
    ):
        raise FleetError("v1.75 transition repair precondition did not match")
    command = [
        str(vault / ".venv/bin/python"),
        "-m",
        "core.migrations.preserve_local_only_paths",
        "stamp-transition",
        "--repo",
        str(vault),
    ]
    result = _run_bounded_process_group(
        command,
        cwd=vault,
        environment=environment,
        timeout_seconds=timeout_seconds,
    )
    if result.returncode:
        raise FleetError("v1.75 transition publisher repair failed")
    try:
        after = json.loads(transition_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FleetError("v1.75 transition publisher repair was unreadable") from error
    if after != {
        "schema_version": 1,
        "phase": "untrack-v1",
        "release_version": "1.75.0",
    }:
        raise FleetError("v1.75 transition publisher repair was invalid")


def _read_closed_json_file(path: Path, *, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise FleetError(f"{label} is missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FleetError(f"{label} is unreadable") from error
    if not isinstance(value, Mapping):
        raise FleetError(f"{label} is malformed")
    return dict(value)


def _prove_installed_release_identity(
    vault: Path,
    release: DistributionRelease,
    environment: Mapping[str, str],
    *,
    official_release_commit: str,
    official_release_tree: str,
) -> None:
    """Accept the original checkout or the migrator's fully proved split."""

    try:
        installed_commit = _git(vault, "rev-parse", "HEAD", environment=environment)
        installed_tree = _git(vault, "rev-parse", "HEAD^{tree}", environment=environment)
    except FleetError as error:
        raise FleetError("historic installer release identity could not be proved") from error
    if installed_commit == release.commit and installed_tree == release.tree:
        return

    try:
        topology = _read_closed_json_file(
            vault / "System/.dex/topology.json",
            label="installer-created topology record",
        )
    except FleetError as error:
        raise FleetError(
            "historic installer changed immutable release identity without a valid topology"
        ) from error
    if (
        topology.get("schemaVersion") != 1
        or topology.get("topology") != "brain-vault-split"
        or topology.get("vaultGitDir") != ".git"
        or topology.get("brainGitDir") != ".dex/brain.git"
        or topology.get("archiveGitDir") != ".dex/pre-split-archive.git"
        or topology.get("installedRelease") != official_release_commit
    ):
        raise FleetError(
            "historic installer changed immutable release identity without a valid topology"
        )
    brain = vault / ".dex/brain.git"
    try:
        vault_marker = _read_closed_json_file(
            vault / ".git/dex-vault-v2",
            label="installer-created vault marker",
        )
        brain_marker = _read_closed_json_file(
            brain / "dex-brain-v2",
            label="installer-created brain marker",
        )
    except FleetError as error:
        raise FleetError(
            "historic installer changed immutable release identity with invalid topology markers"
        ) from error
    if (
        vault_marker != {"schemaVersion": 1, "role": "vault"}
        or brain_marker
        != {
            "schemaVersion": 1,
            "role": "brain",
            "installed": official_release_commit,
        }
    ):
        raise FleetError(
            "historic installer changed immutable release identity with invalid topology markers"
        )
    archive = vault / ".dex/pre-split-archive.git"
    try:
        archive_commit = _git_directory(
            archive, "rev-parse", "HEAD^{commit}", environment=environment
        )
        archive_tree = _git_directory(
            archive, "rev-parse", "HEAD^{tree}", environment=environment
        )
        brain_commit = _git_directory(
            brain,
            "rev-parse",
            "refs/dex/installed^{commit}",
            environment=environment,
        )
        brain_tree = _git_directory(
            brain,
            "rev-parse",
            "refs/dex/installed^{tree}",
            environment=environment,
        )
    except FleetError as error:
        raise FleetError(
            "historic installer changed immutable release identity and topology could not be proved"
        ) from error
    if archive_commit != release.commit or archive_tree != release.tree:
        raise FleetError(
            "historic installer changed immutable release identity and its pre-split archive "
            "does not preserve the immutable release"
        )
    if (
        brain_commit != official_release_commit
        or brain_tree != official_release_tree
    ):
        raise FleetError(
            "historic installer changed immutable release identity and its brain does not "
            "match the official release ref"
        )


def _installer_created_split_topology(vault: Path) -> bool:
    """Recognize the already-proved split shape without requiring a vault remote."""

    brain = vault / ".dex/brain.git"
    archive = vault / ".dex/pre-split-archive.git"
    if (
        brain.is_symlink()
        or not brain.is_dir()
        or archive.is_symlink()
        or not archive.is_dir()
    ):
        return False
    try:
        topology = _read_closed_json_file(
            vault / "System/.dex/topology.json",
            label="installer-created topology record",
        )
        vault_marker = _read_closed_json_file(
            vault / ".git/dex-vault-v2",
            label="installer-created vault marker",
        )
        brain_marker = _read_closed_json_file(
            brain / "dex-brain-v2",
            label="installer-created brain marker",
        )
    except FleetError:
        return False
    installed = topology.get("installedRelease")
    return (
        isinstance(installed, str)
        and bool(installed)
        and topology.get("schemaVersion") == 1
        and topology.get("topology") == "brain-vault-split"
        and topology.get("vaultGitDir") == ".git"
        and topology.get("brainGitDir") == ".dex/brain.git"
        and topology.get("archiveGitDir") == ".dex/pre-split-archive.git"
        and vault_marker == {"schemaVersion": 1, "role": "vault"}
        and brain_marker
        == {
            "schemaVersion": 1,
            "role": "brain",
            "installed": installed,
        }
    )


def _initial_install_evidence(
    vault: Path, environment: Mapping[str, str]
) -> dict[str, object]:
    """Prove a package-created split brain has never-fetched ref shape."""

    if not _installer_created_split_topology(vault):
        return {"topology": "legacy-monolithic", "brain_refs": []}
    refs_output = _git_directory(
        vault / ".dex/brain.git",
        "for-each-ref",
        "--format=%(refname)",
        environment=environment,
    )
    refs = sorted(line for line in refs_output.splitlines() if line)
    allowed = {"refs/dex/installed", "refs/heads/release"}
    if "refs/dex/installed" not in refs or any(ref not in allowed for ref in refs):
        raise FleetError(
            "clean split package fixture must begin without tags or remote-tracking refs"
        )
    return {"topology": "brain-vault-split", "brain_refs": refs}


def _run_historic_installer(
    vault: Path,
    release: DistributionRelease,
    environment: Mapping[str, str],
    *,
    timeout_seconds: int = 15 * 60,
    official_release_commit: str | None = None,
    official_release_tree: str | None = None,
    keep_official_fetch: bool = False,
) -> str:
    """Run trusted first-party installer code inside a sealed disposable fixture.

    Published Dex installers are trusted first-party code, not arbitrary hostile
    programs. The runner still removes ambient HOME/TMP/PATH state, disables Git
    remotes, terminates the whole installer process group on timeout, and proves
    that the installer did not switch away from the immutable release.
    """
    if set(environment) != SEALED_INSTALLER_ENVIRONMENT_KEYS:
        raise FleetError("historic installer requires the sealed fixture environment")
    installer = vault / "install.sh"
    if installer.is_symlink() or not installer.is_file():
        raise FleetError("historic release has no safe install.sh to bootstrap its fixture")
    try:
        command = _historic_installer_command(installer, release)
        result = _run_bounded_process_group(
            command,
            cwd=vault,
            environment=environment,
            timeout_seconds=timeout_seconds,
        )
        detail = "\n".join(
            output for output in (result.stdout, result.stderr) if output
        ).strip()
        if (
            result.returncode
            and release.version == "1.75.0"
            and "Tracked-ignore transition version does not match package metadata."
            in detail
        ):
            _stamp_v175_transition(
                vault,
                environment,
                timeout_seconds=timeout_seconds,
            )
            result = _run_bounded_process_group(
                command,
                cwd=vault,
                environment=environment,
                timeout_seconds=timeout_seconds,
            )
            detail = "\n".join(
                output for output in (result.stdout, result.stderr) if output
            ).strip()
        installed_release_commit = official_release_commit or release.commit
        installed_release_tree = official_release_tree or release.tree
        if result.returncode:
            known_post_topology_stop = (
                "installed catalog release does not match the designated bridge release"
                in detail
                or "ModuleNotFoundError: No module named 'yaml'" in detail
            )
            if not known_post_topology_stop:
                raise FleetError(
                    f"historic installer failed for {vault.name}: {detail}"
                )
            _prove_installed_release_identity(
                vault,
                release,
                environment,
                official_release_commit=installed_release_commit,
                official_release_tree=installed_release_tree,
            )
            return "installer-complete-after-known-post-topology-stop"
        _prove_installed_release_identity(
            vault,
            release,
            environment,
            official_release_commit=installed_release_commit,
            official_release_tree=installed_release_tree,
        )
        return "installer-complete"
    finally:
        if not keep_official_fetch:
            _disable_all_fixture_remotes(vault, environment)


def build_installed_fixture(
    repo: Path,
    release: DistributionRelease,
    output: Path,
    *,
    environment: Mapping[str, str] | None = None,
    keep_official_fetch: bool = False,
) -> FleetCase:
    """Install the historic release, then add synthetic user-owned data for updating."""
    vault = output / safe_case_name(release)
    runtime_root = output / f"{safe_case_name(release)}.runtime"
    sealed_environment = (
        dict(environment)
        if environment is not None
        else _case_environment(vault, runtime_root)
    )
    _create_fixture_vault(repo, release, output, environment=sealed_environment)
    release_commit, release_tree = _prepare_installer_release_remote(
        repo, vault, release, sealed_environment
    )
    _run_historic_installer(
        vault,
        release,
        sealed_environment,
        official_release_commit=release_commit,
        official_release_tree=release_tree,
        keep_official_fetch=keep_official_fetch,
    )
    return FleetCase(
        release=release,
        vault=vault,
        user_hashes=_seed_user_content(vault, sealed_environment),
    )


def _optional_tag_file(repo: Path, tag: str, relative: str) -> bytes | None:
    try:
        return _tag_file(repo, tag, relative)
    except FleetError:
        return None


def classify_historic_update_surface(repo: Path, release: DistributionRelease) -> dict[str, object]:
    """Describe published route material without attempting to execute its prose."""

    skill = _optional_tag_file(repo, release.tag, UPDATE_SKILL_RELATIVE)
    rescue = _optional_tag_file(repo, release.tag, UPDATE_RESCUE_RELATIVE)
    lifecycle = _optional_tag_file(repo, release.tag, "core/lifecycle/service.py")
    activation_bridge = _optional_tag_file(
        repo, release.tag, "core/lifecycle/catalog/bridge-release.json"
    )
    protocol = _optional_tag_file(repo, release.tag, UPDATE_JOURNEY_RELATIVE)
    unbound_source: str | None = None
    if protocol is not None:
        try:
            parsed_protocol = load_update_journey_protocol(protocol)
        except JourneyProtocolError as error:
            raise FleetError(
                f"{release.tag}: released journey protocol is invalid: {error}"
            ) from error
        unbound_source = _unbound_semantic_protocol_source(
            repo, release, parsed_protocol
        )
        if unbound_source is None:
            _verify_released_protocol_artifacts(repo, release, parsed_protocol)
            route = "machine-protocol-released-executor"
            bridge_requirement = "released-journey-executor"
        else:
            route = "protocol-present-unbound-source"
            bridge_requirement = "versioned-delivery-bridge-required"
    elif skill is None:
        route = "missing-dex-update-skill"
        bridge_requirement = "unsupported-without-published-route"
    elif lifecycle is not None:
        route = "lifecycle-guided-prose"
        bridge_requirement = "versioned-delivery-bridge-required"
    elif rescue is not None:
        route = "documented-rescue-prose"
        bridge_requirement = "manual-rescue-only"
    else:
        route = "legacy-dex-update-prose"
        bridge_requirement = "versioned-bridge-required"
    return {
        "route_classification": route,
        "bridge_requirement": bridge_requirement,
        "machine_executable": protocol is not None and unbound_source is None,
        "dex_update_skill": {
            "path": UPDATE_SKILL_RELATIVE,
            "status": "present" if skill is not None else "missing",
            "sha256": hashlib.sha256(skill).hexdigest() if skill is not None else None,
        },
        "rescue": {
            "path": UPDATE_RESCUE_RELATIVE,
            "status": "present" if rescue is not None else "missing",
            "sha256": hashlib.sha256(rescue).hexdigest() if rescue is not None else None,
        },
        "lifecycle_era": {
            "service": lifecycle is not None,
            "activation_bridge": activation_bridge is not None,
        },
        "machine_protocol": {
            "path": UPDATE_JOURNEY_RELATIVE,
            "status": "present" if protocol is not None else "missing",
            "sha256": hashlib.sha256(protocol).hexdigest() if protocol is not None else None,
        },
    }


def _output_fingerprint(value: str | None) -> dict[str, object]:
    raw = (value or "").encode("utf-8", "replace")
    return {"sha256": hashlib.sha256(raw).hexdigest(), "byte_count": len(raw)}


def _doctor_preflight(
    vault: Path,
    environment: Mapping[str, str],
    *,
    fixture_python: FixturePython,
    timeout_seconds: int,
) -> dict[str, object]:
    """Run the fixture's own Doctor only; its report is diagnostic, never acceptance."""

    command = [str(fixture_python.requested_python), "-m", "core.utils.doctor"]
    interpreter = {"interpreter": fixture_python.identity()}
    try:
        result = _run_bounded_process_group(
            command,
            cwd=vault,
            environment=environment,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        return {
            "status": "failed",
            "code": "doctor-timeout",
            "command": command,
            **interpreter,
            "stdout": _output_fingerprint(error.stdout if isinstance(error.stdout, str) else None),
            "stderr": _output_fingerprint(error.stderr if isinstance(error.stderr, str) else None),
        }
    fingerprints = {
        "stdout": _output_fingerprint(result.stdout),
        "stderr": _output_fingerprint(result.stderr),
    }
    if result.returncode:
        return {
            "status": "failed",
            "code": "doctor-exit-nonzero",
            "command": command,
            **interpreter,
            **fingerprints,
        }
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "status": "failed",
            "code": "doctor-invalid-json",
            "command": command,
            **interpreter,
            **fingerprints,
        }
    checks = report.get("checks") if isinstance(report, Mapping) else None
    if not isinstance(checks, list) or not checks:
        return {
            "status": "failed",
            "code": "doctor-missing-checks",
            "command": command,
            **interpreter,
            **fingerprints,
        }
    verdicts = [item.get("verdict") for item in checks if isinstance(item, Mapping)]
    if len(verdicts) != len(checks) or any(verdict not in {"OK", "OFF"} for verdict in verdicts):
        return {
            "status": "failed",
            "code": _doctor_unhealthy_code(checks),
            "command": command,
            **interpreter,
            **fingerprints,
        }
    return {"status": "ok", "code": "doctor-healthy", "command": command, **interpreter, **fingerprints}


def _remove_disposable_fixture(path: Path, work_root: Path) -> None:
    """Delete only a known per-case path inside the explicitly disposable work root."""

    try:
        path.resolve().relative_to(work_root.resolve())
    except ValueError as error:
        raise FleetError("disposable fixture escaped the survey work root") from error
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _survey_issue(stage: str, code: str) -> dict[str, str]:
    return {"stage": stage, "code": code}


def _installer_failure_code(error: FleetError) -> str:
    """Normalize expected fixture setup failures without retaining installer output."""

    detail = str(error).lower()
    if (
        "historic installer changed immutable release identity" in detail
        or "historic installer release identity could not be proved" in detail
    ):
        return "installer-release-identity-changed"
    if "installed catalog release does not match the designated bridge release" in detail:
        return "installer-lifecycle-bridge-release-mismatch"
    if "no module named 'yaml'" in detail:
        return "installer-python-yaml-missing"
    if "dex vault provision failed" in detail:
        return "installer-vault-provision-failed"
    if "python" in detail and (
        "too old" in detail or "requires python 3.10" in detail or "requires python >= 3.10" in detail
    ):
        return "installer-python-unsupported"
    if "npm: command not found" in detail or "npm: not found" in detail:
        return "installer-npm-unavailable"
    if (
        "node: command not found" in detail
        or "node: not found" in detail
        or "node.js is not installed" in detail
    ):
        return "installer-node-unavailable"
    if "python3: command not found" in detail or "python3: not found" in detail:
        return "installer-python-unavailable"
    if "git: command not found" in detail or "git: not found" in detail:
        return "installer-git-unavailable"
    if "permission denied" in detail:
        return "installer-permission-denied"
    if "no such file or directory" in detail:
        return "installer-missing-dependency"
    return "installer-exit-" + hashlib.sha256(detail.encode("utf-8", "replace")).hexdigest()[:12]


def _doctor_unhealthy_code(checks: Sequence[object]) -> str:
    """Normalize Doctor verdicts without retaining volatile report details."""

    details = [
        str(item.get("detail", "")).lower()
        for item in checks
        if isinstance(item, Mapping) and item.get("verdict") not in {"OK", "OFF"}
    ]
    combined = "\n".join(details)
    if "mcp' package missing" in combined or "mcp package missing" in combined:
        return "doctor-mcp-dependency-missing"
    if "python packages not installed" in combined:
        return "doctor-python-dependencies-missing"
    if "modified shipped files" in combined:
        return "doctor-shipped-file-drift"
    signature = [
        (str(item.get("id", "")), str(item.get("verdict", "")))
        for item in checks
        if isinstance(item, Mapping) and item.get("verdict") not in {"OK", "OFF"}
    ]
    return "doctor-unhealthy-" + hashlib.sha256(
        json.dumps(signature, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]


def _survey_case(
    repo: Path,
    release: DistributionRelease,
    work_root: Path,
    *,
    node_runtime: NodeRuntime,
    python_runtime: PythonRuntime,
    install_timeout_seconds: int,
    doctor_timeout_seconds: int,
) -> dict[str, object]:
    """Install and preflight one disposable historic tree without invoking an update route."""

    case_name = safe_case_name(release)
    vault = work_root / case_name
    runtime_root = work_root / f"{case_name}.runtime"
    issues: list[dict[str, str]] = []
    identity = {**_release_manifest(release), "tag_object": _git(repo, "rev-parse", "--verify", release.tag)}
    result: dict[str, object] = {
        "identity": identity,
        "platform": {
            "sys_platform": sys.platform,
            "machine": platform.machine(),
            "python_version": platform.python_version(),
        },
        "shipped_update_surface": classify_historic_update_surface(repo, release),
        "fixture_install": {"status": "not-run", "code": "not-run"},
        "doctor_preflight": {"status": "not-run", "code": "not-run"},
        "fixture_retained": False,
        "issues": issues,
    }
    try:
        environment = _case_environment(
            vault,
            runtime_root,
            node_runtime=node_runtime,
            python_runtime=python_runtime,
            pip_cache_dir=work_root / ".controller-cache/pip",
            controller_root=work_root / ".controller-cache",
        )
        _create_fixture_vault(repo, release, work_root, environment=environment)
        release_commit, release_tree = _prepare_installer_release_remote(
            repo, vault, release, environment
        )
        try:
            install_code = _run_historic_installer(
                vault,
                release,
                environment,
                timeout_seconds=install_timeout_seconds,
                official_release_commit=release_commit,
                official_release_tree=release_tree,
            )
        except subprocess.TimeoutExpired as error:
            result["fixture_install"] = {
                "status": "failed",
                "code": "installer-timeout",
                "stdout": _output_fingerprint(error.stdout if isinstance(error.stdout, str) else None),
                "stderr": _output_fingerprint(error.stderr if isinstance(error.stderr, str) else None),
            }
            issues.append(_survey_issue("fixture-install", "installer-timeout"))
            return result
        except FleetError as error:
            code = (
                "installer-missing"
                if "no safe install.sh" in str(error)
                else _installer_failure_code(error)
            )
            result["fixture_install"] = {"status": "failed", "code": code}
            issues.append(_survey_issue("fixture-install", code))
            return result
        result["fixture_install"] = {"status": "ok", "code": install_code}
        try:
            fixture_python = resolve_fixture_python(vault, trusted_python=python_runtime)
        except FleetError as error:
            code = (
                "doctor-fixture-python-untrusted"
                if "does not bind" in str(error) or "does not match" in str(error)
                else "doctor-fixture-python-unavailable"
            )
            doctor = {
                "status": "failed",
                "code": code,
                "requested_interpreter": str(vault / ".venv" / "bin" / "python"),
            }
        else:
            doctor = _doctor_preflight(
                vault,
                environment,
                fixture_python=fixture_python,
                timeout_seconds=doctor_timeout_seconds,
            )
        result["doctor_preflight"] = doctor
        if doctor["status"] != "ok":
            issues.append(_survey_issue("doctor-preflight", str(doctor["code"])))
        return result
    except FleetError:
        result["fixture_install"] = {"status": "failed", "code": "fixture-create-failed"}
        issues.append(_survey_issue("fixture-install", "fixture-create-failed"))
        return result
    except OSError:
        result["fixture_install"] = {"status": "failed", "code": "fixture-os-error"}
        issues.append(_survey_issue("fixture-install", "fixture-os-error"))
        return result
    finally:
        _remove_disposable_fixture(vault, work_root)
        _remove_disposable_fixture(runtime_root, work_root)


def run_discovery_sweep(
    repo: Path,
    *,
    releases: Sequence[DistributionRelease],
    output: Path,
    workers: int,
    install_timeout_seconds: int,
    doctor_timeout_seconds: int,
) -> dict[str, object]:
    """Survey historic fixtures and return diagnostic coverage, never acceptance evidence."""

    if workers < 1 or workers > DISCOVERY_MAX_WORKERS:
        raise FleetError(f"survey workers must be between 1 and {DISCOVERY_MAX_WORKERS}")
    if install_timeout_seconds < 1 or doctor_timeout_seconds < 1:
        raise FleetError("survey timeouts must be positive")
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise FleetError("survey output must be a safe directory")
    if output.exists() and any(output.iterdir()):
        raise FleetError("survey output directory must be empty")
    node_runtime = resolve_trusted_node_runtime()
    python_runtime = resolve_trusted_python_runtime()
    output.mkdir(parents=True, exist_ok=True)
    work_root = output / DISCOVERY_WORK_NAME
    work_root.mkdir(mode=0o700)
    cases: list[dict[str, object]] = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            submitted = [
                executor.submit(
                    _survey_case,
                    repo,
                    release,
                    work_root,
                    node_runtime=node_runtime,
                    python_runtime=python_runtime,
                    install_timeout_seconds=install_timeout_seconds,
                    doctor_timeout_seconds=doctor_timeout_seconds,
                )
                for release in releases
            ]
            for submitted_case in submitted:
                cases.append(submitted_case.result())
    finally:
        _remove_disposable_fixture(work_root, output)
    grouped: dict[str, list[str]] = {}
    for case in cases:
        identity = case["identity"]
        assert isinstance(identity, Mapping)
        tag = identity["tag"]
        assert isinstance(tag, str)
        issues = case["issues"]
        assert isinstance(issues, list)
        for issue in issues:
            assert isinstance(issue, Mapping)
            key = f"{issue['stage']}:{issue['code']}"
            grouped.setdefault(key, []).append(tag)
    return {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "outcome": "NON_ACCEPTANCE_DISCOVERY",
        "acceptance": False,
        "executed_count": len(cases),
        "expected_count": len(releases),
        "platform": {
            "sys_platform": sys.platform,
            "machine": platform.machine(),
            "python_version": platform.python_version(),
        },
        "fixture_runtime": {
            "node": node_runtime.identity(),
            "python": python_runtime.identity(),
        },
        "root_causes": [
            {"key": key, "count": len(tags), "tags": sorted(tags)}
            for key, tags in sorted(grouped.items())
        ],
        "cases": cases,
    }


def _verify_standalone_bridge_asset(
    repo: Path,
    *,
    source_commit: str,
    follow_up: ImmutableRelease,
    protocol: UpdateJourneyProtocol,
    bridge_asset: Path | None,
    bridge_checksum: Path | None,
) -> dict[str, str]:
    """Bind acceptance to the separately distributable release bridge."""

    if bridge_asset is None or bridge_checksum is None:
        raise FleetError("standalone released bridge asset is required")
    expected_asset_name = f"dex-update-bridge-v{follow_up.version}.py"
    expected_checksum_name = f"{expected_asset_name}.sha256"
    if bridge_asset.name != expected_asset_name or bridge_checksum.name != expected_checksum_name:
        raise FleetError("standalone released bridge asset names do not match follow-up release")
    for label, path in (("bridge asset", bridge_asset), ("bridge checksum", bridge_checksum)):
        if path.is_symlink() or not path.is_file():
            raise FleetError(f"standalone released {label} is missing or unsafe")
    bridge_bytes = bridge_asset.read_bytes()
    bridge_digest = hashlib.sha256(bridge_bytes).hexdigest()
    checksum_bytes = bridge_checksum.read_bytes()
    expected_checksum = f"{bridge_digest}  {expected_asset_name}\n".encode("utf-8")
    if checksum_bytes != expected_checksum:
        raise FleetError("standalone released bridge checksum is invalid")
    released_bridge = _tag_file(repo, source_commit, protocol.bridge.artifact.source_path)
    if bridge_digest != protocol.bridge.artifact.sha256 or bridge_bytes != released_bridge:
        raise FleetError("standalone released bridge does not match released journey source")
    return {
        "name": expected_asset_name,
        "sha256": bridge_digest,
        "checksum_name": expected_checksum_name,
        "checksum_sha256": hashlib.sha256(checksum_bytes).hexdigest(),
        "source": "released-standalone-asset",
    }


def _retained_tail(text: str) -> str:
    """Keep the end of a captured stream inside a fixed evidence bound."""

    if len(text) <= BRIDGE_PROCESS_ENTRY_RETAINED_BYTES:
        return text
    return text[-BRIDGE_PROCESS_ENTRY_RETAINED_BYTES:]


def assert_bridge_process_entry(
    evidence: Mapping[str, object],
    *,
    approval_word: str,
) -> None:
    """Refuse a released bridge that a stuck user cannot actually start.

    The stuck user's whole experience of this path is one command and whatever
    it prints. Every check below is that experience: the process has to finish,
    it has to relaunch itself exactly once into the vault runtime, it must never
    stop on a runtime-entry refusal, and it has to print the first approval gate
    rather than nothing at all. Silence was the reported symptom of the relaunch
    loop, so an empty stream is a failure in its own right.
    """

    problems: list[str] = []
    if evidence.get("timed_out"):
        problems.append(
            "it never finished within "
            f"{evidence.get('timeout_seconds')}s, which is how an unbounded "
            "relaunch loop presents"
        )
    if evidence.get("runtime_entry_refused"):
        problems.append("it stopped on a clean-runtime entry refusal")
    notices = evidence.get("relaunch_notice_count")
    if notices != 1:
        problems.append(
            f"it announced {notices} relaunches into the installed runtime instead of exactly one"
        )
    if not evidence.get("produced_output"):
        problems.append("it produced no output at all")
    if not evidence.get("reached_approval_gate"):
        problems.append(f"it never reached the first {approval_word} gate")
    if not problems:
        return
    raise FleetError(
        "the released bridge asset could not be started the way a stuck user starts it: "
        + "; ".join(problems)
        + f" | exit={evidence.get('exit_code')!r}"
        + f" | stdout tail: {str(evidence.get('stdout', ''))[-2000:]!r}"
        + f" | stderr tail: {str(evidence.get('stderr', ''))[-2000:]!r}"
    )


def probe_bridge_process_entry(
    *,
    vault: Path,
    bridge_asset: Path,
    python_runtime: PythonRuntime,
    environment: Mapping[str, str],
    approval_word: str,
    evidence_root: Path,
) -> dict[str, object]:
    """Start the published bridge as a top-level process against a real vault.

    This is deliberately the published asset, launched from the vault root with
    ``--vault`` and with stdin closed, so it runs the whole entry path -- the
    environment scrub, the ``execve`` into the vault virtualenv, and the
    clean-runtime equality check -- and then halts at the first approval gate
    without changing anything. The asset stays outside the vault so the fixture
    that the journey is about to update is not given an extra untracked file.
    """

    command = [
        str(python_runtime.requested_python),
        str(bridge_asset),
        "--vault",
        str(vault),
    ]
    timed_out = False
    exit_code: int | None = None
    try:
        completed = _run_bounded_process_group(
            command,
            cwd=vault,
            environment=environment,
            timeout_seconds=BRIDGE_PROCESS_ENTRY_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as error:
        timed_out = True
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = error.stderr if isinstance(error.stderr, str) else ""
    evidence: dict[str, object] = {
        "schema_version": 1,
        "command": [str(bridge_asset.name), "--vault", str(vault)],
        "interpreter": str(python_runtime.requested_python),
        "working_directory": str(vault),
        "stdin": "closed",
        "timeout_seconds": BRIDGE_PROCESS_ENTRY_TIMEOUT_SECONDS,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "relaunch_notice_count": stderr.count(BRIDGE_PROCESS_ENTRY_NOTICE),
        "runtime_entry_refused": BRIDGE_PROCESS_ENTRY_REFUSAL in stderr,
        "reached_approval_gate": f"Type {approval_word} to continue:" in stdout,
        "produced_output": bool(stdout.strip()),
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
        "stdout": _retained_tail(stdout),
        "stderr": _retained_tail(stderr),
    }
    # Retain the streams even when the assertion below fails: silence was the
    # original symptom, so the captured output is the evidence that matters.
    evidence_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    (evidence_root / "bridge-process-entry-stdout.txt").write_text(
        _retained_tail(stdout), encoding="utf-8"
    )
    (evidence_root / "bridge-process-entry-stderr.txt").write_text(
        _retained_tail(stderr), encoding="utf-8"
    )
    _write_json(evidence_root / "bridge-process-entry.json", evidence)
    assert_bridge_process_entry(evidence, approval_word=approval_word)
    return evidence


def run_case_executor(
    starting_tag: str,
    executor: Callable[..., object],
    /,
    **kwargs: object,
) -> object:
    """Collect only a failure from an executor that crossed the case boundary."""

    from scripts import release_fleet_executor

    case_execution_started = False

    def mark_case_execution_started() -> None:
        nonlocal case_execution_started
        case_execution_started = True

    try:
        return executor(_case_started=mark_case_execution_started, **kwargs)
    except release_fleet_executor.PublicRouteDriftError:
        raise
    except release_fleet_executor.ExecutorError as error:
        if not case_execution_started:
            raise
        raise CaseJourneyFailure(starting_tag, str(error)) from error


def run_journey(
    repo: Path,
    *,
    output: Path,
    starting_tag: str,
    foundation_tag: str,
    follow_up_tag: str,
    bridge_asset: Path | None = None,
    bridge_checksum: Path | None = None,
    controlled_approvals: bool = False,
    follow_up_cache: Path | None = None,
    bridge_process_entry: bool = False,
) -> object:
    """Build one fixture and delegate the closed journey to its released executor."""

    if sys.platform == "darwin":
        journey_platform = "darwin"
    elif sys.platform.startswith("linux"):
        journey_platform = "linux"
    else:
        raise FleetError("released journey executor supports macOS and Linux only")
    releases = {release.tag: release for release in discover_distribution_releases(repo)}
    start = releases.get(starting_tag)
    if start is None:
        raise FleetError(f"historic distribution tag was not found: {starting_tag}")
    foundation = resolve_immutable_release(repo, foundation_tag)
    follow_up = resolve_immutable_release(repo, follow_up_tag)
    if foundation.tag == follow_up.tag or foundation.commit == follow_up.commit:
        raise FleetError("foundation and follow-up must be different immutable releases")
    protocol_bytes = _optional_tag_file(repo, follow_up.tag, UPDATE_JOURNEY_RELATIVE)
    if protocol_bytes is None:
        raise FleetError("follow-up release has no released journey executor")
    try:
        protocol = load_update_journey_protocol(protocol_bytes)
    except JourneyProtocolError as error:
        raise FleetError(f"follow-up released journey protocol is invalid: {error}") from error
    if protocol.foundation != foundation.identity():
        raise FleetError("released journey protocol names a different foundation")
    approval_input: Callable[[str], str] | None = None
    if controlled_approvals:
        bridge_word = protocol.bridge.approval_word
        follow_up_word = protocol.follow_up.approval_word
        if bridge_word != follow_up_word:
            raise FleetError("controlled fleet approvals require one exact protocol word")

        def approve_disposable_fixture(prompt: str) -> str:
            if not isinstance(prompt, str) or not prompt:
                raise FleetError("controlled fleet approval prompt is invalid")
            return bridge_word

        approval_input = approve_disposable_fixture
    source_commit = _verify_released_protocol_artifacts(repo, follow_up, protocol)
    bridge_asset_evidence = _verify_standalone_bridge_asset(
        repo,
        source_commit=source_commit,
        follow_up=follow_up,
        protocol=protocol,
        bridge_asset=bridge_asset,
        bridge_checksum=bridge_checksum,
    )
    assert bridge_asset is not None
    for label, artifact, running_path in (
        ("fleet runner", protocol.runner, Path(__file__).resolve()),
        (
            "journey executor",
            protocol.executor,
            PROJECT_ROOT / protocol.executor.source_path,
        ),
    ):
        running = running_path.read_bytes()
        released = _tag_file(repo, source_commit, artifact.source_path)
        if (
            hashlib.sha256(running).hexdigest() != artifact.sha256
            or running != released
        ):
            raise FleetError(
                f"running {label} bytes do not match the released journey source"
            )

    # Evidence must not become an untracked vault file that influences either
    # release preview. Keep it beside the disposable fixture.
    evidence_relative = f"{safe_case_name(start)}.evidence"
    evidence_root = output / evidence_relative
    if evidence_root.exists():
        raise FleetError("journey evidence directory must be empty")
    case_name = safe_case_name(start)
    vault = output / case_name
    runtime_root = output / f"{case_name}.runtime"
    historic_surface = shipped_update_surface(repo, start)
    foundation_surface = shipped_update_surface(repo, foundation)
    node_runtime = resolve_trusted_node_runtime()
    python_runtime = resolve_trusted_python_runtime()
    environment = _case_environment(
        vault,
        runtime_root,
        node_runtime=node_runtime,
        python_runtime=python_runtime,
        pip_cache_dir=output / ".fixture-controller/pip",
        controller_root=output / ".fixture-controller",
    )
    try:
        case = build_installed_fixture(
            repo,
            start,
            output,
            environment=environment,
            keep_official_fetch=True,
        )
        resolve_fixture_python(
            case.vault,
            trusted_python=python_runtime,
            required_dependencies=PRE_BRIDGE_REQUIRED_PYTHON_DEPENDENCIES,
        )
        if bridge_process_entry:
            # Read-only: the run stops at the first approval gate, so the vault
            # the journey is about to update is left exactly as installed. Its
            # evidence lives beside the fixture rather than inside the sealed
            # journey evidence the executor owns.
            probe_bridge_process_entry(
                vault=case.vault,
                bridge_asset=bridge_asset.resolve(strict=True),
                python_runtime=python_runtime,
                environment=environment,
                approval_word=protocol.bridge.approval_word,
                evidence_root=output / f"{case_name}{BRIDGE_PROCESS_ENTRY_SUFFIX}",
            )
        initial_install_evidence = _initial_install_evidence(case.vault, environment)
        from scripts import release_fleet_executor

        try:
            if not _installer_created_split_topology(case.vault):
                _prepare_installer_release_remote(
                    repo,
                    case.vault,
                    start,
                    environment,
                )
            return run_case_executor(
                start.tag,
                release_fleet_executor.execute_journey,
                repo_root=repo,
                source_commit=source_commit,
                vault_root=case.vault,
                evidence_root=evidence_root,
                starting_release=historic_surface["release"],
                foundation_release=foundation.identity(),
                follow_up_release=follow_up.identity(),
                protocol=protocol,
                historic_surface=historic_surface,
                foundation_surface=foundation_surface,
                user_owned_paths=tuple(USER_FIXTURES),
                platform=journey_platform,
                bridge_asset_evidence=bridge_asset_evidence,
                bridge_asset_path=bridge_asset.resolve(strict=True),
                initial_install_evidence=initial_install_evidence,
                follow_up_cache=follow_up_cache,
                **({"input_fn": approval_input} if approval_input is not None else {}),
            )
        finally:
            _disable_all_fixture_remotes(case.vault, environment)
    finally:
        _remove_disposable_fixture(vault, output)
        _remove_disposable_fixture(runtime_root, output)


def assert_complete(report: AcceptanceReport, expected_start_tags: set[str]) -> None:
    """Refuse a release claim unless every historic package completed both hops."""

    if not report.cases:
        raise FleetError("acceptance report contains no historic releases")
    if report.platforms and len(set(report.platforms)) != len(report.platforms):
        raise FleetError("acceptance report has invalid platform coverage")
    actual_tags = {case.starting_tag for case in report.cases}
    missing = sorted(expected_start_tags - actual_tags)
    if missing:
        raise FleetError("acceptance report is missing historic releases: " + ", ".join(missing))
    unexpected = sorted(actual_tags - expected_start_tags)
    if unexpected:
        raise FleetError("acceptance report contains unknown historic releases: " + ", ".join(unexpected))

    for case in report.cases:
        if not case.reached_foundation:
            raise FleetError(f"{case.starting_tag}: foundation release was not reached")
        if not case.reached_follow_up:
            raise FleetError(f"{case.starting_tag}: follow-up release was not reached")
        if not case.foundation_doctor_healthy:
            raise FleetError(f"{case.starting_tag}: Doctor was unhealthy after foundation release")
        if not case.follow_up_doctor_healthy:
            raise FleetError(f"{case.starting_tag}: Doctor was unhealthy after follow-up release")
        if not case.user_hashes_before:
            raise FleetError(f"{case.starting_tag}: user-content evidence is missing")
        if case.user_hashes_before != case.user_hashes_after_foundation:
            raise FleetError(f"{case.starting_tag}: user content changed during foundation release")
        if case.user_hashes_before != case.user_hashes_after_follow_up:
            raise FleetError(f"{case.starting_tag}: user content changed during follow-up release")
        if not case.transcript_path:
            raise FleetError(f"{case.starting_tag}: user-visible journey transcript is missing")
        if report.platforms and case.platform not in report.platforms:
            raise FleetError(f"{case.starting_tag}: platform is not declared in report coverage")
    if report.platforms:
        expected_cases = {(tag, platform) for tag in expected_start_tags for platform in report.platforms}
        actual_cases = {(case.starting_tag, case.platform) for case in report.cases}
        if len(actual_cases) != len(report.cases):
            raise FleetError("acceptance report contains a duplicate historic release/platform case")
        if actual_cases != expected_cases:
            raise FleetError("acceptance report has incomplete historic release platform coverage")
    elif len(actual_tags) != len(report.cases):
        raise FleetError("acceptance report contains a duplicate historic release")


def _evidence_file(root: Path, relative: str, context: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise FleetError(f"{context} must be a relative evidence path")
    path = root / candidate
    if path.is_symlink() or not path.is_file() or path.resolve().parent != path.parent.resolve():
        raise FleetError(f"{context} is missing or unsafe")
    return path


def _read_evidence_json(root: Path, relative: str, context: str) -> dict[str, object]:
    path = _evidence_file(root, relative, context)
    return _strict_object(path.read_bytes(), context, frozenset({"release", "receipt"}))


def _manifest_artifact(
    root: Path,
    artifacts: Mapping[str, object],
    name: str,
    context: str,
) -> str:
    """Open one content-addressed runner artifact and return its safe relative path."""

    value = artifacts.get(name)
    if not isinstance(value, Mapping) or set(value) != {"path", "sha256"}:
        raise FleetError(f"{context}: runner manifest has no valid {name} artifact")
    path = value.get("path")
    digest = value.get("sha256")
    if not isinstance(path, str) or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise FleetError(f"{context}: runner manifest has an invalid {name} artifact")
    artifact = _evidence_file(root, path, f"{context} {name} artifact")
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != digest:
        raise FleetError(f"{context}: {name} artifact hash does not match runner manifest")
    return path


def assert_evidence_bound(
    report: AcceptanceReport,
    *,
    repo: Path,
    evidence_root: Path,
    foundation: ImmutableRelease,
    follow_up: ImmutableRelease,
    executor_runs: Sequence[object] = (),
) -> None:
    """Open runner-owned evidence and bind it to released source bytes."""

    from scripts import release_fleet_executor

    if len(executor_runs) != len(report.cases) or any(
        not release_fleet_executor.is_authoritative_executor_run(run)
        for run in executor_runs
    ):
        raise FleetError(
            "released journey executor authority is required in this live process; "
            "serialized evidence cannot substitute for execution"
        )
    authoritative_cases = [run.case for run in executor_runs]  # type: ignore[attr-defined]
    expected_cases = [
        {
            field: getattr(case, field)
            for field in CASE_RESULT_KEYS
        }
        for case in report.cases
    ]
    if authoritative_cases != expected_cases:
        raise FleetError(
            "released journey executor authority does not match the acceptance report"
        )

    releases = {release.tag: release for release in discover_distribution_releases(repo)}

    for case in report.cases:
        starting_release = releases.get(case.starting_tag)
        if starting_release is None:
            raise FleetError(f"{case.starting_tag}: starting release is no longer discoverable")
        expected_historic_surface = shipped_update_surface(repo, starting_release)
        expected_foundation_surface = shipped_update_surface(repo, foundation)
        protocol_surface = shipped_update_surface(repo, follow_up)
        if protocol_surface["machine_executable"] is not True:
            raise FleetError(
                f"{case.starting_tag}: released journey executor is not implemented; "
                "a valid protocol alone cannot make fleet acceptance pass"
            )
        protocol = load_update_journey_protocol(
            _tag_file(repo, follow_up.tag, UPDATE_JOURNEY_RELATIVE)
        )
        source_commit = _verify_released_protocol_artifacts(repo, follow_up, protocol)
        if protocol.foundation != foundation.identity():
            raise FleetError(
                f"{case.starting_tag}: released journey protocol names a different foundation"
            )
        manifest_path = _evidence_file(
            evidence_root, case.evidence_manifest_path, f"{case.starting_tag} evidence manifest"
        )
        if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != case.evidence_manifest_sha256:
            raise FleetError(f"{case.starting_tag}: evidence manifest hash does not match")
        manifest = _strict_object(
            manifest_path.read_bytes(),
            f"{case.starting_tag} evidence manifest",
            EVIDENCE_MANIFEST_KEYS,
        )
        if (
            manifest["schema_version"] != 1
            or manifest["executor"]
            != {
                "source_commit": source_commit,
                "executor": {
                    "source_path": protocol.executor.source_path,
                    "sha256": protocol.executor.sha256,
                },
                "fleet_runner": {
                    "source_path": protocol.runner.source_path,
                    "sha256": protocol.runner.sha256,
                },
                "foundation_bridge": {
                    "source_path": protocol.bridge.artifact.source_path,
                    "sha256": protocol.bridge.artifact.sha256,
                },
            }
            or not isinstance(manifest["starting_release"], Mapping)
            or manifest["starting_release"].get("tag") != case.starting_tag
            or manifest["foundation_release"] != foundation.identity()
            or manifest["follow_up_release"] != follow_up.identity()
            or not isinstance(manifest["events"], list)
            or not isinstance(manifest["artifacts"], Mapping)
        ):
            raise FleetError(f"{case.starting_tag}: evidence manifest is not bound to this journey")
        if any(not isinstance(event, Mapping) for event in manifest["events"]):
            raise FleetError(f"{case.starting_tag}: evidence manifest contains an invalid event")
        event_ids = [event.get("id") for event in manifest["events"]]
        required_order = [
            "historic-update-surface",
            "historic-route-refusal",
            "bridge-foundation",
            "foundation-update-surface",
            "foundation-preview",
            "foundation-approval",
            "foundation-receipt",
            "follow-up-installed",
            "follow-up-doctor",
            "follow-up-smoke",
        ]
        if event_ids != required_order:
            raise FleetError(f"{case.starting_tag}: evidence manifest has an invalid event order")
        events = {str(event["id"]): event for event in manifest["events"]}
        bridge_asset_name = f"dex-update-bridge-v{follow_up.version}.py"
        bridge_checksum_bytes = (
            f"{protocol.bridge.artifact.sha256}  {bridge_asset_name}\n".encode("utf-8")
        )
        expected_bridge_asset = {
            "name": bridge_asset_name,
            "sha256": protocol.bridge.artifact.sha256,
            "checksum_name": f"{bridge_asset_name}.sha256",
            "checksum_sha256": hashlib.sha256(bridge_checksum_bytes).hexdigest(),
            "source": "released-standalone-asset",
        }
        if any(
            not isinstance(event.get("command"), list)
            or not event["command"]
            or any(not isinstance(part, str) or not part for part in event["command"])
            for event in events.values()
        ):
            raise FleetError(f"{case.starting_tag}: evidence manifest contains an invalid command")
        if (
            events["historic-update-surface"].get("command")
            != ["git", "show", f"{case.starting_tag}:{UPDATE_SKILL_RELATIVE}"]
            or events["historic-update-surface"].get("release") != expected_historic_surface["release"]
            or events["historic-update-surface"].get("skill_sha256")
            != expected_historic_surface["skill_sha256"]
            or events["historic-update-surface"].get("rescue_sha256")
            != expected_historic_surface["rescue_sha256"]
            or events["historic-route-refusal"].get("release") != expected_historic_surface["release"]
            or events["historic-route-refusal"].get("command")
            != [protocol.executor.source_path, "classify-historic-route"]
            or events["historic-route-refusal"].get("initial_install")
            not in (
                {"topology": "legacy-monolithic", "brain_refs": []},
                {
                    "topology": "brain-vault-split",
                    "brain_refs": ["refs/dex/installed"],
                },
                {
                    "topology": "brain-vault-split",
                    "brain_refs": ["refs/dex/installed", "refs/heads/release"],
                },
            )
            or events["bridge-foundation"].get("release") != foundation.identity()
            or events["bridge-foundation"].get("command")
            != [protocol.executor.source_path, protocol.bridge.adapter]
            or events["bridge-foundation"].get("bridge_asset")
            != expected_bridge_asset
            or events["foundation-update-surface"].get("release") != foundation.identity()
            or events["foundation-update-surface"].get("command")
            != ["git", "show", f"{foundation.tag}:{UPDATE_SKILL_RELATIVE}"]
            or events["foundation-update-surface"].get("skill_sha256")
            != expected_foundation_surface["skill_sha256"]
            or events["foundation-update-surface"].get("rescue_sha256")
            != expected_foundation_surface["rescue_sha256"]
            or events["foundation-preview"].get("from_release") != foundation.identity()
            or events["foundation-preview"].get("target_release") != follow_up.identity()
            or events["foundation-preview"].get("command")
            != list(protocol.follow_up.operations[:2])
            or events["foundation-approval"].get("target_release") != follow_up.identity()
            or events["foundation-approval"].get("answer") != "APPLY"
            or events["foundation-approval"].get("command")
            != [protocol.executor.source_path, "approve-follow-up"]
            or events["foundation-receipt"].get("release") != follow_up.identity()
            or events["foundation-receipt"].get("command")
            != [protocol.follow_up.operations[2]]
            or events["follow-up-installed"].get("release") != follow_up.identity()
            or events["follow-up-installed"].get("command")
            != [protocol.executor.source_path, "verify-installed-release"]
            or events["follow-up-doctor"].get("command")
            != [protocol.executor.source_path, "doctor"]
            or events["follow-up-smoke"].get("command")
            != [protocol.executor.source_path, "smoke"]
            or events["follow-up-smoke"].get("platform") != case.platform
        ):
            raise FleetError(f"{case.starting_tag}: evidence manifest commands or identities are not bound")
        bridge_approvals = events["bridge-foundation"].get("approvals")
        approval_count = events["bridge-foundation"].get("approval_count")
        if (
            not isinstance(approval_count, int)
            or approval_count < 0
            or approval_count > protocol.bridge.approval_count
            or not isinstance(bridge_approvals, list)
            or approval_count != len(bridge_approvals)
            or any(
                not isinstance(approval, Mapping)
                or set(approval) != {"prompt", "answer"}
                or not isinstance(approval["prompt"], str)
                or approval["answer"] != protocol.bridge.approval_word
                for approval in bridge_approvals
            )
        ):
            raise FleetError(f"{case.starting_tag}: bridge approvals are not exact")
        artifacts = manifest["artifacts"]
        if set(artifacts) != RUNNER_ARTIFACT_KEYS:
            raise FleetError(f"{case.starting_tag}: runner manifest has an invalid artifact set")
        artifact_paths = {
            name: _manifest_artifact(evidence_root, artifacts, name, case.starting_tag)
            for name in RUNNER_ARTIFACT_KEYS
        }
        if (
            artifact_paths["transcript"] != case.transcript_path
            or artifact_paths["foundation_receipt"] != case.foundation_receipt_path
            or artifact_paths["follow_up_receipt"] != case.follow_up_receipt_path
            or artifact_paths["foundation_doctor"] != case.foundation_doctor_path
            or artifact_paths["follow_up_doctor"] != case.follow_up_doctor_path
            or artifact_paths["follow_up_smoke"] != case.follow_up_smoke_path
        ):
            raise FleetError(f"{case.starting_tag}: evidence manifest artifacts are not bound")
        for artifact_name, expected_surface in (
            ("historic_update_surface", expected_historic_surface),
            ("foundation_update_surface", expected_foundation_surface),
        ):
            surface = _strict_object(
                _evidence_file(
                    evidence_root,
                    artifact_paths[artifact_name],
                    f"{case.starting_tag} {artifact_name}",
                ).read_bytes(),
                f"{case.starting_tag} {artifact_name}",
                frozenset(expected_surface),
            )
            if surface != expected_surface:
                raise FleetError(f"{case.starting_tag}: {artifact_name} is not the released update surface")
        transcript = _evidence_file(evidence_root, case.transcript_path, f"{case.starting_tag} transcript")
        transcript_value = _strict_object(transcript.read_bytes(), f"{case.starting_tag} transcript", frozenset({"events"}))
        if not isinstance(transcript_value["events"], list) or transcript_value["events"] != manifest["events"]:
            raise FleetError(f"{case.starting_tag}: transcript has no journey events")
        foundation_receipt = _read_evidence_json(
            evidence_root, case.foundation_receipt_path, f"{case.starting_tag} foundation receipt"
        )
        follow_receipt = _read_evidence_json(
            evidence_root, case.follow_up_receipt_path, f"{case.starting_tag} follow-up receipt"
        )
        if (
            foundation_receipt["release"] != foundation.identity()
            or not _valid_foundation_bridge_receipt(
                foundation_receipt["receipt"],
                expected_foundation=foundation.identity(),
                approval_count=approval_count,
            )
        ):
            raise FleetError(f"{case.starting_tag}: foundation receipt is not bound to the supplied release")
        if follow_receipt["release"] != follow_up.identity() or not _has_transaction_receipt(
            follow_receipt["receipt"]
        ):
            raise FleetError(f"{case.starting_tag}: follow-up receipt is not bound to the supplied release")
        for label, relative in (
            ("foundation Doctor", case.foundation_doctor_path),
            ("follow-up Doctor", case.follow_up_doctor_path),
        ):
            doctor = _evidence_file(evidence_root, relative, f"{case.starting_tag} {label}")
            try:
                doctor_value = json.loads(doctor.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise FleetError(f"{case.starting_tag}: {label} is not valid JSON") from error
            checks = doctor_value.get("checks") if isinstance(doctor_value, Mapping) else None
            if not isinstance(checks, list) or not checks or any(
                not isinstance(item, Mapping) or item.get("verdict") not in {"OK", "OFF"}
                for item in checks
            ):
                raise FleetError(f"{case.starting_tag}: {label} is unhealthy or incomplete")
        smoke = _evidence_file(evidence_root, case.follow_up_smoke_path, f"{case.starting_tag} smoke")
        try:
            smoke_value = json.loads(smoke.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise FleetError(f"{case.starting_tag}: smoke evidence is not valid JSON") from error
        if (
            not isinstance(smoke_value, Mapping)
            or smoke_value.get("status") != "OK"
            or smoke_value.get("platform") != case.platform
        ):
            raise FleetError(f"{case.starting_tag}: smoke/platform evidence is not bound")


def _required_string(value: Mapping[str, Any], key: str, context: str) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str) or not candidate:
        raise FleetError(f"{context} has no valid {key}")
    return candidate


def _hash_map(value: object, context: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise FleetError(f"{context} must be a non-empty object")
    hashes: dict[str, str] = {}
    for relative, digest in value.items():
        if (
            not isinstance(relative, str)
            or not relative
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise FleetError(f"{context} contains an invalid user-content hash")
        hashes[relative] = digest
    return hashes


def acceptance_report_from_json(source: str) -> AcceptanceReport:
    """Parse a strict, machine-readable two-release acceptance report."""

    try:
        raw = json.loads(source)
    except json.JSONDecodeError as error:
        raise FleetError("acceptance report is not valid JSON") from error
    if not isinstance(raw, Mapping) or set(raw) != REPORT_KEYS:
        raise FleetError("acceptance report has an invalid top-level shape")
    foundation_tag = _required_string(raw, "foundation_tag", "acceptance report")
    follow_up_tag = _required_string(raw, "follow_up_tag", "acceptance report")
    platforms_raw = raw.get("platforms")
    if (
        not isinstance(platforms_raw, list)
        or not platforms_raw
        or any(not isinstance(platform, str) or not platform for platform in platforms_raw)
    ):
        raise FleetError("acceptance report platforms must be a non-empty list of strings")
    cases_raw = raw.get("cases")
    if not isinstance(cases_raw, list):
        raise FleetError("acceptance report cases must be a list")

    cases: list[CaseResult] = []
    for index, case_raw in enumerate(cases_raw, start=1):
        context = f"acceptance case {index}"
        if not isinstance(case_raw, Mapping) or set(case_raw) != CASE_RESULT_KEYS:
            raise FleetError(f"{context} has an invalid shape")
        boolean_keys = (
            "reached_foundation",
            "reached_follow_up",
            "foundation_doctor_healthy",
            "follow_up_doctor_healthy",
        )
        if any(not isinstance(case_raw[key], bool) for key in boolean_keys):
            raise FleetError(f"{context} has an invalid boolean verdict")
        cases.append(
            CaseResult(
                starting_tag=_required_string(case_raw, "starting_tag", context),
                reached_foundation=bool(case_raw["reached_foundation"]),
                reached_follow_up=bool(case_raw["reached_follow_up"]),
                foundation_doctor_healthy=bool(case_raw["foundation_doctor_healthy"]),
                follow_up_doctor_healthy=bool(case_raw["follow_up_doctor_healthy"]),
                user_hashes_before=_hash_map(case_raw["user_hashes_before"], context),
                user_hashes_after_foundation=_hash_map(
                    case_raw["user_hashes_after_foundation"], context
                ),
                user_hashes_after_follow_up=_hash_map(
                    case_raw["user_hashes_after_follow_up"], context
                ),
                transcript_path=_required_string(case_raw, "transcript_path", context),
                foundation_receipt_path=_required_string(case_raw, "foundation_receipt_path", context),
                follow_up_receipt_path=_required_string(case_raw, "follow_up_receipt_path", context),
                foundation_doctor_path=_required_string(case_raw, "foundation_doctor_path", context),
                follow_up_doctor_path=_required_string(case_raw, "follow_up_doctor_path", context),
                follow_up_smoke_path=_required_string(case_raw, "follow_up_smoke_path", context),
                platform=_required_string(case_raw, "platform", context),
                evidence_manifest_path=_required_string(case_raw, "evidence_manifest_path", context),
                evidence_manifest_sha256=_required_string(case_raw, "evidence_manifest_sha256", context),
            )
        )
    return AcceptanceReport(foundation_tag, follow_up_tag, tuple(cases), tuple(platforms_raw))


def _case_manifest(case: FleetCase) -> dict[str, object]:
    return {
        "starting": _release_manifest(case.release),
        "vault": str(case.vault),
        "user_hashes": case.user_hashes,
    }


def _release_manifest(release: DistributionRelease) -> dict[str, str]:
    return {
        "tag": release.tag,
        "version": release.version,
        "commit": release.commit,
        "tree": release.tree,
    }


def starting_release_manifest(releases: Sequence[DistributionRelease]) -> dict[str, object]:
    """Return the generated, exact release-tree set that a fleet report must cover."""

    cases = [_release_manifest(release) for release in releases]
    return {"schema_version": 1, "case_count": len(cases), "cases": cases}


def releases_from_starting_manifest(
    source: str, *, current_releases: Sequence[DistributionRelease]
) -> tuple[DistributionRelease, ...]:
    """Parse a generated manifest and reject drift from the current immutable tags."""

    try:
        raw = json.loads(source)
    except json.JSONDecodeError as error:
        raise FleetError("historic release manifest is not valid JSON") from error
    if not isinstance(raw, Mapping) or set(raw) != STARTING_MANIFEST_KEYS or raw.get("schema_version") != 1:
        raise FleetError("historic release manifest has an invalid shape")
    cases = raw.get("cases")
    count = raw.get("case_count")
    if not isinstance(cases, list) or not isinstance(count, int) or count != len(cases):
        raise FleetError("historic release manifest has an invalid case count")
    parsed: list[DistributionRelease] = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, Mapping) or set(case) != STARTING_RELEASE_KEYS:
            raise FleetError(f"historic release manifest case {index} has an invalid shape")
        values = {name: case[name] for name in STARTING_RELEASE_KEYS}
        if any(not isinstance(value, str) or not value for value in values.values()):
            raise FleetError(f"historic release manifest case {index} has invalid values")
        parsed.append(
            DistributionRelease(
                tag=values["tag"],
                version=values["version"],
                commit=values["commit"],
                tree=values["tree"],
            )
        )
    if len({release.tag for release in parsed}) != len(parsed):
        raise FleetError("historic release manifest contains duplicate tags")
    expected = tuple(current_releases)
    if tuple(_release_manifest(release) for release in parsed) != tuple(
        _release_manifest(release) for release in expected
    ):
        raise FleetError("historic release manifest does not match the current immutable release trees")
    return tuple(parsed)


def main(argv: Sequence[str] | None = None) -> int:
    """Build, exercise, or validate deterministic historic release journeys."""

    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    manifest = subcommands.add_parser("manifest", help="list historic releases without cloning them")
    manifest.add_argument("--repo", type=Path, required=True)
    build = subcommands.add_parser("build", help="build clean historic-release fixtures")
    build.add_argument("--repo", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--starting-tag", help="build only this immutable historic release tag")
    check = subcommands.add_parser("check-report", help="fail closed on incomplete fleet evidence")
    check.add_argument("--repo", type=Path, required=True)
    check.add_argument(
        "--starting-manifest",
        type=Path,
        required=True,
        help="generated output from the manifest command for this exact immutable release set",
    )
    check.add_argument("report", type=Path)
    survey = subcommands.add_parser(
        "survey",
        help="non-acceptance discovery across disposable historic fixtures; never runs an update",
    )
    survey.add_argument("--repo", type=Path, required=True)
    survey.add_argument("--starting-manifest", type=Path, required=True)
    survey.add_argument("--output", type=Path, required=True)
    survey.add_argument("--jobs", type=int, default=2)
    survey.add_argument(
        "--installer-timeout-seconds", type=int, default=DISCOVERY_DEFAULT_INSTALL_TIMEOUT_SECONDS
    )
    survey.add_argument(
        "--doctor-timeout-seconds", type=int, default=DISCOVERY_DEFAULT_DOCTOR_TIMEOUT_SECONDS
    )
    journey = subcommands.add_parser(
        "journey",
        help="run one released, closed historic update journey",
    )
    journey.add_argument("--repo", type=Path, required=True)
    journey.add_argument("--output", type=Path, required=True)
    journey.add_argument("--starting-tag", required=True)
    journey.add_argument("--foundation-tag", required=True)
    journey.add_argument("--follow-up-tag", required=True)
    journey.add_argument("--bridge-asset", type=Path, required=True)
    journey.add_argument("--bridge-checksum", type=Path, required=True)
    journey.add_argument("--follow-up-cache", type=Path)
    journey.add_argument(
        "--controlled-approvals",
        action="store_true",
        help="approve only the disposable fixture used by a controlled fleet run",
    )
    journey.add_argument(
        "--bridge-process-entry",
        action="store_true",
        help=(
            "before the journey, start the published bridge asset as a top-level "
            "process against this fixture and require it to reach its first "
            "approval gate"
        ),
    )
    args = parser.parse_args(argv)

    if args.command == "manifest":
        releases = discover_distribution_releases(args.repo)
        print(
            json.dumps(
                starting_release_manifest(releases),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "build":
        releases = discover_distribution_releases(args.repo)
        if args.starting_tag:
            releases = tuple(release for release in releases if release.tag == args.starting_tag)
            if not releases:
                raise FleetError(f"historic distribution tag was not found: {args.starting_tag}")
        cases = [build_fixture(args.repo, release, args.output) for release in releases]
        print(
            json.dumps(
                {"case_count": len(cases), "cases": [_case_manifest(case) for case in cases]},
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "journey":
        run = run_journey(
            args.repo,
            output=args.output,
            starting_tag=args.starting_tag,
            foundation_tag=args.foundation_tag,
            follow_up_tag=args.follow_up_tag,
            bridge_asset=args.bridge_asset,
            bridge_checksum=args.bridge_checksum,
            controlled_approvals=args.controlled_approvals,
            follow_up_cache=args.follow_up_cache,
            bridge_process_entry=args.bridge_process_entry,
        )
        print(
            json.dumps(
                {
                    "outcome": "JOURNEY_COMPLETE_NON_ACCEPTANCE",
                    "acceptance": False,
                    "case": run.case,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "survey":
        releases = releases_from_starting_manifest(
            args.starting_manifest.read_text(encoding="utf-8"),
            current_releases=discover_distribution_releases(args.repo),
        )
        discovery = run_discovery_sweep(
            args.repo,
            releases=releases,
            output=args.output,
            workers=args.jobs,
            install_timeout_seconds=args.installer_timeout_seconds,
            doctor_timeout_seconds=args.doctor_timeout_seconds,
        )
        artifact = args.output / DISCOVERY_OUTPUT_NAME
        _write_json(artifact, discovery)
        print(
            json.dumps(
                {
                    "outcome": "NON_ACCEPTANCE_DISCOVERY",
                    "acceptance": False,
                    "executed_count": discovery["executed_count"],
                    "expected_count": discovery["expected_count"],
                    "artifact": str(artifact),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    report = acceptance_report_from_json(args.report.read_text(encoding="utf-8"))
    foundation = resolve_immutable_release(args.repo, report.foundation_tag)
    follow_up = resolve_immutable_release(args.repo, report.follow_up_tag)
    if foundation.tag == follow_up.tag or foundation.commit == follow_up.commit:
        raise FleetError("acceptance report foundation and follow-up are not distinct immutable releases")
    generated_starting_releases = releases_from_starting_manifest(
        args.starting_manifest.read_text(encoding="utf-8"),
        current_releases=discover_distribution_releases(args.repo),
    )
    expected_start_tags = {release.tag for release in generated_starting_releases}
    assert_complete(report, expected_start_tags)
    assert_evidence_bound(
        report,
        repo=args.repo,
        evidence_root=args.report.parent.resolve(),
        foundation=foundation,
        follow_up=follow_up,
    )
    print(f"PASS: {len(report.cases)} historic release trees reached both releases")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FleetError as error:
        raise SystemExit(f"FAIL: {error}") from error
