"""Bounded local credential scanner with honest scope completion."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tarfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from core.utils.integration_credentials import inspect_active_mcp_config

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_WORKTREE_BYTES = 64 * 1024 * 1024
MAX_WORKTREE_FILES = 10_000
MAX_GIT_METADATA_BYTES = 64 * 1024 * 1024
MAX_GIT_METADATA_FILES = 10_000
MAX_ARCHIVE_MEMBER = 8 * 1024 * 1024
MAX_ARCHIVE_TOTAL = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10_000
MAX_OBJECT_BYTES = 64 * 1024 * 1024
MAX_OBJECTS = 25_000
MAX_GIT_OUTPUT = 16 * 1024 * 1024
SCAN_DEADLINE_SECONDS = 30.0
SCOPES = (
    "worktree",
    "index",
    "git-common-dir",
    "primary-object-db",
    "reachable-refs",
    "stashes",
    "tags",
    "selected-archives",
)


@dataclass(frozen=True)
class Finding:
    scope: str
    opaque_id: str


@dataclass(frozen=True)
class ScanReport:
    findings: tuple[Finding, ...]
    inspected_scopes: tuple[str, ...]
    uninspected_scopes: tuple[str, ...]
    uninspected_reasons: tuple[str, ...] = ()


def _opaque(scope: str, location: bytes) -> Finding:
    return Finding(scope, hashlib.sha256(scope.encode() + b"\0" + location).hexdigest()[:20])


def _git_binary() -> str:
    for candidate in ("/usr/bin/git", "/bin/git", shutil.which("git")):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).resolve())
    raise RuntimeError("sanitized Git unavailable")


def _git(root: Path, *args: str, input_data: bytes | None = None) -> bytes:
    result = subprocess.run(
        [
            _git_binary(),
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "credential.helper=",
            "-c",
            "protocol.file.allow=never",
            *args,
        ],
        cwd=root,
        input=input_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=SCAN_DEADLINE_SECONDS,
        env={
            "PATH": "/usr/bin:/bin",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_PAGER": "cat",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
        },
    )
    if result.returncode or len(result.stdout) > MAX_GIT_OUTPUT:
        raise RuntimeError("bounded sanitized local Git inspection failed")
    return result.stdout


def _bounded_file(path: Path) -> bytes:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > MAX_FILE_BYTES:
        raise OSError("unsafe-or-oversized-file")
    if metadata.st_mode & 0o444 == 0:
        raise OSError("unreadable-file")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        data = os.read(descriptor, MAX_FILE_BYTES + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    current = path.lstat()
    identities = {(item.st_dev, item.st_ino, item.st_size) for item in (metadata, opened, after, current)}
    if len(identities) != 1 or len(data) > MAX_FILE_BYTES:
        raise OSError("identity-changing-file")
    return data


def _archive_members(path: Path):
    total = count = 0
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            for info in infos:
                if info.is_dir():
                    continue
                mode = info.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                if file_type not in {0, stat.S_IFREG}:
                    raise ValueError("selected-archive-nonregular")
                count += 1
                total += info.file_size
                if count > MAX_ARCHIVE_MEMBERS or info.file_size > MAX_ARCHIVE_MEMBER or total > MAX_ARCHIVE_TOTAL:
                    raise ValueError("selected-archive-bound")
                with archive.open(info) as handle:
                    data = handle.read(MAX_ARCHIVE_MEMBER + 1)
                if len(data) != info.file_size:
                    raise ValueError("selected-archive-member-readback")
                yield str(count).encode(), data
    elif tarfile.is_tarfile(path):
        with tarfile.open(path, "r:*") as archive:
            for info in archive:
                if not info.isfile():
                    if info.issym() or info.islnk():
                        raise ValueError("selected-archive-nonregular")
                    continue
                count += 1
                total += info.size
                if count > MAX_ARCHIVE_MEMBERS or info.size > MAX_ARCHIVE_MEMBER or total > MAX_ARCHIVE_TOTAL:
                    raise ValueError("selected-archive-bound")
                handle = archive.extractfile(info)
                if handle is None:
                    raise ValueError("selected-archive-member-unreadable")
                data = handle.read(MAX_ARCHIVE_MEMBER + 1)
                if len(data) != info.size:
                    raise ValueError("selected-archive-member-readback")
                yield str(count).encode(), data
    else:
        raise ValueError("unsupported-selected-archive")


def scan_credentials(root: Path, needles: tuple[bytes, ...], selected_archives: tuple[Path, ...] = ()) -> ScanReport:
    """Inspect bounded approved subscopes; any skipped input makes its scope uninspected."""
    if not needles or any(not value for value in needles):
        raise ValueError("scanner requires non-empty exact credential bytes")
    deadline = time.monotonic() + SCAN_DEADLINE_SECONDS
    findings: list[Finding] = []
    inspected: set[str] = set()
    unknown: dict[str, str] = {}
    tracked: set[bytes] = set()

    try:
        tracked = set(_git(root, "ls-files", "-z").split(b"\0")) - {b""}
        others = set(_git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")) - {b""}
        total = 0
        for number, relative in enumerate(sorted(tracked | others), 1):
            if number > MAX_WORKTREE_FILES or time.monotonic() > deadline:
                raise OSError("worktree-bound")
            data = _bounded_file(root / os.fsdecode(relative))
            total += len(data)
            if total > MAX_WORKTREE_BYTES:
                raise OSError("worktree-bound")
            if any(value in data for value in needles):
                findings.append(_opaque("worktree", str(number).encode()))
        mcp = inspect_active_mcp_config(root)
        if not mcp.inspected:
            raise OSError(mcp.reason or "unsafe-active-config")
        if mcp.data and any(value in mcp.data for value in needles):
            findings.append(_opaque("worktree", b"active-config"))
        inspected.add("worktree")
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        unknown["worktree"] = "input-unavailable-unsafe-or-bound"

    try:
        total = 0
        for number, item in enumerate(sorted(tracked), 1):
            if number > MAX_WORKTREE_FILES or time.monotonic() > deadline:
                raise RuntimeError("index-bound")
            data = _git(root, "show", ":" + item.decode("utf-8"))
            total += len(data)
            if len(data) > MAX_FILE_BYTES or total > MAX_WORKTREE_BYTES:
                raise RuntimeError("index-bound")
            if any(value in data for value in needles):
                findings.append(_opaque("index", str(number).encode()))
        inspected.add("index")
    except (RuntimeError, UnicodeDecodeError, subprocess.TimeoutExpired):
        unknown["index"] = "blob-unavailable-or-bound"

    try:
        common = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip())
        objects = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-path", "objects").decode().strip())
        if objects != common / "objects" or (objects / "info/alternates").exists() or (common / "shallow").exists():
            raise RuntimeError("ambiguous-object-topology")
        config = _bounded_file(common / "config")
        if re.search(rb"(?im)^\s*promisor\s*=\s*true\s*$", config):
            raise RuntimeError("promisor-object-topology")
        metadata_files = [common / "packed-refs"] if (common / "packed-refs").exists() else []
        for metadata_root in (common / "refs", common / "logs"):
            if metadata_root.exists():
                for path in metadata_root.rglob("*"):
                    if path.is_dir() and not path.is_symlink():
                        continue
                    metadata_files.append(path)
        metadata_total = 0
        for number, path in enumerate(sorted(metadata_files), 1):
            if number > MAX_GIT_METADATA_FILES or time.monotonic() > deadline:
                raise OSError("git-metadata-bound")
            data = _bounded_file(path)
            metadata_total += len(data)
            if metadata_total > MAX_GIT_METADATA_BYTES:
                raise OSError("git-metadata-bound")
            if any(value in data for value in needles):
                findings.append(_opaque("git-common-dir", str(number).encode()))
        inspected.add("git-common-dir")

        object_lines = _git(root, "rev-list", "--objects", "--all", "--reflog").splitlines()
        if len(object_lines) > MAX_OBJECTS:
            raise RuntimeError("object-count-bound")
        object_total = 0
        for number, line in enumerate(object_lines, 1):
            if time.monotonic() > deadline:
                raise RuntimeError("object-deadline-bound")
            oid = line.split(b" ", 1)[0].decode("ascii")
            kind = _git(root, "cat-file", "-t", oid).strip()
            if kind != b"blob":
                continue
            size = int(_git(root, "cat-file", "-s", oid))
            object_total += size
            if size > MAX_FILE_BYTES or object_total > MAX_OBJECT_BYTES:
                raise RuntimeError("object-byte-bound")
            data = _git(root, "cat-file", "blob", oid)
            if len(data) != size:
                raise RuntimeError("object-readback")
            if any(value in data for value in needles):
                findings.append(_opaque("reachable-refs", str(number).encode()))
        inspected.update({"primary-object-db", "reachable-refs", "stashes", "tags"})
    except (OSError, RuntimeError, UnicodeDecodeError, ValueError, subprocess.TimeoutExpired):
        for scope in ("git-common-dir", "primary-object-db", "reachable-refs", "stashes", "tags"):
            unknown.setdefault(scope, "git-metadata-object-or-bound")

    if selected_archives:
        try:
            for archive_number, archive in enumerate(selected_archives, 1):
                if time.monotonic() > deadline:
                    raise ValueError("selected-archive-deadline")
                _bounded_file(archive)
                for member, data in _archive_members(archive):
                    if any(value in data for value in needles):
                        findings.append(_opaque("selected-archives", f"{archive_number}:".encode() + member))
            inspected.add("selected-archives")
        except (OSError, RuntimeError, ValueError, tarfile.TarError, zipfile.BadZipFile):
            unknown["selected-archives"] = "archive-input-member-or-bound"
    else:
        unknown["selected-archives"] = "not-selected"

    return ScanReport(
        tuple(sorted(set(findings), key=lambda finding: (finding.scope, finding.opaque_id))),
        tuple(sorted(inspected - unknown.keys())),
        tuple(sorted(unknown)),
        tuple(f"{scope}:{unknown[scope]}" for scope in sorted(unknown)),
    )
