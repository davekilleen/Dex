"""Scope-bounded, local-only credential scanner with opaque findings."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_ARCHIVE_MEMBER = 8 * 1024 * 1024
MAX_ARCHIVE_TOTAL = 64 * 1024 * 1024
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


def _opaque(scope: str, location: bytes) -> Finding:
    return Finding(scope, hashlib.sha256(scope.encode() + b"\0" + location).hexdigest()[:20])


def _git(root: Path, *args: str, input_data: bytes | None = None) -> bytes:
    git = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper=", "-c", "protocol.file.allow=never", *args],
        cwd=root,
        input=input_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env={
            "PATH": os.environ.get("PATH", ""),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_PAGER": "cat",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
        },
    )
    if git.returncode:
        raise RuntimeError("sanitized local Git inspection failed")
    return git.stdout


def _archive_members(path: Path):
    total = 0
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir() or info.file_size > MAX_ARCHIVE_MEMBER:
                    continue
                total += info.file_size
                if total > MAX_ARCHIVE_TOTAL:
                    raise ValueError("selected archive exceeds scan bound")
                with archive.open(info) as handle:
                    yield info.filename.encode(), handle.read(MAX_ARCHIVE_MEMBER + 1)
    elif tarfile.is_tarfile(path):
        with tarfile.open(path, "r:*") as archive:
            for info in archive:
                if not info.isfile() or info.size > MAX_ARCHIVE_MEMBER:
                    continue
                total += info.size
                if total > MAX_ARCHIVE_TOTAL:
                    raise ValueError("selected archive exceeds scan bound")
                handle = archive.extractfile(info)
                if handle:
                    yield info.name.encode(), handle.read(MAX_ARCHIVE_MEMBER + 1)
    else:
        raise ValueError("unsupported selected archive")


def scan_credentials(root: Path, needles: tuple[bytes, ...], selected_archives: tuple[Path, ...] = ()) -> ScanReport:
    """Inspect explicit local scopes. Findings never contain paths or matched bytes."""
    if not needles or any(not value for value in needles):
        raise ValueError("scanner requires non-empty exact credential bytes")
    findings: list[Finding] = []
    inspected: set[str] = set()
    unknown: set[str] = set()
    tracked = set(_git(root, "ls-files", "-z").split(b"\0"))
    others = set(_git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"))
    mcp_config = root / ".mcp.json"
    if mcp_config.exists() and not mcp_config.is_symlink() and mcp_config.is_file():
        if any(value in mcp_config.read_bytes() for value in needles):
            findings.append(_opaque("worktree", b"active-mcp-config"))
    for relative in sorted((tracked | others) - {b""}):
        try:
            path = root / os.fsdecode(relative)
            if path.is_symlink() or not path.is_file():
                continue
            data = path.read_bytes()
            if any(value in data for value in needles):
                findings.append(_opaque("worktree", relative))
        except OSError:
            unknown.add("worktree")
    inspected.add("worktree")
    try:
        for item in sorted(tracked - {b""}):
            try:
                data = _git(root, "show", ":" + item.decode("utf-8"))
            except (RuntimeError, UnicodeDecodeError):
                continue
            if any(value in data for value in needles):
                findings.append(_opaque("index", item))
        inspected.add("index")
    except (RuntimeError, UnicodeDecodeError):
        unknown.add("index")
    try:
        common = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip())
        obj = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-path", "objects").decode().strip())
        if common.is_dir():
            inspected.add("git-common-dir")
        else:
            unknown.add("git-common-dir")
        if obj.is_dir() and (obj == common / "objects"):
            inspected.add("primary-object-db")
        else:
            unknown.add("primary-object-db")
        ambiguous_topology = (
            (obj / "info" / "alternates").exists()
            or (common / "shallow").exists()
            or "promisor = true" in (common / "config").read_text(encoding="utf-8", errors="ignore").lower()
        )
        refs = _git(
            root, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes", "refs/tags", "refs/stash"
        ).splitlines()
        blobs = (
            b""
            if ambiguous_topology
            else (_git(root, "rev-list", "--objects", *[r.decode() for r in refs]) if refs else b"")
        )
        for line in blobs.splitlines():
            oid = line.split(b" ", 1)[0]
            try:
                data = _git(root, "cat-file", "blob", oid.decode())
            except RuntimeError:
                continue
            if any(value in data for value in needles):
                findings.append(_opaque("reachable-refs", oid))
        if ambiguous_topology:
            unknown.add("reachable-refs")
        else:
            inspected.add("reachable-refs")
        (inspected if any(r.startswith(b"refs/stash") for r in refs) else inspected).add("stashes")
        inspected.add("tags")
    except (RuntimeError, UnicodeDecodeError):
        unknown.update({"git-common-dir", "primary-object-db", "reachable-refs", "stashes", "tags"})
    if selected_archives:
        try:
            for archive in selected_archives:
                for name, data in _archive_members(archive):
                    safe_name = str(PurePosixPath(os.fsdecode(name))).encode()
                    if any(value in data for value in needles):
                        findings.append(_opaque("selected-archives", safe_name))
            inspected.add("selected-archives")
        except (OSError, ValueError):
            unknown.add("selected-archives")
    else:
        unknown.add("selected-archives")
    return ScanReport(
        tuple(sorted(set(findings), key=lambda f: (f.scope, f.opaque_id))),
        tuple(sorted(inspected - unknown)),
        tuple(sorted(unknown)),
    )
