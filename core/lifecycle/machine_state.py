"""Read-only machine-local and Git-state evidence for lifecycle reports."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from core.lifecycle.filesystem import DEFAULT_MAX_ENTRIES, WalkReport, walk_read_only
from core.lifecycle.secrets import assert_no_denied_metadata, redact_document
from core.utils.tracked_ignored import TrackedIgnoredError, query_tracked_ignored

PROJECTION_PATHS = (
    ".mcp.json",
    "System/.dex-sessions.db",
    "System/.dex/ritual-intelligence.db",
    "System/.dex/contacts.json",
    "System/.dex/gardener.json",
    "System/.dex/entity-suggestions.json",
    "System/.dex/entity-verification.json",
)


@dataclass(frozen=True)
class TrackedIgnoredEvidence:
    state: str
    paths: tuple[str, ...]
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"state": self.state, "paths": list(self.paths), "error": self.error}


@dataclass(frozen=True)
class MachineStateReport:
    platform: str
    git_metadata_present: bool
    tracked_despite_ignored: TrackedIgnoredEvidence
    projections_present: tuple[str, ...]
    symlinks: tuple[str, ...]
    special_files: tuple[str, ...]
    case_collisions: tuple[tuple[str, ...], ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        raw = {
            "platform": self.platform,
            "git_metadata_present": self.git_metadata_present,
            "tracked_despite_ignored": self.tracked_despite_ignored.to_dict(),
            "projections_present": list(self.projections_present),
            "symlinks": list(self.symlinks),
            "special_files": list(self.special_files),
            "case_collisions": [list(paths) for paths in self.case_collisions],
            "errors": list(self.errors),
        }
        redacted = redact_document(raw)
        assert_no_denied_metadata(redacted)
        assert isinstance(redacted, dict)
        return redacted


def probe_tracked_despite_ignored(vault_root: Path) -> TrackedIgnoredEvidence:
    """E13: report tracked files that Git currently also considers ignored."""
    try:
        paths = query_tracked_ignored(Path(vault_root))
    except TrackedIgnoredError as error:
        return TrackedIgnoredEvidence("UNKNOWN", (), str(error))
    return TrackedIgnoredEvidence("DETECTED" if paths else "CLEAR", paths)


def _git_metadata_present(root: Path) -> bool:
    try:
        os.lstat(root / ".git")
    except OSError:
        return False
    return True


def probe_machine_state(
    vault_root: Path,
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    walk: WalkReport | None = None,
) -> MachineStateReport:
    """Collect machine-state facts without modifying or following the tree."""
    root = Path(vault_root)
    observed = walk if walk is not None else walk_read_only(root, max_entries=max_entries)
    by_path = {entry.path: entry for entry in observed.entries}
    tracked = probe_tracked_despite_ignored(root)
    errors = list(observed.errors)
    if observed.truncated:
        errors.append("filesystem inventory reached its configured entry bound")
    if tracked.error:
        errors.append(tracked.error)
    return MachineStateReport(
        platform=sys.platform,
        git_metadata_present=_git_metadata_present(root),
        tracked_despite_ignored=tracked,
        projections_present=tuple(path for path in PROJECTION_PATHS if path in by_path),
        symlinks=tuple(entry.path for entry in observed.entries if entry.kind == "symlink"),
        special_files=tuple(entry.path for entry in observed.entries if entry.kind == "special"),
        case_collisions=observed.case_collisions,
        errors=tuple(sorted(set(errors))),
    )


__all__ = [
    "MachineStateReport",
    "PROJECTION_PATHS",
    "TrackedIgnoredEvidence",
    "probe_machine_state",
    "probe_tracked_despite_ignored",
]
