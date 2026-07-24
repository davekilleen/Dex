#!/usr/bin/env python3
"""Static full-tree sweep for founder-personal content in tracked files.

Unlike ``scripts/pii_gate.py`` (a diff gate that only inspects newly added lines),
this walks the *entire* tracked tree so pre-existing founder baggage cannot be
grandfathered in. It fails when the founder's name, employer, or a stale runtime
reference appears in a tracked file that is not covered by
``scripts/founder-content-allowlist.txt``.

Tokens are matched on word boundaries, so the canonical ``davekilleen`` GitHub
handle/URL and identifiers like ``next_cursor`` do not trip the gate; only the
standalone words ``dave``/``killeen``/``pendo``/``cursor`` do. Every legitimate
remaining occurrence (branding, license, canonical URLs, real integrations, the
supported Cursor harness, test fixtures) is listed, with a reason, in the
allowlist file.

Personal-layout paths are detected separately and reported with the token
``personal-path``. The only concrete macOS user names exempted are the documented
examples ``alice``, ``testuser``, and ``yourname``.

Allowlist entries are regexes matched against a ``path:line:token`` identity,
mirroring ``scripts/security-scan.py``.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.utils.local_git import git_output

MAX_TRACKED_FILES = 25_000
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FINDINGS = 500

# Case-insensitive, word-boundary matched. \b treats "_" as a word char, so
# "next_cursor"/"seenCursors" and the "davekilleen" handle are intentionally NOT
# matched; only standalone founder-identity words are.
TOKENS = ("dave", "killeen", "pendo", "cursor")
PATTERNS = tuple((token, re.compile(rb"(?i)\b" + token.encode() + rb"\b")) for token in TOKENS)
PERSONAL_PATH_PATTERNS = (
    re.compile(rb"~/dex/"),
    re.compile(rb"~/Vault(?:/|\b)"),
    re.compile(rb"\$HOME/dex(?:/|\b)"),
    re.compile(
        rb"(?:path|os\.path)\.join\(\s*os\.homedir\(\)\s*,\s*['\"](?:Vault|dex)['\"]"
    ),
    # The macOS home prefix is split across two literals so the repo's other
    # scanners (verify-distribution, check-path-consistency), which grep for the
    # contiguous byte sequence, never match this script itself.
    re.compile(rb"/Use" rb"rs/(?!(?:alice|testuser|yourname)/)[^/\\\s:'\"<>|]+/"),
)
ALL_PATTERNS = PATTERNS + tuple(("personal-path", pattern) for pattern in PERSONAL_PATH_PATTERNS)


def _tracked_paths() -> tuple[bytes, ...]:
    paths = tuple(
        path
        for path in git_output(Path.cwd(), "ls-files", "-z", profile="read-only").split(b"\0")
        if path
    )
    if len(paths) > MAX_TRACKED_FILES:
        raise RuntimeError("tracked-file count exceeded founder-content scan bound")
    return paths


def _read_tracked_file(path: bytes) -> bytes | None:
    """Read a tracked working-tree file, skipping symlinks and oversized blobs."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    import stat as _stat

    if not _stat.S_ISREG(info.st_mode):  # skip symlinks and special files
        return None
    if info.st_size > MAX_FILE_BYTES:
        raise RuntimeError("tracked input exceeds founder-content scan bound")
    with open(path, "rb") as handle:
        return handle.read(MAX_FILE_BYTES + 1)


def _load_allowlist(allowlist_path: Path | None) -> tuple[re.Pattern[str], ...]:
    rules: list[re.Pattern[str]] = []
    if allowlist_path and allowlist_path.is_file():
        for raw in allowlist_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                rules.append(re.compile(line))
    return tuple(rules)


def _allowed(identity: str, allowlist: tuple[re.Pattern[str], ...]) -> bool:
    return any(rule.search(identity) for rule in allowlist)


def main() -> int:
    allowlist_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    allowlist = _load_allowlist(allowlist_path)
    findings: list[tuple[str, int, str]] = []
    total = 0
    for raw_path in _tracked_paths():
        data = _read_tracked_file(raw_path)
        if data is None:
            continue
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise RuntimeError("tracked-file bytes exceeded founder-content scan bound")
        if b"\x00" in data:  # skip binary files
            continue
        display = os.fsdecode(raw_path)
        for token, pattern in ALL_PATTERNS:
            for match in pattern.finditer(data):
                line = data.count(b"\n", 0, match.start()) + 1
                identity = f"{display}:{line}:{token}"
                if not _allowed(identity, allowlist):
                    findings.append((display, line, token))
                if len(findings) > MAX_FINDINGS:
                    raise RuntimeError("founder-content finding count exceeded reporting bound")
    if not findings:
        return 0
    print("Founder-personal content detected in tracked files outside the allowlist:")
    print("(add a reviewed exception to scripts/founder-content-allowlist.txt, or remove the content)")
    for path, line, token in sorted(set(findings)):
        print(json.dumps({"file": path, "line": line, "token": token}, ensure_ascii=True))
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, re.error) as error:
        print(f"Founder-content scan failed closed: {error}", file=sys.stderr)
        raise SystemExit(2) from None
