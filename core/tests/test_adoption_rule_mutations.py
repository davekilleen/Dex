"""Mutation-style proofs for fail-closed classifier rules."""

from __future__ import annotations

from pathlib import Path

from core import portable_contract
from core.lifecycle.inventory import build_inventory
from core.tests.lifecycle_test_helpers import write_file, write_manifest


def test_removing_folder_mapping_turns_remapped_content_unknown(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(vault, "Work/Projects/note.md", b"user content\n")
    write_manifest(vault, ["Work/Projects/note.md"])

    without_mapping = build_inventory(vault)
    write_file(vault, "System/folder-paths.yaml", b'projects: "Work/Projects"\n')
    with_mapping = build_inventory(vault)

    assert "Work" in without_mapping.unknown_paths
    mapped = next(entry for entry in with_mapping.entries if entry.actual_path == "Work/Projects/note.md")
    assert mapped.canonical_path == "04-Projects/note.md"
    assert mapped.ownership_class == "vault"


def test_malformed_folder_map_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(vault, "System/folder-paths.yaml", b"projects: ../outside\n")
    write_file(vault, "Work/Projects/note.md", b"user content\n")
    write_manifest(vault, ["System/folder-paths.yaml"])

    report = build_inventory(vault)

    assert report.folder_map.state == "UNKNOWN"
    assert report.complete is False
    assert "Work/Projects/note.md" in report.unknown_paths


def test_inventory_consumes_update_write_verdict(monkeypatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(vault, "core/feature.py", b"release bytes\n")
    write_manifest(vault, ["core/feature.py"])
    original = portable_contract.update_write_verdict

    def mutated(path: str, *, exists: bool):
        verdict = original(path, exists=exists)
        if path == "core/feature.py":
            return portable_contract.WriteVerdict(path, False, "unclassified-never-write", None, None)
        return verdict

    monkeypatch.setattr(portable_contract, "update_write_verdict", mutated)

    report = build_inventory(vault)
    feature = next(entry for entry in report.entries if entry.actual_path == "core/feature.py")
    assert feature.write_allowed is False
    assert feature.write_action == "unclassified-never-write"


def test_symlinked_directory_is_reported_and_never_descended(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    write_file(outside, "private.pem", b"outside secret\n")
    (vault / "04-Projects").symlink_to(outside, target_is_directory=True)
    write_manifest(vault, [])

    report = build_inventory(vault)

    link = next(entry for entry in report.entries if entry.actual_path == "04-Projects")
    assert link.kind == "symlink"
    assert not any(entry.actual_path.endswith("private.pem") for entry in report.entries)
