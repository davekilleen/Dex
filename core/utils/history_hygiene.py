"""Opt-in local Git history privacy hygiene with verified recovery bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Literal

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
LIFECYCLE_LOCK = ".history-lifecycle.lock"


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


def _git_binary() -> Path:
    discovered = shutil.which("git")
    candidates = [Path("/usr/bin/git"), Path("/bin/git")]
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        if path := _safe_executable(candidate):
            return path
    raise RuntimeError("absolute Git executable is unavailable or unsafe")


def _git_env() -> dict[str, str]:
    executable_dirs = dict.fromkeys(
        (str(_git_binary().parent), str(Path(sys.executable).resolve().parent), "/usr/bin", "/bin")
    )
    return {
        "PATH": os.pathsep.join(executable_dirs),
        "HOME": os.environ.get("HOME", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
    }


def _git(root: Path, *args: str, input_data: bytes | None = None, pass_fds: tuple[int, ...] = ()) -> bytes:
    result = subprocess.run(
        [str(_git_binary()), "-c", "core.hooksPath=/dev/null", "-c", "credential.helper=", *args],
        cwd=root,
        input=input_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=_git_env(),
        pass_fds=pass_fds,
    )
    if result.returncode:
        raise RuntimeError("sanitized local Git operation failed")
    return result.stdout


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
        if relative.startswith(b"System/.dex/adoption/history-backups/"):
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


def _open_directory_chain(root: Path, parts: tuple[str, ...], *, create: bool = False) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, flags)
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


def _open_backup_root(root: Path, *, create: bool = False) -> int:
    return _open_directory_chain(root, ("System", ".dex", "adoption", "history-backups"), create=create)


def _directory_identity(descriptor: int) -> dict[str, int]:
    metadata = os.fstat(descriptor)
    return {"device": metadata.st_dev, "inode": metadata.st_ino}


@dataclass
class _LoadedTransaction:
    descriptor: int
    path: Path
    manifest: dict[str, object] | None = None

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
    backup_descriptor: int
    descriptor: int

    def close(self) -> None:
        if self.descriptor >= 0:
            if fcntl is not None:
                fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            os.close(self.descriptor)
            self.descriptor = -1
        if self.backup_descriptor >= 0:
            os.close(self.backup_descriptor)
            self.backup_descriptor = -1


def _acquire_history_lifecycle_lock(root: Path, *, create: bool) -> _HistoryLifecycleLock:
    if fcntl is None:
        raise RuntimeError("history lifecycle locking is unavailable")
    backup_descriptor = _open_backup_root(root, create=create)
    descriptor = None
    created = False
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            descriptor = os.open(LIFECYCLE_LOCK, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=backup_descriptor)
            created = True
            os.fsync(backup_descriptor)
        except FileExistsError:
            descriptor = os.open(LIFECYCLE_LOCK, flags, dir_fd=backup_descriptor)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != 0o600
        ):
            raise OSError("unsafe history lifecycle lock")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        current = os.stat(LIFECYCLE_LOCK, dir_fd=backup_descriptor, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise OSError("history lifecycle lock identity changed")
        return _HistoryLifecycleLock(backup_descriptor, descriptor)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            with suppress(FileNotFoundError):
                os.unlink(LIFECYCLE_LOCK, dir_fd=backup_descriptor)
                os.fsync(backup_descriptor)
        os.close(backup_descriptor)
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


def _used_recovery_bytes(root: Path) -> int:
    try:
        adoption = _open_directory_chain(root, ("System", ".dex", "adoption"))
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
    if not incomplete and TRANSACTION_ID.fullmatch(name) is None:
        raise OSError("unsafe unpublished history transaction name")
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=backup_descriptor,
    )
    try:
        entries = os.listdir(descriptor)
        if not incomplete and "manifest.json" in entries:
            return
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


def _prune_incomplete_transactions(root: Path) -> None:
    try:
        backup_descriptor = _open_backup_root(root)
    except FileNotFoundError:
        return
    try:
        for name in sorted(os.listdir(backup_descriptor)):
            if INCOMPLETE_TRANSACTION.fullmatch(name) or TRANSACTION_ID.fullmatch(name):
                _remove_unpublished_transaction(backup_descriptor, name)
    finally:
        os.close(backup_descriptor)


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
            "Optional history privacy cleanup is unavailable because a supported preinstalled git-filter-repo was not found. Security remains fixed; Dex did not install or run anything.",
        )
    lifecycle_lock = _acquire_history_lifecycle_lock(root, create=True)
    try:
        _prune_incomplete_transactions(root)
        _, common, objects = _repository_boundaries(root)
        refs = _refs(root, selected_refs)
        all_refs = _all_refs(root)
        object_evidence, estimated = _object_evidence(root, tuple(all_refs))
        used = _used_recovery_bytes(root)
        required = estimated + MIN_FREE_MARGIN_BYTES
        free = shutil.disk_usage(root).free
        if used + estimated > SHARED_RECOVERY_CAP_BYTES or free < required:
            raise OSError("insufficient verified recovery space")
    except BaseException:
        lifecycle_lock.close()
        raise
    transaction_id = uuid.uuid4().hex
    incomplete_name = f".incomplete-{transaction_id}"
    backup_descriptor = None
    transaction_descriptor = None
    transaction_created = False
    transaction_published = False
    try:
        backup_descriptor = _open_backup_root(root, create=True)
        os.mkdir(incomplete_name, 0o700, dir_fd=backup_descriptor)
        transaction_created = True
        transaction_descriptor = os.open(
            incomplete_name,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=backup_descriptor,
        )
        transaction = _fd_path(transaction_descriptor)
        bundle = transaction / "history.bundle"
        _git(root, "bundle", "create", str(bundle), *all_refs, pass_fds=(transaction_descriptor,))
        os.chmod(bundle, 0o600)
        bundle_sha256, bundle_size = _sync_file_identity(bundle)
        if not bundle_size or stat.S_IMODE(bundle.stat().st_mode) != 0o600:
            raise OSError("bundle readback failed")
        _git(root, "bundle", "verify", str(bundle), pass_fds=(transaction_descriptor,))
        _write_restrictive(transaction / "objects.json", object_evidence)
        config_path = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-path", "config").decode().strip())
        index_path = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-path", "index").decode().strip())
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
            _used_recovery_bytes(root) > SHARED_RECOVERY_CAP_BYTES
            or shutil.disk_usage(transaction).free < MIN_FREE_MARGIN_BYTES
        ):
            raise OSError("shared recovery cap exceeded")
        created = now().astimezone(UTC)
        tool_sha256, tool_size = _sync_file_identity(tool)
        repository_state = _repository_state(root)
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
            "credential_occurrences": _credential_occurrences(root, tuple(refs), credential_needles),
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
        preview_sha = _sha(_json_bytes(core))
        manifest = {**core, "preview_sha256": preview_sha}
        _write_restrictive(transaction / "manifest.json", _json_bytes(manifest))
        _fsync_dir(transaction)
        os.rename(
            incomplete_name,
            transaction_id,
            src_dir_fd=backup_descriptor,
            dst_dir_fd=backup_descriptor,
        )
        transaction_published = True
        os.fsync(backup_descriptor)
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
        if transaction_created and not transaction_published and backup_descriptor is not None:
            _remove_unpublished_transaction(backup_descriptor, incomplete_name)
        raise
    finally:
        if transaction_descriptor is not None:
            with suppress(OSError):
                os.close(transaction_descriptor)
        if backup_descriptor is not None:
            with suppress(OSError):
                os.close(backup_descriptor)
        lifecycle_lock.close()


def _load_manifest(root: Path, transaction_id: str) -> _LoadedTransaction:
    if not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
        raise ValueError("invalid history transaction id")
    backup = _open_backup_root(root)
    try:
        descriptor = os.open(
            transaction_id,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=backup,
        )
    finally:
        os.close(backup)
    try:
        transaction = _LoadedTransaction(descriptor, _fd_path(descriptor))
        manifest_path = transaction.path / "manifest.json"
        if manifest_path.is_symlink():
            raise ValueError("unsafe history transaction")
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o700 or stat.S_IMODE(manifest_path.stat().st_mode) != 0o600:
            raise PermissionError("history transaction permissions changed")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        preview_sha = manifest.pop("preview_sha256")
        if preview_sha != _sha(_json_bytes(manifest)):
            raise ValueError("history preview manifest changed")
        manifest["preview_sha256"] = preview_sha
        if manifest.get("recovery_directory_identity") != _directory_identity(descriptor):
            raise ValueError("history recovery directory identity changed")
        transaction.manifest = manifest
        return transaction
    except BaseException:
        os.close(descriptor)
        raise


def _store_manifest(transaction: Path, manifest: dict[str, object]) -> None:
    unsigned = {key: value for key, value in manifest.items() if key != "preview_sha256"}
    manifest["preview_sha256"] = _sha(_json_bytes(unsigned))
    _atomic_replace(
        transaction / "manifest.json",
        _json_bytes(manifest),
        0o600,
        "restrictive history artifact replacement failed",
    )


def _verify_bundle(root: Path, transaction: _LoadedTransaction, manifest: dict[str, object]) -> None:
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


def _verify_recovery_artifacts(transaction: Path, manifest: dict[str, object]) -> None:
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
    with _load_manifest(root, preview.transaction_id) as loaded_transaction:
        return _apply_history_cleanup_loaded(
            root,
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
    config_path = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-path", "config").decode().strip())
    config_before = config_path.read_bytes()
    config_mode = stat.S_IMODE(config_path.stat().st_mode)
    remotes_before = _git(root, "remote", "-v")
    lines = b"".join(b"literal:" + item + b"==>***REMOVED REVOKED CREDENTIAL***\n" for item in credential_needles)
    manifest["phase"] = "applying"
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
        manifest["phase"] = "applied"
        manifest["after_refs"] = after_refs
        manifest["after_all_refs"] = after_all_refs
        state = _scan_selected_history(root, selected_refs, credential_needles)
        manifest["post_cleanup_scan_state"] = state
        if state == "history-scope-unknown":
            manifest["post_cleanup_uninspected_scopes"] = ["selected-refs"]
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
        recovery = {
            **manifest,
            "phase": "recovery-required",
            "recovery_guidance": "Do not push. Verify history.bundle, then use the deterministic rewind operation. Provider rotation is not reversed.",
        }
        if current_refs is not None:
            recovery["after_refs"] = current_refs
            recovery["after_all_refs"] = current_all_refs
        _store_manifest(transaction, recovery)
        return HistoryOutcome(
            "recovery-required",
            preview.transaction_id,
            guidance=recovery["recovery_guidance"],
        )


def rewind_history_cleanup(root: Path, transaction_id: str) -> HistoryOutcome:
    with _load_manifest(root, transaction_id) as loaded_transaction:
        return _rewind_history_cleanup_loaded(root, transaction_id, loaded_transaction)


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
    manifest["phase"] = "rewound"
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
    manifests: list[tuple[str, dict[str, object], datetime, datetime]] = []
    try:
        lifecycle_lock = _acquire_history_lifecycle_lock(root, create=False)
    except FileNotFoundError:
        transaction_ids = []
    else:
        try:
            _prune_incomplete_transactions(root)
            transaction_ids = sorted(
                name for name in os.listdir(lifecycle_lock.backup_descriptor) if TRANSACTION_ID.fullmatch(name)
            )
        finally:
            lifecycle_lock.close()
    for transaction_id in transaction_ids:
        try:
            with _load_manifest(root, transaction_id) as loaded_transaction:
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
        with _load_manifest(root, transaction_id) as loaded_transaction:
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
    current = preview_retention(
        root,
        now=datetime.fromisoformat(preview.evaluated_at),
        successful_release_activations=preview.successful_release_activations,
    )
    if current != preview or acknowledged_ids != preview.candidate_ids or exact_set_sha256 != preview.exact_set_sha256:
        raise PermissionError("retention exact-set acknowledgement changed")
    if preview.protected_final_id in acknowledged_ids:
        raise PermissionError("final history bundle is protected")
    for transaction_id in acknowledged_ids:
        with _load_manifest(root, transaction_id) as loaded_transaction:
            manifest = loaded_transaction.manifest
            assert manifest is not None
            _verify_bundle(root, loaded_transaction, manifest)
    backup_descriptor = _open_backup_root(root)
    try:
        for transaction_id in acknowledged_ids:
            with _load_manifest(root, transaction_id) as loaded_transaction:
                for name in os.listdir(loaded_transaction.descriptor):
                    metadata = os.stat(name, dir_fd=loaded_transaction.descriptor, follow_symlinks=False)
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                        raise OSError("unsafe history retention artifact")
                    os.unlink(name, dir_fd=loaded_transaction.descriptor)
            os.rmdir(transaction_id, dir_fd=backup_descriptor)
        os.fsync(backup_descriptor)
    finally:
        os.close(backup_descriptor)
    return acknowledged_ids
