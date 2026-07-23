"""Focused coverage for the E1c manifest additions: frozen-contract path
enforcement and canonical manifest reading."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.utils.manifest import (
    REQUIRED_LIFECYCLE_RELEASE_PATHS,
    ManifestError,
    read_manifest,
    require_lifecycle_release_paths,
)


def test_require_lifecycle_release_paths_accepts_a_complete_manifest() -> None:
    # A superset of the required frozen-contract paths must pass unchanged.
    paths = (*REQUIRED_LIFECYCLE_RELEASE_PATHS, "README.md", "System/pillars.yaml")
    require_lifecycle_release_paths(tuple(sorted(paths)))


def test_require_lifecycle_release_paths_fails_closed_when_a_contract_is_missing() -> None:
    assert REQUIRED_LIFECYCLE_RELEASE_PATHS, "there must be frozen contract paths to guard"
    dropped = REQUIRED_LIFECYCLE_RELEASE_PATHS[0]
    incomplete = tuple(p for p in REQUIRED_LIFECYCLE_RELEASE_PATHS if p != dropped)
    with pytest.raises(ManifestError) as excinfo:
        require_lifecycle_release_paths(incomplete)
    assert dropped in str(excinfo.value)


def test_read_manifest_round_trips_canonical_text(tmp_path: Path) -> None:
    manifest = tmp_path / "installed.manifest"
    entries = ("README.md", "System/pillars.yaml", "core/lifecycle/service.py")
    manifest.write_bytes(("".join(f"{e}\n" for e in sorted(entries))).encode("utf-8"))
    assert read_manifest(manifest) == tuple(sorted(entries))


def test_read_manifest_rejects_unsorted_or_duplicated_paths(tmp_path: Path) -> None:
    manifest = tmp_path / "installed.manifest"
    manifest.write_bytes(b"b.md\na.md\n")
    with pytest.raises(ManifestError):
        read_manifest(manifest)


def test_read_manifest_rejects_non_canonical_bytes(tmp_path: Path) -> None:
    manifest = tmp_path / "installed.manifest"
    # Carriage return and a missing trailing newline are both non-canonical.
    manifest.write_bytes(b"a.md\r\nb.md")
    with pytest.raises(ManifestError):
        read_manifest(manifest)
