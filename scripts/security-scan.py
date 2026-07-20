#!/usr/bin/env python3
"""Bounded, NUL-safe tracked-file secret scan with redacted diagnostics."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.utils.local_git import git_output

MAX_TRACKED_FILES = 25_000
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FINDINGS = 200
PATTERNS = (
    ("linear-api-key", re.compile(rb"lin_api_[A-Za-z0-9]{20,}")),
    ("anthropic-api-key", re.compile(rb"(?:sk-ant-api|sk-ant-)[0-9A-Za-z_-]{20,}")),
    ("github-token", re.compile(rb"ghp_[A-Za-z0-9]{20,}")),
    ("aws-access-key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("slack-token", re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("private-key", re.compile(rb"-----BEGIN (?:RSA|OPENSSH|EC|DSA) PRIVATE KEY-----")),
)
RAW_TASK_CREDENTIAL = re.compile(
    rb"(?m)^[ \t]*(?:api_key|token):[ \t]*[^<{ \t\r\n]"
)


def _tracked_paths() -> tuple[bytes, ...]:
    paths = tuple(path for path in git_output(Path.cwd(), "ls-files", "-z", profile="read-only").split(b"\0") if path)
    if len(paths) > MAX_TRACKED_FILES:
        raise RuntimeError("tracked-file count exceeded security scan bound")
    return paths


def _bounded_read(path: bytes) -> bytes:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise RuntimeError("no-follow tracked-file reads are unavailable")
    parts = tuple(part for part in path.split(b"/") if part)
    if not parts or path.startswith(b"/") or any(part in {b".", b".."} for part in parts):
        raise RuntimeError("tracked input path is unsafe")
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    directory = os.open(b".", os.O_RDONLY | no_follow | directory_flag | close_on_exec)
    descriptor = None
    try:
        for part in parts[:-1]:
            child = os.open(
                part,
                os.O_RDONLY | no_follow | directory_flag | close_on_exec,
                dir_fd=directory,
            )
            os.close(directory)
            directory = child
        before = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > MAX_FILE_BYTES
        ):
            raise RuntimeError("tracked input is unsafe or exceeds security scan bound")
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | no_follow | close_on_exec,
            dir_fd=directory,
        )
        opened = os.fstat(descriptor)
        chunks = []
        remaining = MAX_FILE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        current = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)
    identities = {
        (
            item.st_dev,
            item.st_ino,
            item.st_mode,
            item.st_nlink,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
        )
        for item in (before, opened, after, current)
    }
    if len(identities) != 1 or len(data) != before.st_size or len(data) > MAX_FILE_BYTES:
        raise RuntimeError("tracked input changed during security scan")
    return data


def _allowed(identity: str, allowlist: tuple[re.Pattern[str], ...]) -> bool:
    return any(rule.search(identity) for rule in allowlist)


def main() -> int:
    allowlist_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    rules: list[re.Pattern[str]] = []
    if allowlist_path and allowlist_path.is_file():
        for raw in allowlist_path.read_text(encoding="utf-8").splitlines():
            if raw and not raw.startswith("#"):
                rules.append(re.compile(raw))
    findings: list[tuple[str, int, str]] = []
    total = 0
    for raw_path in _tracked_paths():
        data = _bounded_read(raw_path)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise RuntimeError("tracked-file bytes exceeded security scan bound")
        display = os.fsdecode(raw_path)
        patterns = list(PATTERNS)
        if raw_path == b"System/integrations/config.yaml":
            patterns.append(("raw-task-credential", RAW_TASK_CREDENTIAL))
        for category, pattern in patterns:
            for match in pattern.finditer(data):
                line = data.count(b"\n", 0, match.start()) + 1
                identity = f"{display}:{line}:{category}"
                if not _allowed(identity, tuple(rules)):
                    findings.append((display, line, category))
                if len(findings) > MAX_FINDINGS:
                    raise RuntimeError("security finding count exceeded reporting bound")
    if not findings:
        return 0
    print("Potential secret leakage detected (matching values redacted):")
    for path, line, category in findings:
        print(json.dumps({"file": path, "line": line, "category": category}, ensure_ascii=True))
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, re.error) as error:
        print(f"Security scan failed closed: {error}", file=sys.stderr)
        raise SystemExit(2) from None
