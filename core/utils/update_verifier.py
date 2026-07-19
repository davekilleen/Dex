#!/usr/bin/env python3
"""Bounded, fail-closed evidence checks for Dex release awareness.

This module deliberately does not authenticate a publisher and never changes the
installed repository. Git is used only against an isolated bare object cache.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Protocol

CANONICAL_REMOTE_URL = "https://github.com/davekilleen/Dex.git"
CANONICAL_RELEASE_PAGE = "https://github.com/davekilleen/Dex/releases/tag/{tag}"
PROFILE_PATH = "System/.release-evidence-profile.json"
MANIFEST_PATH = "System/.installed-files.manifest"
CATALOG_PATH = "System/.release-catalog.json"
NOTICE_CAUTION = (
    "A newer Dex release appears to exist, but Dex has not authenticated its publisher. "
    "Review the exact release/tag before choosing to update."
)
NOTICE_GUIDANCE = "Run /dex-doctor to review this evidence and update guidance. Dex will not update automatically."

STATUS_RELEASE = "release-appears-available-unverified"
STATUS_NONE = "no-newer-release-observed-unverified"
STATUS_OFFLINE = "offline"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_SKIPPED = "skipped"

_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_TAG_RE = re.compile(
    r"^dist/release/v(?P<version>(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))"
    r"-(?P<short>[0-9a-f]{7,64})$"
)
_HEX_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_OFFLINE_MARKERS = (
    "could not resolve host",
    "failed to connect",
    "network is unreachable",
    "connection timed out",
    "connection refused",
    "couldn't connect to server",
    "temporary failure in name resolution",
)
_FORBIDDEN_GIT_ENV_NAMES = {
    "ALL_PROXY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "SSH_AUTH_SOCK",
}
SESSION_WALL_CLOCK_SECONDS = 10.0
MAX_AGGREGATE_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_GIT_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_REMOTE_RELEASE_REFS = 128
# Normal operation has one higher stable target. Thirty-two preserves ample
# overlap for skipped releases and same-version ambiguity checks while keeping
# adversarial tag fan-out within the single SessionStart deadline/disk budget.
MAX_RELEASE_TAGS = 32
MAX_RELEASE_TREE_ENTRIES = 100_000
MAX_RELEASE_TREE_PATH_BYTES = 16 * 1024 * 1024
MAX_QUARANTINE_BYTES = 128 * 1024 * 1024
MAX_QUARANTINE_FILES = 20_000
MAX_QUARANTINE_OBJECTS = 20_000
MAX_STATE_BYTES = 1024 * 1024
MAX_PROFILE_BYTES = 64 * 1024
MAX_PACKAGE_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_CATALOG_BYTES = 16 * 1024 * 1024
MAX_COMPATIBILITY_BYTES = 16 * 1024 * 1024
MAX_TAG_OBJECT_BYTES = 64 * 1024
_CACHE_CONFIG = b"[core]\n\trepositoryformatversion = 0\n\tbare = true\n"


class EvidenceError(RuntimeError):
    """Release evidence is malformed, contradictory, or unsupported."""


class OfflineError(RuntimeError):
    """The bounded canonical network operation could not complete."""


class CancelledError(RuntimeError):
    """The caller cancelled the evidence operation."""


class PublisherAuthenticator(Protocol):
    """Future publisher-authentication seam; SR1 selects no authenticator."""

    def authenticate(self, candidate: "CandidateEvidence") -> str:
        """Return an authenticator-specific state without changing evidence."""


class NoPublisherAuthenticator:
    """Explicit SR1 authenticator: authentication is unavailable."""

    def authenticate(self, candidate: "CandidateEvidence") -> str:
        del candidate
        return "unavailable"


@dataclass(frozen=True, order=True)
class SemVer:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: object) -> "SemVer":
        if not isinstance(value, str):
            raise EvidenceError("release version is not a string")
        match = _SEMVER_RE.fullmatch(value)
        if match is None:
            raise EvidenceError("release version is not canonical semantic versioning")
        return cls(*(int(part) for part in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class CompatibilityArtifact:
    path: str
    contract_version: int
    sha256: str


@dataclass(frozen=True)
class ReleaseEvidenceProfile:
    schema_version: int
    profile: str
    release_version: str
    catalog_contract_version: int | None = None
    catalog_sha256: str | None = None
    compatibility_metadata: tuple[CompatibilityArtifact, ...] = ()


@dataclass(frozen=True)
class CandidateEvidence:
    version: str
    tag: str
    commit: str
    tree: str
    profile: str

    @property
    def identity(self) -> str:
        return f"{self.version}|{self.tag}|{self.commit}|{self.tree}|{self.profile}"

    @property
    def legacy_identity(self) -> str:
        return f"{self.version}|{self.tag}|{self.commit}|{self.profile}"


@dataclass
class ExecutionBudget:
    deadline: float
    output_bytes_remaining: int = MAX_AGGREGATE_OUTPUT_BYTES
    monitored_path: Path | None = None

    @classmethod
    def start(cls, seconds: float = SESSION_WALL_CLOCK_SECONDS) -> "ExecutionBudget":
        return cls(time.monotonic() + seconds, MAX_AGGREGATE_OUTPUT_BYTES)

    def check_deadline(self, *, network: bool = False) -> None:
        if time.monotonic() >= self.deadline:
            if network:
                raise OfflineError("bounded canonical operation exceeded the session deadline")
            raise EvidenceError("release evidence check exceeded the session deadline")

    def consume_output(self, count: int) -> None:
        self.output_bytes_remaining -= count
        if self.output_bytes_remaining < 0:
            raise EvidenceError("aggregate Git evidence output exceeded its bound")


def _json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_closed_json(raw: bytes, *, description: str) -> dict[str, object]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, EvidenceError) as error:
        raise EvidenceError(f"{description} is not canonical JSON: {error}") from error
    if not isinstance(value, dict):
        raise EvidenceError(f"{description} must be a JSON object")
    canonical = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if raw != canonical:
        raise EvidenceError(f"{description} is not in canonical JSON form")
    return value


def canonical_profile_bytes(profile: ReleaseEvidenceProfile) -> bytes:
    value: dict[str, object] = {
        "profile": profile.profile,
        "release_version": profile.release_version,
        "schema_version": profile.schema_version,
    }
    if profile.profile == "catalog-v1":
        value.update(
            {
                "catalog_contract_version": profile.catalog_contract_version,
                "catalog_sha256": profile.catalog_sha256,
                "compatibility_metadata": [
                    {
                        "contract_version": artifact.contract_version,
                        "path": artifact.path,
                        "sha256": artifact.sha256,
                    }
                    for artifact in profile.compatibility_metadata
                ],
            }
        )
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def legacy_profile_bytes(release_version: str) -> bytes:
    SemVer.parse(release_version)
    return canonical_profile_bytes(ReleaseEvidenceProfile(1, "legacy-v1", release_version))


def write_legacy_profile(destination: Path, release_version: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(legacy_profile_bytes(release_version))


def _validate_relative_artifact_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or any(ord(char) < 32 for char in value):
        raise EvidenceError("compatibility artifact path is not canonical")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(part in {"", ".", ".."} for part in path.parts):
        raise EvidenceError("compatibility artifact path escapes the release tree")
    if value in {PROFILE_PATH, MANIFEST_PATH, CATALOG_PATH}:
        raise EvidenceError("compatibility artifact path overlaps release evidence")
    return value


def parse_profile(raw: bytes, *, expected_version: str) -> ReleaseEvidenceProfile:
    value = _load_closed_json(raw, description="release evidence profile")
    base_keys = {"schema_version", "profile", "release_version"}
    profile_name = value.get("profile")
    if profile_name == "legacy-v1":
        if set(value) != base_keys:
            raise EvidenceError("legacy-v1 contains unknown or catalog-only fields")
        profile = ReleaseEvidenceProfile(
            schema_version=value.get("schema_version"),  # type: ignore[arg-type]
            profile=profile_name,
            release_version=value.get("release_version"),  # type: ignore[arg-type]
        )
    elif profile_name == "catalog-v1":
        expected_keys = base_keys | {"catalog_contract_version", "catalog_sha256", "compatibility_metadata"}
        if set(value) != expected_keys:
            raise EvidenceError("catalog-v1 fields are missing or unknown")
        contract_version = value.get("catalog_contract_version")
        catalog_sha256 = value.get("catalog_sha256")
        metadata = value.get("compatibility_metadata")
        if isinstance(contract_version, bool) or not isinstance(contract_version, int) or contract_version < 1:
            raise EvidenceError("catalog contract version is invalid")
        if not isinstance(catalog_sha256, str) or _HEX_HASH_RE.fullmatch(catalog_sha256) is None:
            raise EvidenceError("catalog hash is invalid")
        if not isinstance(metadata, list):
            raise EvidenceError("compatibility metadata must be a list")
        artifacts: list[CompatibilityArtifact] = []
        for item in metadata:
            if not isinstance(item, dict) or set(item) != {"path", "contract_version", "sha256"}:
                raise EvidenceError("compatibility metadata entry is not closed")
            artifact_contract = item.get("contract_version")
            artifact_hash = item.get("sha256")
            if isinstance(artifact_contract, bool) or not isinstance(artifact_contract, int) or artifact_contract < 1:
                raise EvidenceError("compatibility contract version is invalid")
            if not isinstance(artifact_hash, str) or _HEX_HASH_RE.fullmatch(artifact_hash) is None:
                raise EvidenceError("compatibility artifact hash is invalid")
            artifacts.append(
                CompatibilityArtifact(
                    path=_validate_relative_artifact_path(item.get("path")),
                    contract_version=artifact_contract,
                    sha256=artifact_hash,
                )
            )
        if [artifact.path for artifact in artifacts] != sorted({artifact.path for artifact in artifacts}):
            raise EvidenceError("compatibility metadata must be uniquely sorted by path")
        profile = ReleaseEvidenceProfile(
            schema_version=value.get("schema_version"),  # type: ignore[arg-type]
            profile=profile_name,
            release_version=value.get("release_version"),  # type: ignore[arg-type]
            catalog_contract_version=contract_version,
            catalog_sha256=catalog_sha256,
            compatibility_metadata=tuple(artifacts),
        )
    else:
        raise EvidenceError("release evidence profile is unknown")

    if profile.schema_version != 1:
        raise EvidenceError("release evidence schema version is unsupported")
    SemVer.parse(profile.release_version)
    if profile.release_version != expected_version:
        raise EvidenceError("release evidence profile version contradicts the tag")
    if raw != canonical_profile_bytes(profile):
        raise EvidenceError("release evidence profile content is inconsistent")
    return profile


def _sanitized_git_environment() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_") and key.upper() not in _FORBIDDEN_GIT_ENV_NAMES
    }
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "",
            "GIT_SSH_COMMAND": "false",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "LC_ALL": "C",
        }
    )
    return env


class GitRunner:
    """Absolute, sanitized, bounded Git subprocess runner."""

    def __init__(
        self,
        git_path: Path | None = None,
        *,
        timeout_seconds: float = 10.0,
        cancelled: Callable[[], bool] | None = None,
        allowed_protocol: str = "https",
        command_observer: Callable[[tuple[str, ...]], None] | None = None,
    ) -> None:
        discovered = str(git_path) if git_path is not None else shutil.which("git")
        if not discovered:
            raise EvidenceError("an absolute Git executable is unavailable")
        resolved = Path(discovered).resolve()
        if not resolved.is_absolute() or not resolved.is_file():
            raise EvidenceError("the Git executable is not an absolute regular file")
        self.git_path = resolved
        self.timeout_seconds = timeout_seconds
        self.cancelled = cancelled or (lambda: False)
        self.allowed_protocol = allowed_protocol
        self.command_observer = command_observer
        self.budget: ExecutionBudget | None = None

    def use_budget(self, budget: ExecutionBudget) -> None:
        self.budget = budget

    @staticmethod
    def _bounded_directory_usage(path: Path) -> tuple[int, int]:
        total_bytes = 0
        total_files = 0
        for root, directories, files in os.walk(path, followlinks=False):
            if any((Path(root) / name).is_symlink() for name in directories):
                raise EvidenceError("release quarantine contains a symlinked directory")
            total_files += len(files)
            if total_files > MAX_QUARANTINE_FILES:
                raise EvidenceError("release quarantine file count exceeded its bound")
            for name in files:
                item = Path(root) / name
                if item.is_symlink():
                    raise EvidenceError("release quarantine contains a symlinked file")
                total_bytes += item.stat().st_size
                if total_bytes > MAX_QUARANTINE_BYTES:
                    raise EvidenceError("release quarantine bytes exceeded their bound")
        return total_bytes, total_files

    def _execute(
        self,
        command: tuple[str, ...],
        *,
        network: bool = False,
        max_output_bytes: int = MAX_GIT_OUTPUT_BYTES,
    ) -> bytes:
        if self.cancelled():
            raise CancelledError("release evidence check cancelled")
        budget = self.budget or ExecutionBudget.start(self.timeout_seconds)
        budget.check_deadline(network=network)
        if self.command_observer is not None:
            self.command_observer(command)
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                env=_sanitized_git_environment(),
            )
            while process.poll() is None:
                if self.cancelled():
                    process.kill()
                    process.wait()
                    raise CancelledError("release evidence check cancelled")
                stdout_size = os.fstat(stdout_file.fileno()).st_size
                stderr_size = os.fstat(stderr_file.fileno()).st_size
                if stdout_size > max_output_bytes or stderr_size > 64 * 1024:
                    process.kill()
                    process.wait()
                    raise EvidenceError("Git evidence output exceeded its command bound")
                if stdout_size + stderr_size > budget.output_bytes_remaining:
                    process.kill()
                    process.wait()
                    raise EvidenceError("aggregate Git evidence output exceeded its bound")
                if budget.monitored_path is not None and budget.monitored_path.exists():
                    try:
                        self._bounded_directory_usage(budget.monitored_path)
                    except EvidenceError:
                        process.kill()
                        process.wait()
                        raise
                if time.monotonic() >= budget.deadline:
                    process.kill()
                    process.wait()
                    if network:
                        raise OfflineError("bounded canonical fetch timed out")
                    raise EvidenceError("bounded Git evidence command timed out")
                time.sleep(0.01)
            budget.check_deadline(network=network)
            stderr_file.seek(0)
            stderr = stderr_file.read(64 * 1024 + 1)
            stdout_size = os.fstat(stdout_file.fileno()).st_size
            budget.consume_output(stdout_size + len(stderr))
            if process.returncode != 0:
                detail = stderr[: 64 * 1024].decode("utf-8", errors="replace").strip()
                if network and any(marker in detail.lower() for marker in _OFFLINE_MARKERS):
                    raise OfflineError("bounded canonical fetch was unavailable")
                raise EvidenceError(detail or "Git evidence command failed")
            stdout_file.seek(0)
            stdout = stdout_file.read(max_output_bytes + 1)
            if len(stdout) > max_output_bytes:
                raise EvidenceError("Git evidence output exceeded its bound")
            return stdout

    def run_plain(
        self,
        *args: str,
        network: bool = False,
        max_output_bytes: int = MAX_GIT_OUTPUT_BYTES,
    ) -> bytes:
        command = (str(self.git_path), *args)
        return self._execute(command, network=network, max_output_bytes=max_output_bytes)

    def run(
        self,
        git_dir: Path,
        *args: str,
        network: bool = False,
        max_output_bytes: int = MAX_GIT_OUTPUT_BYTES,
    ) -> bytes:
        command = (
            str(self.git_path),
            "-c",
            "credential.helper=",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "protocol.allow=never",
            "-c",
            f"protocol.{self.allowed_protocol}.allow=always",
            "--git-dir",
            str(git_dir.resolve()),
            *args,
        )
        return self._execute(command, network=network, max_output_bytes=max_output_bytes)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _default_state_root(vault_root: Path) -> Path:
    vault_id = hashlib.sha256(str(vault_root.resolve()).encode("utf-8")).hexdigest()[:24]
    if sys.platform == "darwin":
        parent = Path.home() / "Library" / "Caches" / "Dex"
    elif os.name == "nt":
        parent = Path.home() / "AppData" / "Local" / "Dex" / "Cache"
    else:
        parent = Path.home() / ".cache" / "dex"
    return parent / "update-awareness" / vault_id


def _atomic_write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        else:
            os.chmod(temporary_path, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        temporary_path.unlink(missing_ok=True)


@contextmanager
def _state_lock(state_root: Path, *, timeout_seconds: float = 2.0, absolute_deadline: float | None = None):
    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = state_root / "state.lock"
    deadline = time.monotonic() + timeout_seconds
    if absolute_deadline is not None:
        deadline = min(deadline, absolute_deadline)
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise EvidenceError("update awareness state is busy")
            time.sleep(0.02)
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def _read_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"schema_version": 1, "noticed_releases": [], "seen_tags": {}}
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_STATE_BYTES:
            raise EvidenceError("update awareness state is not a bounded regular file")
        with path.open("rb") as handle:
            raw = handle.read(MAX_STATE_BYTES + 1)
        if len(raw) > MAX_STATE_BYTES:
            raise EvidenceError("update awareness state exceeded its bound")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError, EvidenceError) as error:
        raise EvidenceError("update awareness state is corrupt") from error
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise EvidenceError("update awareness state schema is unsupported")
    if not isinstance(value.get("noticed_releases", []), list) or not isinstance(value.get("seen_tags", {}), dict):
        raise EvidenceError("update awareness state fields are invalid")
    return value


class UpdateVerifier:
    """Verify immutable candidate release evidence without touching the install."""

    def __init__(
        self,
        vault_root: Path,
        *,
        state_root: Path | None = None,
        remote_url: str = CANONICAL_REMOTE_URL,
        allow_test_transport: bool = False,
        git_runner: GitRunner | None = None,
        now: Callable[[], datetime] | None = None,
        authenticator: PublisherAuthenticator | None = None,
        fetch_override: Callable[[GitRunner, Path, str], None] | None = None,
        wall_clock_seconds: float = SESSION_WALL_CLOCK_SECONDS,
    ) -> None:
        self.vault_root = vault_root.resolve()
        self.state_root = (state_root or _default_state_root(self.vault_root)).resolve()
        if remote_url != CANONICAL_REMOTE_URL and not allow_test_transport:
            raise EvidenceError("production release evidence URL is pinned")
        self.remote_url = remote_url
        self.git = git_runner or GitRunner(allowed_protocol="file" if allow_test_transport else "https")
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.authenticator = authenticator or NoPublisherAuthenticator()
        self.fetch_override = fetch_override
        self.wall_clock_seconds = wall_clock_seconds
        self._evidence_cache = self.state_root / "objects.git"
        self._budget: ExecutionBudget | None = None

    @property
    def state_path(self) -> Path:
        return self.state_root / "state.json"

    @property
    def cache_path(self) -> Path:
        return self._evidence_cache

    @staticmethod
    def _bounded_regular_file(path: Path, *, max_bytes: int, description: str) -> bytes:
        try:
            if path.is_symlink() or not path.is_file():
                raise EvidenceError(f"{description} is not a regular file")
            size = path.stat().st_size
            if size < 0 or size > max_bytes:
                raise EvidenceError(f"{description} exceeded its bound")
            raw = path.read_bytes()
        except OSError as error:
            raise EvidenceError(f"{description} is unreadable") from error
        if len(raw) != size:
            raise EvidenceError(f"{description} changed while being read")
        return raw

    def _current_version(self) -> str:
        try:
            package_raw = self._bounded_regular_file(
                self.vault_root / "package.json",
                max_bytes=MAX_PACKAGE_BYTES,
                description="installed package.json",
            )
            package = json.loads(package_raw.decode("utf-8"), object_pairs_hook=_json_pairs)
        except (UnicodeError, json.JSONDecodeError, EvidenceError) as error:
            raise EvidenceError("installed package version is unreadable") from error
        version = package.get("version") if isinstance(package, dict) else None
        SemVer.parse(version)
        profile_raw = self._bounded_regular_file(
            self.vault_root / PROFILE_PATH,
            max_bytes=MAX_PROFILE_BYTES,
            description="installed release evidence profile",
        )
        parse_profile(profile_raw, expected_version=version)
        return version

    def _initialize_cache(self) -> None:
        if self.cache_path.exists():
            self._validate_cache()
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.git.run_plain("init", "--bare", "--quiet", str(self.cache_path), max_output_bytes=1024)
        (self.cache_path / "config").write_bytes(_CACHE_CONFIG)
        self._validate_cache()

    def _validate_cache(self) -> None:
        required_file_paths = (self.cache_path / "HEAD", self.cache_path / "config")
        required_dir_paths = (self.cache_path / "objects", self.cache_path / "refs")
        if self.cache_path.is_symlink() or not self.cache_path.is_dir():
            raise EvidenceError("isolated release cache is malformed")
        if any(path.is_symlink() or not path.is_file() for path in required_file_paths):
            raise EvidenceError("isolated release cache metadata is malformed")
        if any(path.is_symlink() or not path.is_dir() for path in required_dir_paths):
            raise EvidenceError("isolated release cache storage is malformed")
        config_path = self.cache_path / "config"
        if config_path.stat().st_size > 1024 or config_path.read_bytes() != _CACHE_CONFIG:
            raise EvidenceError("isolated release cache configuration was modified")
        if (self.cache_path / "objects" / "info" / "alternates").exists():
            raise EvidenceError("isolated release cache contains alternate object storage")
        GitRunner._bounded_directory_usage(self.cache_path)

    def _remote_release_tags(self) -> tuple[str, ...]:
        raw = self.git.run_plain(
            "-c",
            "credential.helper=",
            "-c",
            "protocol.allow=never",
            "-c",
            f"protocol.{self.git.allowed_protocol}.allow=always",
            "ls-remote",
            "--refs",
            "--tags",
            self.remote_url,
            "refs/tags/dist/release/*",
            network=True,
            max_output_bytes=256 * 1024,
        )
        tags: list[str] = []
        for line in raw.splitlines():
            try:
                object_id, raw_ref = line.split(b"\t", 1)
                ref = raw_ref.decode("utf-8")
            except (ValueError, UnicodeDecodeError) as error:
                raise EvidenceError("remote release reference is malformed") from error
            if re.fullmatch(rb"[0-9a-f]{40,64}", object_id) is None or not ref.startswith(
                "refs/tags/dist/release/"
            ):
                raise EvidenceError("remote release reference is outside the pinned namespace")
            tags.append(ref.removeprefix("refs/tags/"))
            if len(tags) > MAX_REMOTE_RELEASE_REFS:
                raise EvidenceError("remote release reference enumeration exceeded its bound")
        if len(tags) != len(set(tags)):
            raise EvidenceError("remote release reference enumeration is ambiguous")
        return tuple(sorted(tags))

    def _fetch(self, tags: tuple[str, ...]) -> None:
        if self.fetch_override is not None:
            self.fetch_override(self.git, self.cache_path, self.remote_url)
            return
        refspecs = tuple(f"refs/tags/{tag}:refs/tags/{tag}" for tag in tags)
        if not refspecs:
            return
        self.git.run(
            self.cache_path,
            "fetch",
            "--quiet",
            "--no-tags",
            "--no-write-fetch-head",
            "--depth=1",
            "--no-recurse-submodules",
            self.remote_url,
            *refspecs,
            network=True,
            max_output_bytes=1024,
        )
        self._validate_cache()
        count_raw = self.git.run(
            self.cache_path,
            "count-objects",
            "-v",
            max_output_bytes=4096,
        ).decode("ascii")
        counts = {}
        for line in count_raw.splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                if value.isdigit():
                    counts[key] = int(value)
        if counts.get("count", 0) + counts.get("in-pack", 0) > MAX_QUARANTINE_OBJECTS:
            raise EvidenceError("release quarantine object count exceeded its bound")

    def _release_tags(self) -> tuple[str, ...]:
        raw = self.git.run(
            self.cache_path,
            "for-each-ref",
            "--format=%(refname)",
            max_output_bytes=256 * 1024,
        )
        try:
            refs = tuple(line for line in raw.decode("utf-8").splitlines() if line)
        except UnicodeDecodeError as error:
            raise EvidenceError("release references are not UTF-8") from error
        if any(not ref.startswith("refs/tags/dist/release/") for ref in refs):
            raise EvidenceError("isolated release cache contains an unexpected reference")
        tags = tuple(ref.removeprefix("refs/tags/") for ref in refs)
        if len(tags) != len(set(tags)):
            raise EvidenceError("release tag enumeration is ambiguous")
        if len(tags) > MAX_RELEASE_TAGS:
            raise EvidenceError("release tag enumeration exceeded its bound")
        return tuple(sorted(tags))

    def _blob_tree(self, commit: str) -> tuple[str, dict[str, tuple[str, str]]]:
        tree = self.git.run(self.cache_path, "rev-parse", "--verify", f"{commit}^{{tree}}").decode().strip()
        raw = self.git.run(
            self.cache_path,
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            commit,
            max_output_bytes=MAX_GIT_OUTPUT_BYTES,
        )
        entries: dict[str, tuple[str, str]] = {}
        path_bytes = 0
        for record in raw.split(b"\0"):
            if not record:
                continue
            try:
                metadata, raw_path = record.split(b"\t", 1)
                mode, object_type, object_id = metadata.decode("ascii").split(" ")
                path = raw_path.decode("utf-8")
            except (ValueError, UnicodeDecodeError) as error:
                raise EvidenceError("release tree entry is malformed") from error
            if path in entries or object_type != "blob" or mode not in {"100644", "100755", "120000"}:
                raise EvidenceError("release tree is ambiguous or contains unsupported entries")
            entries[path] = (mode, object_id)
            path_bytes += len(raw_path)
            if len(entries) > MAX_RELEASE_TREE_ENTRIES:
                raise EvidenceError("release tree entry count exceeded its bound")
            if path_bytes > MAX_RELEASE_TREE_PATH_BYTES:
                raise EvidenceError("release tree path bytes exceeded their bound")
        return tree, entries

    def _blob(
        self,
        entries: dict[str, tuple[str, str]],
        path: str,
        *,
        max_bytes: int,
        regular: bool = True,
    ) -> bytes:
        entry = entries.get(path)
        if entry is None:
            raise EvidenceError(f"required release artifact is missing: {path}")
        mode, object_id = entry
        if regular and mode != "100644":
            raise EvidenceError(f"required release artifact has a non-canonical mode: {path}")
        size_raw = self.git.run(self.cache_path, "cat-file", "-s", object_id, max_output_bytes=128)
        try:
            size = int(size_raw.decode("ascii").strip())
        except (UnicodeDecodeError, ValueError) as error:
            raise EvidenceError(f"required release artifact size is malformed: {path}") from error
        if size < 0 or size > max_bytes:
            raise EvidenceError(f"required release artifact exceeded its bound: {path}")
        raw = self.git.run(self.cache_path, "cat-file", "blob", object_id, max_output_bytes=max_bytes)
        if len(raw) != size:
            raise EvidenceError(f"required release artifact size changed: {path}")
        return raw

    def _verify_manifest(self, entries: dict[str, tuple[str, str]]) -> None:
        raw = self._blob(entries, MANIFEST_PATH, max_bytes=MAX_MANIFEST_BYTES)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise EvidenceError("installed-files manifest is not UTF-8") from error
        if not text.endswith("\n") or "\r" in text or "\x00" in text:
            raise EvidenceError("installed-files manifest is not canonical")
        paths = text.splitlines()
        if paths != sorted(set(paths)) or set(paths) != set(entries):
            raise EvidenceError("installed-files manifest contradicts the exact release tree")
        if PROFILE_PATH not in paths:
            raise EvidenceError("release evidence profile is absent from the installed-files manifest")

    def _verify_catalog(self, profile: ReleaseEvidenceProfile, entries: dict[str, tuple[str, str]]) -> None:
        catalog_raw = self._blob(entries, CATALOG_PATH, max_bytes=MAX_CATALOG_BYTES)
        if _sha256(catalog_raw) != profile.catalog_sha256:
            raise EvidenceError("catalog hash contradicts the declared catalog-v1 profile")
        try:
            catalog = json.loads(catalog_raw.decode("utf-8"), object_pairs_hook=_json_pairs)
        except (UnicodeDecodeError, json.JSONDecodeError, EvidenceError) as error:
            raise EvidenceError("catalog-v1 catalog is malformed") from error
        if not isinstance(catalog, dict) or catalog.get("contract_version") != profile.catalog_contract_version:
            raise EvidenceError("catalog contract version contradicts the declared catalog-v1 profile")
        for artifact in profile.compatibility_metadata:
            raw = self._blob(entries, artifact.path, max_bytes=MAX_COMPATIBILITY_BYTES)
            if _sha256(raw) != artifact.sha256:
                raise EvidenceError("compatibility artifact hash contradicts catalog-v1")
            try:
                value = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_pairs)
            except (UnicodeDecodeError, json.JSONDecodeError, EvidenceError) as error:
                raise EvidenceError("compatibility artifact is malformed") from error
            if not isinstance(value, dict) or value.get("contract_version") != artifact.contract_version:
                raise EvidenceError("compatibility artifact contract version contradicts catalog-v1")

    def _verify_candidate(self, tag: str, expected_version: str, expected_short: str) -> CandidateEvidence:
        object_type = self.git.run(self.cache_path, "cat-file", "-t", tag, max_output_bytes=64).decode().strip()
        if object_type != "tag":
            raise EvidenceError("candidate release tag is not annotated")
        try:
            tag_object = self.git.run(
                self.cache_path,
                "cat-file",
                "tag",
                tag,
                max_output_bytes=MAX_TAG_OBJECT_BYTES,
            ).decode("utf-8")
        except UnicodeDecodeError as error:
            raise EvidenceError("annotated tag object is not UTF-8") from error
        headers = {}
        for line in tag_object.split("\n\n", 1)[0].splitlines():
            if " " in line:
                key, value = line.split(" ", 1)
                if key in headers:
                    raise EvidenceError("annotated tag headers are ambiguous")
                headers[key] = value
        if headers.get("type") != "commit" or headers.get("tag") != tag:
            raise EvidenceError("annotated tag identity is malformed or moved")
        commit = headers.get("object", "")
        if re.fullmatch(r"[0-9a-f]{40,64}", commit) is None:
            raise EvidenceError("annotated tag commit identity is malformed")
        resolved_commit = self.git.run(self.cache_path, "rev-parse", "--verify", f"{tag}^{{commit}}").decode().strip()
        if resolved_commit != commit or not commit.startswith(expected_short):
            raise EvidenceError("tag suffix and immutable full commit identity disagree")

        tree, entries = self._blob_tree(commit)
        if sum(path == PROFILE_PATH for path in entries) != 1:
            raise EvidenceError("candidate must declare exactly one release evidence profile")
        package_raw = self._blob(entries, "package.json", max_bytes=MAX_PACKAGE_BYTES)
        try:
            package = json.loads(package_raw.decode("utf-8"), object_pairs_hook=_json_pairs)
        except (UnicodeDecodeError, json.JSONDecodeError, EvidenceError) as error:
            raise EvidenceError("tagged package.json is malformed") from error
        if not isinstance(package, dict) or package.get("version") != expected_version:
            raise EvidenceError("tagged package version contradicts the immutable tag")
        profile = parse_profile(
            self._blob(entries, PROFILE_PATH, max_bytes=MAX_PROFILE_BYTES),
            expected_version=expected_version,
        )
        self._verify_manifest(entries)
        if profile.profile == "catalog-v1":
            self._verify_catalog(profile, entries)
        return CandidateEvidence(expected_version, tag, commit, tree, profile.profile)

    def _legacy_notice_matches(self, candidate: CandidateEvidence, state: dict[str, object]) -> bool:
        if state.get("legacy_notice_migrated") is True:
            return False
        state["legacy_notice_migrated"] = True
        legacy_path = self.vault_root / "System" / ".update-available"
        try:
            if legacy_path.is_symlink() or not legacy_path.is_file():
                return False
            legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        latest = legacy.get("latest_version") if isinstance(legacy, dict) else None
        return latest in {candidate.version, f"v{candidate.version}"}

    def _notice(self, candidate: CandidateEvidence) -> str:
        return "\n".join(
            (
                NOTICE_CAUTION,
                f"Target version: v{candidate.version}",
                f"Immutable tag: {candidate.tag}",
                f"Full commit: {candidate.commit}",
                f"Evidence profile: {candidate.profile}",
                f"Release page: {CANONICAL_RELEASE_PAGE.format(tag=candidate.tag)}",
                NOTICE_GUIDANCE,
            )
        )

    @contextmanager
    def _quarantined_cache(self):
        self.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        quarantine = Path(tempfile.mkdtemp(prefix="objects-quarantine.", dir=self.state_root)) / "objects.git"
        original_cache = self._evidence_cache
        self._evidence_cache = quarantine
        if self._budget is not None:
            self._budget.monitored_path = quarantine.parent
        try:
            self._initialize_cache()
            yield
        finally:
            self._evidence_cache = original_cache
            if self._budget is not None:
                self._budget.monitored_path = None
            shutil.rmtree(quarantine.parent, ignore_errors=True)

    def _promote_quarantine(self) -> None:
        quarantine = self.cache_path
        persistent = self.state_root / "objects.git"
        backup = self.state_root / "objects.previous.git"
        shutil.rmtree(backup, ignore_errors=True)
        if persistent.exists():
            os.replace(persistent, backup)
        try:
            os.replace(quarantine, persistent)
        except Exception:
            if backup.exists() and not persistent.exists():
                os.replace(backup, persistent)
            raise
        finally:
            shutil.rmtree(backup, ignore_errors=True)

    @staticmethod
    def _migrate_state(state: dict[str, object]) -> None:
        # These SR1-preview fields were never read by a tool/API. Preserve the
        # authoritative date/status and exact noticed identities instead.
        state.pop("last_attempt_at", None)
        state.pop("last_notice", None)

    def _write_state(self, state: dict[str, object]) -> bool:
        try:
            _atomic_write_json(self.state_path, state)
        except OSError:
            return False
        return True

    def _record_attempt(self, state: dict[str, object], status: str, reason: str | None = None) -> bool:
        state["last_status"] = status
        if reason is None:
            state.pop("last_reason", None)
        else:
            state["last_reason"] = reason
        return self._write_state(state)

    def _persist_failure(self, *, today: str, status: str, reason: str) -> bool:
        try:
            with _state_lock(self.state_root, timeout_seconds=0.2):
                try:
                    current = _read_state(self.state_path)
                except EvidenceError:
                    current = {"schema_version": 1, "noticed_releases": [], "seen_tags": {}}
                self._migrate_state(current)
                current["last_attempt_date"] = today
                return self._record_attempt(current, status, reason)
        except (EvidenceError, OSError):
            return False

    def check(self, *, force: bool = False, doctor_redisplay: bool = False) -> dict[str, object]:
        today = self.now().date().isoformat()
        result: dict[str, object] = {"status": STATUS_UNKNOWN, "should_notify": False}
        state: dict[str, object] | None = None
        self._budget = ExecutionBudget.start(self.wall_clock_seconds)
        self.git.use_budget(self._budget)
        try:
            with _state_lock(
                self.state_root,
                absolute_deadline=self._budget.deadline if self._budget is not None else None,
            ):
                try:
                    state = _read_state(self.state_path)
                except EvidenceError:
                    state = {
                        "schema_version": 1,
                        "noticed_releases": [],
                        "seen_tags": {},
                        "last_attempt_date": today,
                        "last_status": STATUS_UNKNOWN,
                        "last_reason": "state-corrupt",
                        "recovered_from_corrupt_state": True,
                    }
                    if not self._write_state(state):
                        return {**result, "reason": "state-write-failed"}
                    return {**result, "reason": "state-corrupt"}
                self._migrate_state(state)
                if not (force or doctor_redisplay) and state.get("last_attempt_date") == today:
                    return {"status": STATUS_SKIPPED, "should_notify": False, "skip_reason": "daily-attempt"}
                state["last_attempt_date"] = today
                if not self._write_state(state):
                    return {**result, "reason": "state-write-failed"}

                current_version = self._current_version()
                current_semver = SemVer.parse(current_version)
                result["current_version"] = current_version
                persistent_cache = self.state_root / "objects.git"
                if persistent_cache.exists():
                    self._evidence_cache = persistent_cache
                    self._validate_cache()
                remote_tags = self._remote_release_tags() if self.fetch_override is None else ()
                selected_remote_tags: list[str] = []
                for tag in remote_tags:
                    match = _TAG_RE.fullmatch(tag)
                    if match is None:
                        raise EvidenceError("candidate release tag shape is malformed")
                    if SemVer.parse(match.group("version")) > current_semver:
                        selected_remote_tags.append(tag)
                if len(selected_remote_tags) > MAX_RELEASE_TAGS:
                    raise EvidenceError("higher release candidate count exceeded its bound")
                higher: list[CandidateEvidence] = []
                seen_tags = state.setdefault("seen_tags", {})
                if not isinstance(seen_tags, dict):
                    raise EvidenceError("seen tag state is invalid")
                for prior_tag in seen_tags:
                    prior_match = _TAG_RE.fullmatch(prior_tag) if isinstance(prior_tag, str) else None
                    if (
                        prior_match is not None
                        and SemVer.parse(prior_match.group("version")) > current_semver
                        and self.fetch_override is None
                        and prior_tag not in remote_tags
                    ):
                        raise EvidenceError("previously observed immutable candidate tag disappeared")
                with self._quarantined_cache():
                    self._fetch(tuple(selected_remote_tags))
                    tags = self._release_tags()
                    for tag in tags:
                        match = _TAG_RE.fullmatch(tag)
                        if match is None:
                            raise EvidenceError("candidate release tag shape is malformed")
                        version = match.group("version")
                        if SemVer.parse(version) <= current_semver:
                            continue
                        candidate = self._verify_candidate(tag, version, match.group("short"))
                        prior_commit = seen_tags.get(tag)
                        if prior_commit is not None and prior_commit != candidate.commit:
                            raise EvidenceError("immutable candidate tag moved")
                        seen_tags[tag] = candidate.commit
                        higher.append(candidate)
                    self._promote_quarantine()
                if not higher:
                    if not self._record_attempt(state, STATUS_NONE):
                        return {**result, "reason": "state-write-failed"}
                    return {
                        "status": STATUS_NONE,
                        "should_notify": False,
                        "current_version": current_version,
                        "message": "No higher release was observed by the bounded evidence check; this is not a currentness claim.",
                    }
                highest_version = max(SemVer.parse(candidate.version) for candidate in higher)
                selected = [candidate for candidate in higher if SemVer.parse(candidate.version) == highest_version]
                if len({candidate.identity for candidate in selected}) != 1:
                    raise EvidenceError("higher release evidence is ambiguous")
                candidate = selected[0]
                if self.authenticator.authenticate(candidate) != "unavailable":
                    raise EvidenceError("no authenticated release status is selected in SR1")

                noticed = state.setdefault("noticed_releases", [])
                if not isinstance(noticed, list) or any(not isinstance(item, str) for item in noticed):
                    raise EvidenceError("notice dedup state is invalid")
                legacy_suppressed = self._legacy_notice_matches(candidate, state)
                if legacy_suppressed and candidate.identity not in noticed:
                    noticed.append(candidate.identity)
                already_noticed = candidate.identity in noticed or candidate.legacy_identity in noticed
                if already_noticed and not doctor_redisplay:
                    if not self._record_attempt(state, STATUS_SKIPPED, "exact-release-notice"):
                        return {**result, "reason": "state-write-failed"}
                    return {
                        "status": STATUS_SKIPPED,
                        "should_notify": False,
                        "skip_reason": "legacy-notice" if legacy_suppressed else "exact-release-notice",
                        "current_version": current_version,
                    }
                if not already_noticed:
                    noticed.append(candidate.identity)
                notice = self._notice(candidate)
                if not self._record_attempt(state, STATUS_RELEASE):
                    return {**result, "reason": "state-write-failed"}
                return {
                    "status": STATUS_RELEASE,
                    "should_notify": True,
                    "current_version": current_version,
                    "version": candidate.version,
                    "tag": candidate.tag,
                    "commit": candidate.commit,
                    "tree": candidate.tree,
                    "profile": candidate.profile,
                    "release_page": CANONICAL_RELEASE_PAGE.format(tag=candidate.tag),
                    "notice": notice,
                    "publisher_authentication": "unavailable",
                }
        except OfflineError:
            reason = "network-unavailable"
            if not self._persist_failure(today=today, status=STATUS_OFFLINE, reason=reason):
                reason = "state-write-failed"
                return {**result, "reason": reason}
            return {**result, "status": STATUS_OFFLINE, "reason": reason}
        except (CancelledError, EvidenceError, OSError, UnicodeError, subprocess.SubprocessError) as error:
            reason = {
                CancelledError: "cancelled",
                EvidenceError: "evidence-invalid",
                OSError: "io-error",
                UnicodeError: "encoding-invalid",
                subprocess.SubprocessError: "subprocess-failed",
            }.get(type(error), "evidence-invalid")
            if not self._persist_failure(today=today, status=STATUS_UNKNOWN, reason=reason):
                reason = "state-write-failed"
            return {**result, "reason": reason}
        finally:
            self._budget = None
            self.git.budget = None


def _session_start_output(result: dict[str, object]) -> None:
    if result.get("status") != STATUS_RELEASE or result.get("should_notify") is not True:
        return
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": f"\n{result['notice']}\n",
        }
    }
    print(json.dumps(output, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=Path.cwd())
    parser.add_argument("--session-start", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--doctor-redisplay", action="store_true")
    parser.add_argument("--write-legacy-profile", type=Path)
    parser.add_argument("--release-version")
    args = parser.parse_args(argv)
    if args.write_legacy_profile is not None:
        if args.release_version is None:
            parser.error("--write-legacy-profile requires --release-version")
        write_legacy_profile(args.write_legacy_profile, args.release_version)
        return 0
    result = UpdateVerifier(args.vault).check(force=args.force, doctor_redisplay=args.doctor_redisplay)
    if args.session_start:
        _session_start_output(result)
    else:
        print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
