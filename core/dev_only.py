"""Dev-only leftover patterns shared by catalog generation and assessment.

``.distignore`` is export-ignored, so a release catalog may carry the same
pattern list as ``dev_only_patterns``. Matching stays conservative: directory
prefixes, exact paths, and gitignore-style globs. A missing list is not an
error — callers fall back to today's unproved behaviour.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

DEV_LEFTOVER_ARCHIVE_PREFIX = "System/.dex/archive/"
# Contract-level bound for the tidy write operation. Must stay in lockstep
# with ``.distignore`` (asserted by tests when that file is present). The
# catalog may carry the same list; a missing catalog field does not use this
# bound for classification, only for write authorization.
CONTRACT_TIDY_PATTERNS = (
    ".logs/",
    "System/.dex/adoption/credential-journals/",
    "System/.dex/adoption/history-backups/",
    "System/.dex/customization-migrations/",
    "extensions/tau-mirror/",
    ".github/",
    ".ci/",
    ".gitattributes",
    "pyproject.toml",
    "requirements-dev.txt",
    "vitest.config.mjs",
    ".husky/",
    "core/tests/",
    "core/mcp/tests/",
    "core/migrations/tests/",
    "core/integrations/connection-manager/*.test.cjs",
    "core/integrations/connection-manager/hardening.child.cjs",
    ".claude/hooks/tests/",
    ".scripts/lib/tests/",
    ".scripts/meeting-intel/__tests__/",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "DISTRIBUTION_READY.md",
    "scripts/",
    ".claude/skills/dex-orient/",
    ".ao-issue.md",
    ".codex/",
    ".obsidianignore",
    "_import/",
    "bun.lock",
    "memory/",
    ".distignore",
    "System/knowledge-half-life.yaml",
    "System/knowledge-half-life.example.yaml",
    "install.ps1",
)
DEV_LEFTOVER_ARCHIVE_NAME_PREFIX = "dev-leftovers-"
TIDY_DEV_LEFTOVERS_DRY_RUN = (
    "python3 -m core.customization_migration.cli tidy-dev-leftovers --dry-run"
)
REANCHOR_COMMAND = "python3 -m core.update.reanchor_cli"

# Dex-known config that assessment must list but must not treat as incomplete.
DEX_KNOWN_RESTRICTED_PATHS = frozenset(
    {
        ".claude/settings.json",
        ".claude/settings.local.json",
    }
)


def parse_distignore_patterns(text: str) -> tuple[str, ...]:
    """Return the closed, ordered pattern list from a ``.distignore`` body."""
    patterns: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line in seen:
            continue
        seen.add(line)
        patterns.append(line)
    return tuple(patterns)


def load_distignore_patterns(path: Path) -> tuple[str, ...]:
    return parse_distignore_patterns(path.read_text(encoding="utf-8"))


def matches_dev_only_pattern(path: str, patterns: Sequence[str]) -> bool:
    """True when *path* is covered by a release's dev-only pattern list."""
    if not path or not patterns:
        return False
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return False
    for pattern in patterns:
        if _path_matches_one_pattern(path, pattern):
            return True
    return False


def _path_matches_one_pattern(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        prefix = pattern[:-1]
        return path == prefix or path.startswith(prefix + "/")
    if any(token in pattern for token in "*?["):
        return fnmatch.fnmatchcase(path, pattern)
    return path == pattern or path.startswith(pattern + "/")


def internal_object_store_root(path: str) -> str | None:
    """Return the ``.dex/*.git`` object-store root that contains *path*, if any."""
    parts = PurePosixPath(path).parts
    for index, part in enumerate(parts):
        if not part.endswith(".git") or part == ".git":
            continue
        if index >= 1 and parts[index - 1] == ".dex":
            return PurePosixPath(*parts[: index + 1]).as_posix()
    return None


def archive_dir_for(stamp: str) -> str:
    if not stamp or "/" in stamp or "\\" in stamp or "\x00" in stamp:
        raise ValueError("archive stamp is not canonical")
    return f"{DEV_LEFTOVER_ARCHIVE_PREFIX}{DEV_LEFTOVER_ARCHIVE_NAME_PREFIX}{stamp}"


def is_dev_leftover_archive_path(path: str) -> bool:
    return path.startswith(DEV_LEFTOVER_ARCHIVE_PREFIX)


def is_tidable_leftover_source(path: str) -> bool:
    """True when the ownership contract may move this leftover source path."""
    return matches_dev_only_pattern(path, CONTRACT_TIDY_PATTERNS)


def archived_source_path(archive_dir: str, source_path: str) -> str:
    return f"{archive_dir.rstrip('/')}/{source_path}"


__all__ = [
    "CONTRACT_TIDY_PATTERNS",
    "DEX_KNOWN_RESTRICTED_PATHS",
    "DEV_LEFTOVER_ARCHIVE_NAME_PREFIX",
    "DEV_LEFTOVER_ARCHIVE_PREFIX",
    "REANCHOR_COMMAND",
    "TIDY_DEV_LEFTOVERS_DRY_RUN",
    "archive_dir_for",
    "archived_source_path",
    "internal_object_store_root",
    "is_dev_leftover_archive_path",
    "is_tidable_leftover_source",
    "load_distignore_patterns",
    "matches_dev_only_pattern",
    "parse_distignore_patterns",
]
