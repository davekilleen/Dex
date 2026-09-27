"""Small release-evidence fixtures shared by lifecycle B4 tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.lifecycle.catalog import (
    HASH_TABLE_PATH,
    build_release_hash_table_document,
    canonical_hash_table_bytes,
    with_catalog_identity,
)
from core.lifecycle.model import ReleaseCatalog
from core.transaction.journal import PREVIOUS_SCHEMA_VERSION, SCHEMA_VERSION

SOURCE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
CTRL_Z_OFFSET = 100
CTRL_Z_BLOB_SIZE = 4096


def ctrl_z_binary_blob() -> bytes:
    """4 KiB blob with ``0x1A`` at offset 100; the rest is non-text payload."""
    blob = bytearray(CTRL_Z_BLOB_SIZE)
    for index in range(CTRL_Z_BLOB_SIZE):
        blob[index] = (index % 250) + 1  # never 0x00 or 0x1A
    blob[CTRL_Z_OFFSET] = 0x1A
    return bytes(blob)


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def write_bridge_release(vault: Path, release_version: str = "1.64.0") -> None:
    """Write the canonical shipped bridge declaration for ``release_version``."""
    target = vault / "core/lifecycle/catalog/bridge-release.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        canonical_json_bytes(
            {
                "bridge_contract_version": 1,
                "release_version": release_version,
                "transaction_journal": {
                    "current_schema": SCHEMA_VERSION,
                    "previous_schema": PREVIOUS_SCHEMA_VERSION,
                    "minimum_resumable_schema": PREVIOUS_SCHEMA_VERSION,
                    "incompatible_action": "rollback-only",
                },
            }
        )
    )


def lifecycle_catalog_document(version: str, manifest_bytes: bytes) -> dict[str, object]:
    """Build a minimal schema-valid catalog binding ``manifest_bytes`` for ``version``."""
    return with_catalog_identity(
        {
            "catalog_version": 2,
            "release": {
                "version": version,
                "channel": "release",
                "immutable_distribution_tag_pattern": f"dist/release/v{version}-<release-commit-prefix>",
                "source_commit": SOURCE_COMMIT,
                "manifest": {
                    "path": "System/.installed-files.manifest",
                    "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                },
            },
            "items": [],
            "integrity": {"catalog_sha256": "0" * 64, "signatures": []},
        }
    )


def write_manifest(vault: Path, paths: list[str]) -> bytes:
    manifest_paths = sorted(set(paths) | {"System/.installed-files.manifest"})
    raw = "".join(f"{path}\n" for path in manifest_paths).encode()
    target = vault / "System/.installed-files.manifest"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return raw


def write_release_hash_table(
    vault: Path,
    rows: dict[str, bytes],
    *,
    release_version: str = "1.64.0",
) -> tuple[str, str]:
    """Write the sibling whole-tree hash table; return its (path, sha256) binding."""
    document = build_release_hash_table_document(
        release_version=release_version,
        source_commit=SOURCE_COMMIT,
        files={path: hashlib.sha256(content).hexdigest() for path, content in rows.items()},
    )
    table_bytes = canonical_hash_table_bytes(document)
    write_file(vault, HASH_TABLE_PATH, table_bytes)
    return HASH_TABLE_PATH, hashlib.sha256(table_bytes).hexdigest()


def catalog_for(
    manifest_bytes: bytes,
    expected: dict[str, bytes],
    *,
    hash_table: tuple[str, str] | None = None,
) -> ReleaseCatalog:
    files = [
        {
            "path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "ownership_class": "brain",
        }
        for path, content in sorted(expected.items())
    ]
    release: dict[str, object] = {
        "version": "1.64.0",
        "channel": "release",
        "immutable_distribution_tag_pattern": "dist/release/v1.64.0-<release-commit-prefix>",
        "source_commit": SOURCE_COMMIT,
        "manifest": {
            "path": "System/.installed-files.manifest",
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
    }
    if hash_table is not None:
        release["hash_table"] = {"path": hash_table[0], "sha256": hash_table[1]}
    return ReleaseCatalog.from_dict(
        {
            "catalog_version": 2,
            "release": release,
            "items": [
                {
                    "id": "fixture-item",
                    "kind": "skill",
                    "version": "1.0.0",
                    "files": files,
                    "dependencies": [],
                    "capabilities": [],
                    "rewind": {
                        "acknowledgement_required": True,
                        "token": "rewind:fixture-item@1.0.0",
                    },
                }
            ],
            "integrity": {"catalog_sha256": "0" * 64, "signatures": []},
        }
    )


def write_file(vault: Path, relative: str, content: bytes) -> None:
    target = vault / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
