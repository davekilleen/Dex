"""Opt-in local Git history privacy hygiene with verified recovery bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Literal

from core.paths import HISTORY_BACKUPS_RELATIVE_PARTS
from core.utils.local_git import git_env, git_output

try:
    import fcntl
except ImportError:  # pragma: no cover - history cleanup already requires Unix descriptor passing
    fcntl = None

HistoryResult = Literal[
    "optional-tool-unavailable",
    "prepared",
    "history-clean",
    "history-cleanup-pending",
    "history-scope-unknown",
    "recovery-required",
    "rewound",
]

SHARED_RECOVERY_CAP_BYTES = 10 * 1024 * 1024 * 1024
MIN_FREE_MARGIN_BYTES = 1024 * 1024
RETENTION_DAYS = 90
RETENTION_RELEASES = 2
SUPPORTED_FILTER_REPO = re.compile(r"^(?:2\.(?:3[8-9]|[4-9]\d)\.\d+|[0-9a-f]{7,64})$")
ALLOWED_REF_PREFIXES = ("refs/heads/", "refs/tags/", "refs/stash/")
INCOMPLETE_TRANSACTION = re.compile(r"^\.incomplete-([0-9a-f]{32})$")
TRANSACTION_ID = re.compile(r"^[0-9a-f]{32}$")
PREPARATION_ARTIFACTS = frozenset(
    {"history.bundle", "objects.json", "git-config.bin", "index.bin", "manifest.json"}
)
MAX_STATUS_OUTPUT_BYTES = 16 * 1024 * 1024
HISTORY_BACKUPS_RELATIVE_POSIX = "/".join(HISTORY_BACKUPS_RELATIVE_PARTS)


@dataclass(frozen=True)
class HistoryPreview:
    state: HistoryResult
    transaction_id: str | None
    preview_sha256: str | None
    guidance: str


@dataclass(frozen=True)
class HistoryOutcome:
    state: HistoryResult
    transaction_id: str
    uninspected_scopes: tuple[str, ...] = ()
    guidance: str = ""


@dataclass(frozen=True)
class RetentionPreview:
    candidate_ids: tuple[str, ...]
    exact_set_sha256: str
    protected_final_id: str | None
    retained_ids: tuple[str, ...]
    evaluated_at: str
    successful_release_activations: int
    candidate_bytes: int


_MANIFEST_BASE_KEYS = frozenset(
    {
        "schema_version", "transaction_id", "phase", "created_at", "minimum_delete_after",
        "successful_release_activations_at_creation", "minimum_successful_release_activations_for_deletion",
        "external_backup", "selected_refs", "all_refs", "repository_state", "credential_occurrences",
        "recovery_directory_identity", "before_object_evidence", "primary_common_dir_identity",
        "primary_object_db_identity", "bundle", "recovery_artifacts", "filter_repo", "preview_sha256",
    }
)
_MANIFEST_APPLIED_KEYS = frozenset({"after_refs", "after_all_refs", "post_cleanup_scan_state", "post_cleanup_uninspected_scopes"})
_MANIFEST_RECOVERY_KEYS = frozenset({"after_refs", "after_all_refs", "recovery_guidance"})


@dataclass(frozen=True)
class HistoryManifest:
    """Closed, phase-aware history transaction model and serializer."""

    _data: dict[str, object]

    @classmethod
    def create(cls, core: dict[str, object]) -> "HistoryManifest":
        if "preview_sha256" in core or core.get("phase") != "prepared":
            raise ValueError("history manifest must begin in prepared phase")
        unsigned = dict(core)
        return cls.from_dict({**unsigned, "preview_sha256": _sha(_json_bytes(unsigned))})

    @classmethod
    def from_dict(cls, value: object) -> "HistoryManifest":
        if not isinstance(value, dict):
            raise ValueError("history manifest must be an object")
        phase = value.get("phase")
        optional = (
            frozenset()
            if phase in {"prepared", "applying"}
            else _MANIFEST_APPLIED_KEYS
            if phase in {"applied", "rewound"}
            else _MANIFEST_RECOVERY_KEYS | _MANIFEST_APPLIED_KEYS
            if phase == "recovery-required"
            else None
        )
        if optional is None or not _MANIFEST_BASE_KEYS <= value.keys() or not value.keys() <= _MANIFEST_BASE_KEYS | optional:
            raise ValueError("history manifest changed: invalid phase or keys")
        if value.get("schema_version") != 1 or not re.fullmatch(r"[0-9a-f]{32}", str(value.get("transaction_id", ""))):
            raise ValueError("history manifest identity is invalid")
        for name in ("selected_refs", "all_refs"):
            refs = value.get(name)
            if not isinstance(refs, dict) or any(
                not isinstance(ref, str) or not isinstance(oid, str) or not re.fullmatch(r"[0-9a-f]{40,64}", oid)
                for ref, oid in refs.items()
            ):
                raise ValueError("history manifest refs are invalid")
        for name, keys in {
            "bundle": {"sha256", "size", "verified"},
            "before_object_evidence": {"sha256", "size", "file"},
            "filter_repo": {"path_identity", "sha256", "size"},
        }.items():
            nested = value.get(name)
            if not isinstance(nested, dict) or set(nested) != keys:
                raise ValueError(f"history manifest {name} is invalid")
        external = value.get("external_backup")
        if not isinstance(external, dict) or set(external) not in (
            {"verified_evidence_sha256"},
            {"no_external_backup_acknowledged"},
        ):
            raise ValueError("history manifest external backup is invalid")
        directory_identity = value.get("recovery_directory_identity")
        if not isinstance(directory_identity, dict) or set(directory_identity) != {"device", "inode"} or not all(
            isinstance(item, int) for item in directory_identity.values()
        ):
            raise ValueError("history manifest recovery directory identity is invalid")
        repository_state = value.get("repository_state")
        if not isinstance(repository_state, dict) or set(repository_state) != {
            "head", "index_sha256", "worktree_sha256", "remote_config_sha256",
        } or not all(isinstance(item, str) for item in repository_state.values()):
            raise ValueError("history manifest repository state is invalid")
        artifacts = value.get("recovery_artifacts")
        if not isinstance(artifacts, dict) or set(artifacts) != {"git-config.bin", "index.bin"}:
            raise ValueError("history manifest recovery artifacts are invalid")
        for artifact in artifacts.values():
            if not isinstance(artifact, dict) or set(artifact) != {"absent", "sha256", "size", "mode"}:
                raise ValueError("history manifest recovery artifact is invalid")
        occurrences = value.get("credential_occurrences")
        if not isinstance(occurrences, list) or any(
            not isinstance(profile, list)
            or any(
                not isinstance(span, list)
                or len(span) != 3
                or any(not isinstance(number, int) or number < 0 for number in span)
                for span in profile
            )
            for profile in occurrences
        ):
            raise ValueError("history manifest credential occurrences are invalid")
        preview = value.get("preview_sha256")
        unsigned = {key: item for key, item in value.items() if key != "preview_sha256"}
        if preview != _sha(_json_bytes(unsigned)):
            raise ValueError("history preview manifest changed")
        return cls(dict(value))

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)

    def items(self):
        return self._data.items()

    def to_dict(self) -> dict[str, object]:
        return dict(self._data)

    def serialize(self) -> bytes:
        return _json_bytes(self._data)

    def _transition(self, phase: str, **updates: object) -> "HistoryManifest":
        unsigned = {key: item for key, item in self._data.items() if key != "preview_sha256"}
        unsigned.update(updates)
        unsigned["phase"] = phase
        return HistoryManifest.from_dict({**unsigned, "preview_sha256": _sha(_json_bytes(unsigned))})

    def begin_apply(self) -> "HistoryManifest":
        if self["phase"] != "prepared":
            raise ValueError("history manifest is not prepared")
        return self._transition("applying")

    def record_applied(
        self, after_refs: dict[str, str], after_all_refs: dict[str, str], scan_state: str,
        uninspected_scopes: tuple[str, ...] = (),
    ) -> "HistoryManifest":
        if self["phase"] != "applying":
            raise ValueError("history manifest is not applying")
        updates: dict[str, object] = {
            "after_refs": after_refs, "after_all_refs": after_all_refs, "post_cleanup_scan_state": scan_state,
        }
        if uninspected_scopes:
            updates["post_cleanup_uninspected_scopes"] = list(uninspected_scopes)
        return self._transition("applied", **updates)

    def record_recovery_required(
        self, guidance: str, after_refs: dict[str, str] | None = None,
        after_all_refs: dict[str, str] | None = None,
    ) -> "HistoryManifest":
        updates: dict[str, object] = {"recovery_guidance": guidance}
        if after_refs is not None and after_all_refs is not None:
            updates.update(after_refs=after_refs, after_all_refs=after_all_refs)
        return self._transition("recovery-required", **updates)

    def record_rewound(self) -> "HistoryManifest":
        if self["phase"] not in {"applied", "recovery-required"}:
            raise ValueError("history manifest cannot be rewound")
        unsigned = {key: item for key, item in self._data.items() if key not in {"preview_sha256", "recovery_guidance"}}
        unsigned["phase"] = "rewound"
        return HistoryManifest.from_dict({**unsigned, "preview_sha256": _sha(_json_bytes(unsigned))})


def _now() -> datetime:
    return datetime.now(UTC)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_restrictive(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if path.read_bytes() != data or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise OSError("restrictive history artifact readback failed")
    _fsync_dir(path.parent)


def _atomic_replace(path: Path, data: bytes, mode: int, error: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
        if path.read_bytes() != data or stat.S_IMODE(path.stat().st_mode) != mode:
            raise OSError(error)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _safe_executable(candidate: Path) -> Path | None:
    candidate = candidate.absolute()
    try:
        if candidate.is_symlink() or not candidate.is_file() or not os.access(candidate, os.X_OK):
            return None
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    return resolved


def _git_env() -> dict[str, str]:
    return git_env()


def _git(root: Path, *args: str, input_data: bytes | None = None, pass_fds: tuple[int, ...] = ()) -> bytes:
    mutation_commands = {"bundle", "update-ref"}
    profile = "mutation" if args and args[0] in mutation_commands else "read-only"
    return git_output(
        root,
        *args,
        profile=profile,
        input_data=input_data,
        pass_fds=pass_fds,
    )


def _repository_boundaries(root: Path) -> tuple[Path, Path, Path]:
    git_dir = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-dir").decode().strip()).resolve()
    common = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip()).resolve()
    objects = Path(
        _git(root, "rev-parse", "--path-format=absolute", "--git-path", "objects").decode().strip()
    ).resolve()
    if git_dir != common or objects != common / "objects" or not common.is_dir() or not objects.is_dir():
        raise RuntimeError("history cleanup requires the approved primary common-dir/object database")
    config = common / "config"
    if (
        (objects / "info" / "alternates").exists()
        or (common / "shallow").exists()
        or config.is_symlink()
        or not config.is_file()
    ):
        raise RuntimeError("ambiguous Git object topology")
    if "promisor = true" in config.read_text(encoding="utf-8", errors="ignore").lower():
        raise RuntimeError("promisor object topology is unsupported")
    return git_dir, common, objects


def resolve_filter_repo(explicit: Path | None = None) -> Path | None:
    candidate = explicit or (Path(found) if (found := shutil.which("git-filter-repo")) else None)
    if candidate is None:
        return None
    candidate = _safe_executable(candidate)
    if candidate is None:
        return None
    result = subprocess.run(
        [str(candidate), "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=_git_env(),
    )
    version = result.stdout.decode("ascii", errors="ignore").strip()
    return candidate if result.returncode == 0 and SUPPORTED_FILTER_REPO.fullmatch(version) else None


def _refs(root: Path, selected_refs: tuple[str, ...]) -> dict[str, str]:
    if not selected_refs or len(set(selected_refs)) != len(selected_refs):
        raise ValueError("explicit unique selected refs are required")
    result: dict[str, str] = {}
    for ref in sorted(selected_refs):
        if ref != "refs/stash" and not ref.startswith(ALLOWED_REF_PREFIXES):
            raise ValueError("unsupported selected ref")
        _git(root, "check-ref-format", ref)
        oid = _git(root, "rev-parse", "--verify", ref).decode().strip()
        if not re.fullmatch(r"[0-9a-f]{40,64}", oid):
            raise RuntimeError("invalid selected ref identity")
        result[ref] = oid
    return result


def _all_refs(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in _git(root, "for-each-ref", "--format=%(refname) %(objectname)").decode().splitlines():
        ref, oid = line.split(" ", 1)
        if not re.fullmatch(r"refs/[^\x00-\x20~^:?*\\]+", ref) or not re.fullmatch(r"[0-9a-f]{40,64}", oid):
            raise RuntimeError("invalid repository ref evidence")
        result[ref] = oid
    if not result:
        raise RuntimeError("history cleanup requires restorable refs")
    return dict(sorted(result.items()))


def _repository_state(root: Path) -> dict[str, str]:
    index = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-path", "index").decode().strip())
    index_identity = _sha(index.read_bytes()) if index.exists() else "absent"
    worktree = hashlib.sha256()
    paths = set(_git(root, "ls-files", "-z").split(b"\0"))
    paths.update(_git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"))
    for relative in sorted(paths):
        if not relative:
            continue
        if relative.startswith(os.fsencode(HISTORY_BACKUPS_RELATIVE_POSIX + "/")):
            continue
        path = root / os.fsdecode(relative)
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("tracked worktree state is unsafe")
        worktree.update(relative)
        worktree.update(b"\0")
        worktree.update(path.read_bytes())
    return {
        "head": _git(root, "symbolic-ref", "-q", "HEAD").decode().strip(),
        "index_sha256": index_identity,
        "worktree_sha256": worktree.hexdigest(),
        "remote_config_sha256": _sha(
            Path(
                _git(root, "rev-parse", "--path-format=absolute", "--git-path", "config").decode().strip()
            ).read_bytes()
        ),
    }


def _require_repository_quiescence(root: Path) -> None:
    status = _git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
        ".",
        f":(exclude){HISTORY_BACKUPS_RELATIVE_POSIX}",
        f":(exclude){HISTORY_BACKUPS_RELATIVE_POSIX}/**",
    )
    if len(status) > MAX_STATUS_OUTPUT_BYTES:
        raise RuntimeError("repository quiescence evidence exceeded its bound")
    if status:
        raise PermissionError("history cleanup requires a clean index and worktree")


def _object_evidence(root: Path, refs: tuple[str, ...]) -> tuple[bytes, int]:
    oids = {line.split(b" ", 1)[0] for line in _git(root, "rev-list", "--objects", *refs).splitlines()}
    oids.update(_git(root, "rev-parse", "--verify", ref).strip() for ref in refs)
    counts: dict[str, int] = {}
    estimated = 0
    for raw_oid in sorted(oids):
        oid = raw_oid.decode()
        kind = _git(root, "cat-file", "-t", oid).decode().strip()
        size = _git(root, "cat-file", "-s", oid).decode().strip()
        estimated += int(size)
        counts[kind] = counts.get(kind, 0) + 1
    return _json_bytes({"object_counts": counts, "estimated_uncompressed_bytes": estimated}), estimated


def _fd_path(descriptor: int) -> Path:
    for root in (Path("/proc/self/fd"), Path("/dev/fd")):
        if root.is_dir():
            return root / str(descriptor)
    raise OSError("descriptor paths are unavailable")


def _open_directory_chain_at(parent_descriptor: int, parts: tuple[str, ...], *, create: bool = False) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.dup(parent_descriptor)
    try:
        for part in parts:
            if not part or part in {".", ".."} or "/" in part:
                raise OSError("unsafe recovery directory component")
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=descriptor)
                os.fsync(descriptor)
                child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_directory_chain(root: Path, parts: tuple[str, ...], *, create: bool = False) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_descriptor = os.open(root, flags)
    try:
        return _open_directory_chain_at(root_descriptor, parts, create=create)
    finally:
        os.close(root_descriptor)


def _open_backup_root_at(root_descriptor: int, *, create: bool = False) -> int:
    return _open_directory_chain_at(
        root_descriptor,
        HISTORY_BACKUPS_RELATIVE_PARTS,
        create=create,
    )


def _directory_identity(descriptor: int) -> dict[str, int]:
    metadata = os.fstat(descriptor)
    return {"device": metadata.st_dev, "inode": metadata.st_ino}


@dataclass
class _LoadedTransaction:
    descriptor: int
    path: Path
    manifest: HistoryManifest | None = None

    def __enter__(self) -> _LoadedTransaction:
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1


@dataclass
class _HistoryLifecycleLock:
    root_descriptor: int
    backup_descriptor: int

    def __enter__(self) -> _HistoryLifecycleLock:
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()

    def close(self) -> None:
        if self.backup_descriptor >= 0:
            os.close(self.backup_descriptor)
            self.backup_descriptor = -1
        if self.root_descriptor >= 0:
            if fcntl is not None:
                fcntl.flock(self.root_descriptor, fcntl.LOCK_UN)
            os.close(self.root_descriptor)
            self.root_descriptor = -1


def _acquire_history_lifecycle_lock(root: Path, *, create: bool) -> _HistoryLifecycleLock:
    if fcntl is None:
        raise RuntimeError("history lifecycle locking is unavailable")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_descriptor = os.open(root, flags)
    backup_descriptor = None
    try:
        fcntl.flock(root_descriptor, fcntl.LOCK_EX)
        backup_descriptor = _open_backup_root_at(root_descriptor, create=create)
        metadata = os.fstat(backup_descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise OSError("unsafe history backup directory")
        return _HistoryLifecycleLock(root_descriptor, backup_descriptor)
    except BaseException:
        if backup_descriptor is not None:
            os.close(backup_descriptor)
        os.close(root_descriptor)
        raise

def _sync_file_identity(path: Path) -> tuple[str, int]:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return digest.hexdigest(), size


def _used_recovery_bytes(root_descriptor: int) -> int:
    try:
        adoption = _open_directory_chain_at(root_descriptor, ("System", ".dex", "adoption"))
    except FileNotFoundError:
        return 0
    total = 0
    try:
        for current, directories, files in os.walk(_fd_path(adoption), followlinks=False):
            if any((Path(current) / name).is_symlink() for name in directories):
                raise OSError("unsafe recovery capacity input")
            for name in files:
                path = Path(current) / name
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise OSError("unsafe recovery capacity input")
                total += metadata.st_size
        return total
    finally:
        os.close(adoption)


def _remove_unpublished_transaction(backup_descriptor: int, name: str) -> None:
    incomplete = INCOMPLETE_TRANSACTION.fullmatch(name) is not None
    if not incomplete:
        raise OSError("unsafe unpublished history transaction name")
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=backup_descriptor,
    )
    try:
        entries = os.listdir(descriptor)
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o700:
            raise OSError("unsafe unpublished history transaction")
        if any(entry not in PREPARATION_ARTIFACTS for entry in entries):
            raise OSError("unsafe unpublished history transaction")
        for entry in entries:
            metadata = os.stat(entry, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise OSError("unsafe unpublished history transaction")
        for entry in entries:
            os.unlink(entry, dir_fd=descriptor)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.rmdir(name, dir_fd=backup_descriptor)
    os.fsync(backup_descriptor)


def _prune_incomplete_transactions(backup_descriptor: int) -> None:
    for name in sorted(os.listdir(backup_descriptor)):
        if INCOMPLETE_TRANSACTION.fullmatch(name):
            _remove_unpublished_transaction(backup_descriptor, name)
        elif TRANSACTION_ID.fullmatch(name):
            descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=backup_descriptor)
            try:
                if "manifest.json" not in os.listdir(descriptor):
                    raise OSError("published history transaction is missing its manifest")
            finally:
                os.close(descriptor)


def prepare_history_cleanup(
    root: Path,
    *,
    security_state: str,
    explicit_choice: bool,
    selected_refs: tuple[str, ...],
    credential_needles: tuple[bytes, ...],
    successful_release_activations: int,
    no_external_backup_acknowledged: bool = False,
    external_backup_evidence: str | None = None,
    filter_repo: Path | None = None,
    now: Callable[[], datetime] = _now,
) -> HistoryPreview:
    """Prepare a verified recovery bundle; never rewrite history."""
    if security_state != "remediated" or not explicit_choice:
        raise PermissionError("optional history preparation requires remediated security and explicit choice")
    if not credential_needles or any(not item for item in credential_needles):
        raise ValueError("exact revoked credential bytes are required")
    if len(set(credential_needles)) != len(credential_needles):
        raise ValueError("exact revoked credential bytes must be unique")
    if successful_release_activations < 0:
        raise ValueError("successful release activations cannot be negative")
    if not (no_external_backup_acknowledged ^ bool(external_backup_evidence)):
        raise ValueError("choose no-external-backup acknowledgement or verified external-backup evidence")
    if external_backup_evidence and not re.fullmatch(r"[0-9a-f]{64}", external_backup_evidence):
        raise ValueError("verified external-backup evidence must be a SHA-256 identity")
    tool = resolve_filter_repo(filter_repo)
    if tool is None:
        return HistoryPreview(
            "optional-tool-unavailable",
            None,
            None,
            "Optional history privacy cleanup is unavailable because a supported preinstalled git-filter-repo was not found. Security remains fixed; Dex did not install or run anything. To enable the guided path, install git-filter-repo yourself from its official platform package, verify that `git-filter-repo --version` reports supported version 2.38.0 or newer, then rerun Doctor. Manual advanced path: first create and verify a private local backup, use a separately reviewed offline history-cleaning procedure, and rerun the credential scanner before any publication.",
        )
    _require_repository_quiescence(root)
    with _acquire_history_lifecycle_lock(root, create=True) as lifecycle_lock:
        pinned_root = _fd_path(lifecycle_lock.root_descriptor)
        _prune_incomplete_transactions(lifecycle_lock.backup_descriptor)
        _require_repository_quiescence(pinned_root)
        _, common, objects = _repository_boundaries(pinned_root)
        refs = _refs(pinned_root, selected_refs)
        all_refs = _all_refs(pinned_root)
        object_evidence, estimated = _object_evidence(pinned_root, tuple(all_refs))
        used = _used_recovery_bytes(lifecycle_lock.root_descriptor)
        required = estimated + MIN_FREE_MARGIN_BYTES
        free = shutil.disk_usage(pinned_root).free
        if used + estimated > SHARED_RECOVERY_CAP_BYTES or free < required:
            raise OSError("insufficient verified recovery space")
        transaction_id = uuid.uuid4().hex
        incomplete_name = f".incomplete-{transaction_id}"
        transaction_descriptor = None
        transaction_created = False
        transaction_published = False
        try:
            os.mkdir(incomplete_name, 0o700, dir_fd=lifecycle_lock.backup_descriptor)
            transaction_created = True
            transaction_descriptor = os.open(
                incomplete_name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=lifecycle_lock.backup_descriptor,
            )
            transaction = _fd_path(transaction_descriptor)
            bundle = transaction / "history.bundle"
            _git(pinned_root, "bundle", "create", str(bundle), *all_refs, pass_fds=(transaction_descriptor,))
            os.chmod(bundle, 0o600)
            bundle_sha256, bundle_size = _sync_file_identity(bundle)
            if not bundle_size or stat.S_IMODE(bundle.stat().st_mode) != 0o600:
                raise OSError("bundle readback failed")
            _git(pinned_root, "bundle", "verify", str(bundle), pass_fds=(transaction_descriptor,))
            _write_restrictive(transaction / "objects.json", object_evidence)
            config_path = Path(_git(pinned_root, "rev-parse", "--path-format=absolute", "--git-path", "config").decode().strip())
            index_path = Path(_git(pinned_root, "rev-parse", "--path-format=absolute", "--git-path", "index").decode().strip())
            recovery_artifacts: dict[str, dict[str, object]] = {}
            for name, source in (("git-config.bin", config_path), ("index.bin", index_path)):
                if source.exists():
                    data = source.read_bytes()
                    _write_restrictive(transaction / name, data)
                    recovery_artifacts[name] = {
                        "absent": False,
                        "sha256": _sha(data),
                        "size": len(data),
                        "mode": stat.S_IMODE(source.stat().st_mode),
                    }
                else:
                    recovery_artifacts[name] = {"absent": True, "sha256": None, "size": 0, "mode": None}
            if (
                _used_recovery_bytes(lifecycle_lock.root_descriptor) > SHARED_RECOVERY_CAP_BYTES
                or shutil.disk_usage(transaction).free < MIN_FREE_MARGIN_BYTES
            ):
                raise OSError("shared recovery cap exceeded")
            created = now().astimezone(UTC)
            tool_sha256, tool_size = _sync_file_identity(tool)
            repository_state = _repository_state(pinned_root)
            core = {
            "schema_version": 1,
            "transaction_id": transaction_id,
            "phase": "prepared",
            "created_at": created.isoformat(),
            "minimum_delete_after": (created + timedelta(days=RETENTION_DAYS)).isoformat(),
            "successful_release_activations_at_creation": successful_release_activations,
            "minimum_successful_release_activations_for_deletion": successful_release_activations + RETENTION_RELEASES,
            "external_backup": {"verified_evidence_sha256": external_backup_evidence}
            if external_backup_evidence
            else {"no_external_backup_acknowledged": True},
            "selected_refs": refs,
            "all_refs": all_refs,
            "repository_state": repository_state,
            "credential_occurrences": _credential_occurrences(pinned_root, tuple(refs), credential_needles),
            "recovery_directory_identity": _directory_identity(transaction_descriptor),
            "before_object_evidence": {
                "sha256": _sha(object_evidence),
                "size": len(object_evidence),
                "file": "objects.json",
            },
            "primary_common_dir_identity": _sha(str(common).encode()),
            "primary_object_db_identity": _sha(str(objects).encode()),
            "bundle": {"sha256": bundle_sha256, "size": bundle_size, "verified": True},
            "recovery_artifacts": recovery_artifacts,
            "filter_repo": {
                "path_identity": _sha(str(tool).encode()),
                "sha256": tool_sha256,
                "size": tool_size,
            },
            }
            manifest = HistoryManifest.create(core)
            preview_sha = str(manifest["preview_sha256"])
            _write_restrictive(transaction / "manifest.json", manifest.serialize())
            _fsync_dir(transaction)
            os.rename(
                incomplete_name,
                transaction_id,
                src_dir_fd=lifecycle_lock.backup_descriptor,
                dst_dir_fd=lifecycle_lock.backup_descriptor,
            )
            transaction_published = True
            os.fsync(lifecycle_lock.backup_descriptor)
            return HistoryPreview(
                "prepared",
                transaction_id,
                preview_sha,
                "Optional privacy cleanup is prepared. Provider rotation is unchanged. Review the selected refs, then type the exact consent shown by Doctor to apply.",
            )
        except BaseException:
            if transaction_descriptor is not None:
                with suppress(OSError):
                    os.close(transaction_descriptor)
                transaction_descriptor = None
            if transaction_created and not transaction_published:
                _remove_unpublished_transaction(lifecycle_lock.backup_descriptor, incomplete_name)
            raise
        finally:
            if transaction_descriptor is not None:
                with suppress(OSError):
                    os.close(transaction_descriptor)


def _load_manifest(backup_descriptor: int, transaction_id: str) -> _LoadedTransaction:
    if not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
        raise ValueError("invalid history transaction id")
    descriptor = os.open(
        transaction_id,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=backup_descriptor,
    )
    try:
        transaction = _LoadedTransaction(descriptor, _fd_path(descriptor))
        manifest_path = transaction.path / "manifest.json"
        if manifest_path.is_symlink():
            raise ValueError("unsafe history transaction")
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o700 or stat.S_IMODE(manifest_path.stat().st_mode) != 0o600:
            raise PermissionError("history transaction permissions changed")
        manifest = HistoryManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
        if manifest.get("recovery_directory_identity") != _directory_identity(descriptor):
            raise ValueError("history recovery directory identity changed")
        transaction.manifest = manifest
        return transaction
    except BaseException:
        os.close(descriptor)
        raise


def _store_manifest(transaction: Path, manifest: HistoryManifest) -> None:
    _atomic_replace(
        transaction / "manifest.json",
        manifest.serialize(),
        0o600,
        "restrictive history artifact replacement failed",
    )


def _verify_bundle(root: Path, transaction: _LoadedTransaction, manifest: HistoryManifest) -> None:
    transaction_path = transaction.path
    bundle = transaction_path / "history.bundle"
    expected = manifest["bundle"]
    bundle_sha256, bundle_size = _sync_file_identity(bundle)
    if (
        bundle.is_symlink()
        or stat.S_IMODE(bundle.stat().st_mode) != 0o600
        or bundle_size != expected["size"]
        or bundle_sha256 != expected["sha256"]
    ):
        raise OSError("history recovery bundle identity changed")
    _git(root, "bundle", "verify", str(bundle), pass_fds=(transaction.descriptor,))
    _verify_recovery_artifacts(transaction_path, manifest)


def _verify_restrictive_artifact(path: Path, expected: dict[str, object], error: str) -> None:
    if expected.get("absent") is True:
        if path.exists():
            raise OSError(error)
        return
    if (
        path.is_symlink()
        or stat.S_IMODE(path.stat().st_mode) != 0o600
        or path.stat().st_size != expected["size"]
        or _sha(path.read_bytes()) != expected["sha256"]
    ):
        raise OSError(error)


def _verify_recovery_artifacts(transaction: Path, manifest: HistoryManifest) -> None:
    expected_evidence = manifest["before_object_evidence"]
    if expected_evidence.get("file") != "objects.json":
        raise OSError("history object evidence path changed")
    _verify_restrictive_artifact(
        transaction / expected_evidence["file"],
        expected_evidence,
        "history object evidence identity changed",
    )
    for name in ("git-config.bin", "index.bin"):
        _verify_restrictive_artifact(
            transaction / name,
            manifest["recovery_artifacts"][name],
            "history recovery artifact identity changed",
        )


def _selected_history_blobs(root: Path, refs: tuple[str, ...]):
    objects = sorted(set(line.split(b" ", 1)[0] for line in _git(root, "rev-list", "--objects", *refs).splitlines()))
    for oid in objects:
        if _git(root, "cat-file", "-t", oid.decode()).strip() == b"blob":
            yield _git(root, "cat-file", "blob", oid.decode())


def _occurrence_profile(blobs: tuple[bytes, ...], needle: bytes) -> list[list[int]]:
    profile: list[list[int]] = []
    for blob_index, data in enumerate(blobs):
        start = 0
        while (offset := data.find(needle, start)) >= 0:
            profile.append([blob_index, offset, offset + len(needle)])
            start = offset + 1
    return profile


def _credential_occurrences(
    root: Path, refs: tuple[str, ...], needles: tuple[bytes, ...]
) -> list[list[list[int]]]:
    blobs = tuple(_selected_history_blobs(root, refs))
    profiles = [_occurrence_profile(blobs, needle) for needle in needles]
    if any(not profile for profile in profiles):
        raise ValueError("each selected credential must occur in prepared history")
    return sorted(profiles)


def _scan_selected_history(root: Path, refs: tuple[str, ...], needles: tuple[bytes, ...]) -> HistoryResult:
    try:
        for data in _selected_history_blobs(root, refs):
            if any(needle in data for needle in needles):
                return "history-cleanup-pending"
        return "history-clean"
    except (OSError, RuntimeError, UnicodeDecodeError):
        return "history-scope-unknown"


def _selected_history_matches_occurrences(
    root: Path,
    refs: tuple[str, ...],
    needles: tuple[bytes, ...],
    expected: list[list[list[int]]],
) -> bool:
    """Rebind supplied secrets to exact prepared coordinates without persisting a value digest."""
    try:
        return _credential_occurrences(root, refs, needles) == expected
    except (OSError, RuntimeError, UnicodeDecodeError, ValueError):
        return False


def _restore_and_verify_git_config(
    root: Path,
    config_path: Path,
    expected: bytes,
    mode: int,
    expected_remotes: bytes,
) -> None:
    if not config_path.is_file() or config_path.read_bytes() != expected:
        _atomic_replace(config_path, expected, mode, "Git configuration restoration failed")
    if config_path.read_bytes() != expected or _git(root, "remote", "-v") != expected_remotes:
        raise RuntimeError("remote configuration could not be preserved")


def apply_history_cleanup(
    root: Path,
    preview: HistoryPreview,
    *,
    typed_consent: str,
    credential_needles: tuple[bytes, ...],
    filter_repo: Path | None = None,
) -> HistoryOutcome:
    if preview.state != "prepared" or not preview.transaction_id or not preview.preview_sha256:
        raise ValueError("a prepared history preview is required")
    if typed_consent != f"CLEAN OPTIONAL HISTORY {preview.transaction_id}":
        raise PermissionError("typed history-cleanup consent did not match")
    with _acquire_history_lifecycle_lock(root, create=False) as lifecycle_lock:
        with _load_manifest(lifecycle_lock.backup_descriptor, preview.transaction_id) as loaded_transaction:
            return _apply_history_cleanup_loaded(
                _fd_path(lifecycle_lock.root_descriptor),
                preview,
                loaded_transaction,
                credential_needles=credential_needles,
                filter_repo=filter_repo,
            )


def _apply_history_cleanup_loaded(
    root: Path,
    preview: HistoryPreview,
    loaded_transaction: _LoadedTransaction,
    *,
    credential_needles: tuple[bytes, ...],
    filter_repo: Path | None,
) -> HistoryOutcome:
    tool = resolve_filter_repo(filter_repo)
    if tool is None:
        raise RuntimeError("supported preinstalled git-filter-repo is no longer available")
    manifest = loaded_transaction.manifest
    assert manifest is not None
    transaction = loaded_transaction.path
    if manifest["preview_sha256"] != preview.preview_sha256 or manifest["phase"] != "prepared":
        raise ValueError("history preview or phase changed")
    if (
        len(set(credential_needles)) != len(credential_needles)
        or not _selected_history_matches_occurrences(
            root,
            tuple(sorted(manifest["selected_refs"])),
            credential_needles,
            manifest["credential_occurrences"],
        )
    ):
        raise ValueError("cleanup credential set changed")
    _, common, objects = _repository_boundaries(root)
    if (
        _sha(str(common).encode()) != manifest["primary_common_dir_identity"]
        or _sha(str(objects).encode()) != manifest["primary_object_db_identity"]
    ):
        raise RuntimeError("repository boundaries changed after preview")
    tool_sha256, tool_size = _sync_file_identity(tool)
    if manifest["filter_repo"] != {
        "path_identity": _sha(str(tool).encode()),
        "sha256": tool_sha256,
        "size": tool_size,
    }:
        raise RuntimeError("git-filter-repo identity changed after preview")
    _verify_bundle(root, loaded_transaction, manifest)
    selected_refs = tuple(sorted(manifest["selected_refs"]))
    if _refs(root, selected_refs) != manifest["selected_refs"]:
        raise RuntimeError("selected refs changed after preview")
    repository_state = manifest["repository_state"]
    if (
        _all_refs(root) != manifest["all_refs"]
        or _repository_state(root) != repository_state
    ):
        raise RuntimeError("repository state changed after preview")
    _require_repository_quiescence(root)
    config_path = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-path", "config").decode().strip())
    config_before = config_path.read_bytes()
    config_mode = stat.S_IMODE(config_path.stat().st_mode)
    remotes_before = _git(root, "remote", "-v")
    lines = b"".join(b"literal:" + item + b"==>***REMOVED REVOKED CREDENTIAL***\n" for item in credential_needles)
    manifest = manifest.begin_apply()
    _store_manifest(transaction, manifest)
    try:
        with tempfile.TemporaryFile() as replacement:
            replacement.write(lines)
            replacement.flush()
            os.fsync(replacement.fileno())
            replacement.seek(0)
            descriptor_path = f"/dev/fd/{replacement.fileno()}"
            command = [
                str(tool),
                "--force",
                "--replace-text",
                descriptor_path,
                "--refs",
                *selected_refs,
            ]
            _require_repository_quiescence(root)
            result = subprocess.run(
                command,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                env=_git_env(),
                pass_fds=(replacement.fileno(),),
            )
        _fsync_dir(transaction)
        if result.returncode:
            raise RuntimeError("git-filter-repo cleanup failed")
        _restore_and_verify_git_config(root, config_path, config_before, config_mode, remotes_before)
        after_refs = _refs(root, selected_refs)
        if after_refs == manifest["selected_refs"]:
            raise RuntimeError("selected refs were not rewritten")
        for oid in after_refs.values():
            _git(root, "cat-file", "-e", f"{oid}^{{object}}")
        after_all_refs = _all_refs(root)
        if {ref: oid for ref, oid in after_all_refs.items() if ref not in selected_refs} != {
            ref: oid for ref, oid in manifest["all_refs"].items() if ref not in selected_refs
        }:
            raise RuntimeError("unselected refs changed during history cleanup")
        expected_state = dict(repository_state)
        expected_state["remote_config_sha256"] = _sha(config_before)
        if _repository_state(root) != expected_state:
            raise RuntimeError("HEAD, index, worktree, or remote configuration changed")
        state = _scan_selected_history(root, selected_refs, credential_needles)
        manifest = manifest.record_applied(
            after_refs,
            after_all_refs,
            state,
            ("selected-refs",) if state == "history-scope-unknown" else (),
        )
        _store_manifest(transaction, manifest)
        return HistoryOutcome(
            state,
            preview.transaction_id,
            uninspected_scopes=("selected-refs",) if state == "history-scope-unknown" else (),
        )
    except BaseException:
        _fsync_dir(transaction)
        try:
            _restore_and_verify_git_config(root, config_path, config_before, config_mode, remotes_before)
        except (OSError, RuntimeError):
            pass
        try:
            current_refs = _refs(root, selected_refs)
            current_all_refs = _all_refs(root)
        except (OSError, RuntimeError, ValueError):
            current_refs = None
        guidance = "Do not push. Verify history.bundle, then use the deterministic rewind operation. Provider rotation is not reversed."
        recovery = manifest.record_recovery_required(
            guidance,
            current_refs,
            current_all_refs if current_refs is not None else None,
        )
        _store_manifest(transaction, recovery)
        return HistoryOutcome(
            "recovery-required",
            preview.transaction_id,
            guidance=guidance,
        )


def rewind_history_cleanup(root: Path, transaction_id: str) -> HistoryOutcome:
    with _acquire_history_lifecycle_lock(root, create=False) as lifecycle_lock:
        with _load_manifest(lifecycle_lock.backup_descriptor, transaction_id) as loaded_transaction:
            return _rewind_history_cleanup_loaded(
                _fd_path(lifecycle_lock.root_descriptor),
                transaction_id,
                loaded_transaction,
            )


def _rewind_history_cleanup_loaded(
    root: Path, transaction_id: str, loaded_transaction: _LoadedTransaction
) -> HistoryOutcome:
    manifest = loaded_transaction.manifest
    assert manifest is not None
    transaction = loaded_transaction.path
    _, common, objects = _repository_boundaries(root)
    if (
        _sha(str(common).encode()) != manifest["primary_common_dir_identity"]
        or _sha(str(objects).encode()) != manifest["primary_object_db_identity"]
    ):
        raise RuntimeError("repository boundaries changed after preview")
    _verify_bundle(root, loaded_transaction, manifest)
    if manifest["phase"] not in {"applied", "recovery-required"} or _all_refs(root) != manifest.get("after_all_refs"):
        return HistoryOutcome(
            "recovery-required",
            transaction_id,
            guidance="Automatic rewind was refused because current refs do not exactly match the recorded post-cleanup refs. Do not push; recover from the verified history.bundle manually. Provider rotation is not reversed.",
        )
    bundle = transaction / "history.bundle"
    unbundled = {}
    for line in _git(
        root, "bundle", "unbundle", str(bundle), pass_fds=(loaded_transaction.descriptor,)
    ).decode().splitlines():
        oid, ref = line.split(" ", 1)
        unbundled[ref] = oid
    if any(unbundled.get(ref) != oid for ref, oid in manifest["all_refs"].items()):
        raise RuntimeError("bundle ref readback mismatch")
    updates = ["start\n"]
    current = manifest["after_all_refs"]
    for ref, before_oid in sorted(manifest["all_refs"].items()):
        after_oid = current[ref]
        updates.append(f"update {ref} {before_oid} {after_oid}\n")
    for ref, after_oid in sorted(current.items()):
        if ref not in manifest["all_refs"]:
            updates.append(f"delete {ref} {after_oid}\n")
    updates.extend(["prepare\n", "commit\n"])
    _git(root, "update-ref", "--stdin", input_data="".join(updates).encode())
    config_path = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-path", "config").decode().strip())
    index_path = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-path", "index").decode().strip())
    for name, target in (("git-config.bin", config_path), ("index.bin", index_path)):
        artifact = manifest["recovery_artifacts"][name]
        if artifact["absent"]:
            target.unlink(missing_ok=True)
        else:
            _atomic_replace(
                target,
                (transaction / name).read_bytes(),
                artifact["mode"],
                "Git configuration restoration failed",
            )
    expected_state = manifest["repository_state"]
    if _all_refs(root) != manifest["all_refs"] or _repository_state(root) != expected_state:
        return HistoryOutcome(
            "recovery-required",
            transaction_id,
            guidance="Automatic rewind could not verify exact HEAD, index, worktree, ref, and remote restoration. Do not push; recover from the verified history.bundle and restrictive recovery artifacts manually. Provider rotation is not reversed.",
        )
    manifest = manifest.record_rewound()
    _store_manifest(transaction, manifest)
    return HistoryOutcome(
        "rewound",
        transaction_id,
        guidance="Selected refs were restored from the verified local bundle. Provider rotation was not reversed.",
    )


def preview_retention(
    root: Path,
    *,
    now: datetime,
    successful_release_activations: int,
) -> RetentionPreview:
    if now.utcoffset() is None or successful_release_activations < 0:
        raise ValueError("retention inputs must use an aware time and nonnegative release count")
    try:
        lifecycle_context = _acquire_history_lifecycle_lock(root, create=False)
    except FileNotFoundError:
        return _preview_retention_locked(root, now, successful_release_activations, (), None)
    with lifecycle_context as lifecycle_lock:
        _prune_incomplete_transactions(lifecycle_lock.backup_descriptor)
        transaction_ids = tuple(
            sorted(name for name in os.listdir(lifecycle_lock.backup_descriptor) if TRANSACTION_ID.fullmatch(name))
        )
        return _preview_retention_locked(
            _fd_path(lifecycle_lock.root_descriptor),
            now,
            successful_release_activations,
            transaction_ids,
            lifecycle_lock.backup_descriptor,
        )


def _history_transaction_is_deletion_eligible(root: Path, manifest: HistoryManifest) -> bool:
    if manifest.get("phase") != "applied" or manifest.get("post_cleanup_scan_state") != "history-clean":
        return False
    if manifest.get("post_cleanup_uninspected_scopes"):
        return False
    before = manifest.get("selected_refs")
    after = manifest.get("after_refs")
    after_all = manifest.get("after_all_refs")
    backup = manifest.get("external_backup")
    if not all(isinstance(value, dict) for value in (before, after, after_all, backup)):
        return False
    assert isinstance(before, dict)
    assert isinstance(after, dict)
    assert isinstance(after_all, dict)
    assert isinstance(backup, dict)
    if not before or set(before) != set(after):
        return False
    if any(
        not isinstance(after.get(ref), str)
        or not re.fullmatch(r"[0-9a-f]{40,64}", after[ref])
        or after[ref] == oid
        or after_all.get(ref) != after[ref]
        for ref, oid in before.items()
    ):
        return False
    backup_evidence = backup.get("verified_evidence_sha256")
    if backup.get("no_external_backup_acknowledged") is not True and not (
        isinstance(backup_evidence, str) and re.fullmatch(r"[0-9a-f]{64}", backup_evidence)
    ):
        return False
    try:
        for oid in after.values():
            _git(root, "cat-file", "-e", f"{oid}^{{object}}")
    except (OSError, RuntimeError):
        return False
    return True


def _preview_retention_locked(
    root: Path,
    now: datetime,
    successful_release_activations: int,
    transaction_ids: tuple[str, ...],
    backup_descriptor: int | None,
) -> RetentionPreview:
    manifests: list[tuple[str, HistoryManifest, datetime, datetime]] = []
    for transaction_id in transaction_ids:
        try:
            assert backup_descriptor is not None
            with _load_manifest(backup_descriptor, transaction_id) as loaded_transaction:
                manifest = loaded_transaction.manifest
                assert manifest is not None
                _verify_bundle(root, loaded_transaction, manifest)
                created = datetime.fromisoformat(manifest["created_at"])
                minimum_delete_after = datetime.fromisoformat(manifest["minimum_delete_after"])
                if created.utcoffset() is None or minimum_delete_after.utcoffset() is None:
                    raise ValueError("retention manifest times must be aware")
                if not isinstance(manifest["minimum_successful_release_activations_for_deletion"], int):
                    raise TypeError("retention release count must be an integer")
                if not isinstance(manifest["external_backup"], dict):
                    raise TypeError("retention backup posture must be an object")
                manifests.append((transaction_id, manifest, created, minimum_delete_after))
        except (KeyError, OSError, ValueError, RuntimeError, TypeError, PermissionError, json.JSONDecodeError):
            continue
    final_id = max(manifests, key=lambda item: item[2])[0] if manifests else None
    candidates = tuple(
        transaction_id
        for transaction_id, manifest, _, minimum_delete_after in manifests
        if transaction_id != final_id
        and _history_transaction_is_deletion_eligible(root, manifest)
        and now.astimezone(UTC) >= minimum_delete_after.astimezone(UTC)
        and successful_release_activations >= manifest["minimum_successful_release_activations_for_deletion"]
        and (
            manifest["external_backup"].get("no_external_backup_acknowledged") is True
            or bool(manifest["external_backup"].get("verified_evidence_sha256"))
        )
    )
    retained = tuple(transaction_id for transaction_id, *_ in manifests if transaction_id not in candidates)
    candidate_bytes = 0
    for transaction_id in candidates:
        assert backup_descriptor is not None
        with _load_manifest(backup_descriptor, transaction_id) as loaded_transaction:
            for name in os.listdir(loaded_transaction.descriptor):
                metadata = os.stat(name, dir_fd=loaded_transaction.descriptor, follow_symlinks=False)
                if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                    candidate_bytes += metadata.st_size
    evaluated_at = now.astimezone(UTC).isoformat()
    exact = _sha(
        _json_bytes(
            {
                "policy_version": 1,
                "candidate_ids": candidates,
                "candidate_manifest_sha256": {
                    transaction_id: manifest["preview_sha256"]
                    for transaction_id, manifest, *_ in manifests
                    if transaction_id in candidates
                },
                "candidate_bytes": candidate_bytes,
                "protected_final_id": final_id,
                "retained_ids": retained,
                "evaluated_at": evaluated_at,
                "successful_release_activations": successful_release_activations,
            }
        )
    )
    return RetentionPreview(
        candidates,
        exact,
        final_id,
        retained,
        evaluated_at,
        successful_release_activations,
        candidate_bytes,
    )


def delete_retention_candidates(
    root: Path,
    preview: RetentionPreview,
    *,
    acknowledged_ids: tuple[str, ...],
    exact_set_sha256: str,
) -> tuple[str, ...]:
    with _acquire_history_lifecycle_lock(root, create=False) as lifecycle_lock:
        _prune_incomplete_transactions(lifecycle_lock.backup_descriptor)
        transaction_ids = tuple(
            sorted(name for name in os.listdir(lifecycle_lock.backup_descriptor) if TRANSACTION_ID.fullmatch(name))
        )
        current = _preview_retention_locked(
            _fd_path(lifecycle_lock.root_descriptor),
            datetime.fromisoformat(preview.evaluated_at),
            preview.successful_release_activations,
            transaction_ids,
            lifecycle_lock.backup_descriptor,
        )
        if (
            current != preview
            or acknowledged_ids != preview.candidate_ids
            or exact_set_sha256 != preview.exact_set_sha256
        ):
            raise PermissionError("retention exact-set acknowledgement changed")
        if preview.protected_final_id in acknowledged_ids:
            raise PermissionError("final history bundle is protected")
        for transaction_id in acknowledged_ids:
            with _load_manifest(lifecycle_lock.backup_descriptor, transaction_id) as loaded_transaction:
                manifest = loaded_transaction.manifest
                assert manifest is not None
                _verify_bundle(root, loaded_transaction, manifest)
        for transaction_id in acknowledged_ids:
            with _load_manifest(lifecycle_lock.backup_descriptor, transaction_id) as loaded_transaction:
                for name in os.listdir(loaded_transaction.descriptor):
                    metadata = os.stat(name, dir_fd=loaded_transaction.descriptor, follow_symlinks=False)
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                        raise OSError("unsafe history retention artifact")
                    os.unlink(name, dir_fd=loaded_transaction.descriptor)
            os.rmdir(transaction_id, dir_fd=lifecycle_lock.backup_descriptor)
        os.fsync(lifecycle_lock.backup_descriptor)
    return acknowledged_ids
