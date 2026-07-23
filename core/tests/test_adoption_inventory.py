"""B4 inventory contract, including E6 and folder-map canonicalization."""

from __future__ import annotations

from pathlib import Path

from core.lifecycle.inventory import build_inventory, canonical_inventory_bytes
from core.tests.lifecycle_test_helpers import catalog_for, write_file, write_manifest


def _by_path(report):
    return {entry.actual_path: entry for entry in report.entries}


def test_inventory_layers_contract_ownership_and_release_state_without_writes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    shipped = b"release bytes\n"
    write_file(vault, "core/feature.py", shipped)
    write_file(vault, "04-Projects/Client/notes.md", b"private notes\n")
    write_file(vault, "mystery/place.txt", b"unknown\n")
    write_file(vault, ".env", b"API_KEY=never-read\n")
    manifest = write_manifest(
        vault,
        [
            "core/feature.py",
            "core/missing.py",
            "04-Projects/Client/notes.md",
            "mystery/place.txt",
            ".env",
        ],
    )
    catalog = catalog_for(manifest, {"core/feature.py": shipped, "core/missing.py": b"expected\n"})
    before = sorted((path.relative_to(vault).as_posix(), path.lstat().st_mtime_ns) for path in vault.rglob("*"))

    first = build_inventory(vault, catalog=catalog)
    second = build_inventory(vault, catalog=catalog)

    entries = _by_path(first)
    assert entries["core/feature.py"].ownership_class == "brain"
    assert entries["core/feature.py"].release_state == "stock-unmodified"
    assert entries["04-Projects/Client/notes.md"].ownership_class == "vault"
    assert entries["04-Projects/Client/notes.md"].release_state == "canonical-customization"
    assert entries["mystery/place.txt"].ownership_class is None
    assert {"mystery", "mystery/place.txt"}.issubset(first.unknown_paths)
    assert entries["core/missing.py"].kind == "missing"
    assert entries["core/missing.py"].release_state == "stock-missing"
    denied = entries[".env"].to_dict()
    assert denied["redacted"] is True
    assert "size" not in denied and "sha256" not in denied
    assert canonical_inventory_bytes(first) == canonical_inventory_bytes(second)
    after = sorted((path.relative_to(vault).as_posix(), path.lstat().st_mtime_ns) for path in vault.rglob("*"))
    assert after == before


def test_remapped_folder_is_canonicalized_before_contract_resolution(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(
        vault,
        "System/folder-paths.yaml",
        b'projects: "Work/Projects"\n',
    )
    write_file(vault, "Work/Projects/README.md", b"starter edited by user\n")
    write_file(vault, "Work/Projects/Client/notes.md", b"user content\n")
    write_manifest(vault, ["System/folder-paths.yaml"])

    report = build_inventory(vault)
    entries = _by_path(report)

    assert report.folder_map.state == "LOADED"
    assert entries["Work/Projects/README.md"].canonical_path == "04-Projects/README.md"
    assert entries["Work/Projects/README.md"].ownership_class == "seed"
    assert entries["Work/Projects/Client/notes.md"].canonical_path == "04-Projects/Client/notes.md"
    assert entries["Work/Projects/Client/notes.md"].ownership_class == "vault"
    assert "Work/Projects/Client/notes.md" not in report.unknown_paths
