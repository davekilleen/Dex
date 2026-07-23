"""Small release-evidence fixtures shared by lifecycle B4 tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

from core.lifecycle.model import ReleaseCatalog

SOURCE_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def write_manifest(vault: Path, paths: list[str]) -> bytes:
    manifest_paths = sorted(set(paths) | {"System/.installed-files.manifest"})
    raw = "".join(f"{path}\n" for path in manifest_paths).encode()
    target = vault / "System/.installed-files.manifest"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return raw


def catalog_for(manifest_bytes: bytes, expected: dict[str, bytes]) -> ReleaseCatalog:
    files = [
        {
            "path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "ownership_class": "brain",
        }
        for path, content in sorted(expected.items())
    ]
    return ReleaseCatalog.from_dict(
        {
            "catalog_version": 1,
            "release": {
                "version": "1.64.0",
                "channel": "release",
                "immutable_distribution_tag": "dist/release/v1.64.0-0123456",
                "source_commit": SOURCE_COMMIT,
                "manifest": {
                    "path": "System/.installed-files.manifest",
                    "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                },
            },
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
