"""Release-catalog generation and coverage gates at their CLI seams."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from core.lifecycle.catalog import canonical_catalog_bytes, loads_catalog

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts/generate-release-catalog.py"
COVERAGE_GATE = REPO_ROOT / "scripts/check-catalog-coverage.py"
SOURCE_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _catalog_fixture(tmp_path: Path) -> tuple[Path, Path, bytes]:
    release_root = tmp_path / "release"
    item_path = release_root / ".claude/skills/decision-log/SKILL.md"
    item_path.parent.mkdir(parents=True)
    item_bytes = b"# Decision log\n"
    item_path.write_bytes(item_bytes)

    source_path = release_root / "core/lifecycle/catalog/test-items.json"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        json.dumps(
            {
                "catalog_source_version": 1,
                "items": [
                    {
                        "id": "decision-log",
                        "kind": "skill",
                        "version": "1.0.0",
                        "files": [".claude/skills/decision-log/SKILL.md"],
                        "dependencies": [],
                        "capabilities": [],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (release_root / "package.json").write_text('{"version":"9.8.7"}\n', encoding="utf-8")

    manifest_path = release_root / "System/.installed-files.manifest"
    manifest_path.parent.mkdir(parents=True)
    manifest_bytes = (
        b".claude/skills/decision-log/SKILL.md\n"
        b"System/.installed-files.manifest\n"
        b"System/.release-catalog.json\n"
        b"core/lifecycle/catalog/test-items.json\n"
        b"package.json\n"
    )
    manifest_path.write_bytes(manifest_bytes)
    return release_root, item_path, manifest_bytes


def _generate(release_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(release_root),
            "--contract-root",
            str(REPO_ROOT),
            "--source-commit",
            SOURCE_COMMIT,
            "--channel",
            "release",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_release_catalog_generation_is_deterministic_and_uses_b1_contract(
    tmp_path: Path,
) -> None:
    release_root, item_path, manifest_bytes = _catalog_fixture(tmp_path)

    first = _generate(release_root)
    assert first.returncode == 0, first.stdout + first.stderr
    output_path = release_root / "System/.release-catalog.json"
    first_bytes = output_path.read_bytes()

    second = _generate(release_root)
    assert second.returncode == 0, second.stdout + second.stderr
    assert output_path.read_bytes() == first_bytes

    catalog = loads_catalog(first_bytes.decode("utf-8"), manifest_bytes=manifest_bytes)
    assert first_bytes == canonical_catalog_bytes(catalog)
    assert catalog.release.version == "9.8.7"
    assert catalog.release.source_commit == SOURCE_COMMIT
    assert catalog.release.immutable_distribution_tag == "dist/release/v9.8.7-0123456"
    assert catalog.release.manifest.sha256 == hashlib.sha256(manifest_bytes).hexdigest()
    assert catalog.items[0].files[0].sha256 == hashlib.sha256(item_path.read_bytes()).hexdigest()
    assert catalog.items[0].files[0].ownership_class == "brain"
    assert catalog.items[0].rewind.token == "rewind:decision-log@1.0.0"


def test_catalog_coverage_gate_fails_closed_when_an_item_file_is_removed(
    tmp_path: Path,
) -> None:
    release_root, item_path, _manifest_bytes = _catalog_fixture(tmp_path)
    generated = _generate(release_root)
    assert generated.returncode == 0, generated.stdout + generated.stderr

    green = subprocess.run(
        [
            sys.executable,
            str(COVERAGE_GATE),
            "--release-root",
            str(release_root),
            "--contract-root",
            str(REPO_ROOT),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert green.returncode == 0, green.stdout + green.stderr

    item_path.unlink()
    red = subprocess.run(
        [
            sys.executable,
            str(COVERAGE_GATE),
            "--release-root",
            str(release_root),
            "--contract-root",
            str(REPO_ROOT),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert red.returncode == 1
    assert "missing catalog file" in red.stderr


def test_distributed_release_catalog_schema_matches_b1_source() -> None:
    source = REPO_ROOT / "core/lifecycle/schemas/release-catalog-v1.schema.json"
    distributed = REPO_ROOT / "packages/dex-contracts/dist/release-catalog-v1.schema.json"

    assert distributed.read_bytes() == source.read_bytes()
