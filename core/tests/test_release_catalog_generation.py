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


def _shipped_role_skills() -> dict[str, Path]:
    available = REPO_ROOT / ".claude/skills/_available"
    return {
        skill.parent.name: skill
        for role_group in available.iterdir()
        if role_group.is_dir() and role_group.name != "capabilities"
        for skill in role_group.glob("*/SKILL.md")
    }


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
                        "files": [
                            {
                                "path": ".claude/skills/decision-log/SKILL.md",
                                "source_path": ".claude/skills/decision-log/SKILL.md",
                                "sha256": hashlib.sha256(item_bytes).hexdigest(),
                                "byte_size": len(item_bytes),
                            }
                        ],
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


def test_release_catalog_generation_rejects_stale_source_file_pins(
    tmp_path: Path,
) -> None:
    release_root, item_path, _manifest_bytes = _catalog_fixture(tmp_path)
    item_path.write_bytes(b"# changed after the registry was reviewed\n")

    result = _generate(release_root)

    assert result.returncode == 1
    assert "does not match its declared sha256 or byte_size" in result.stderr


def test_release_catalog_generation_rejects_duplicate_ids_across_fragments(
    tmp_path: Path,
) -> None:
    release_root, _item_path, _manifest_bytes = _catalog_fixture(tmp_path)
    source_dir = release_root / "core/lifecycle/catalog"
    first_source = source_dir / "test-items.json"
    second_source = source_dir / "more-items.json"
    second_source.write_bytes(first_source.read_bytes())

    result = _generate(release_root)

    assert result.returncode == 1
    assert "duplicate catalog item id 'decision-log'" in result.stderr
    assert str(first_source) in result.stderr
    assert str(second_source) in result.stderr


def test_catalog_generation_and_coverage_use_dormant_payload_for_active_target(
    tmp_path: Path,
) -> None:
    release_root, active_path, _manifest_bytes = _catalog_fixture(tmp_path)
    dormant_relative = ".claude/skills/_available/product/decision-log/SKILL.md"
    dormant_path = release_root / dormant_relative
    dormant_path.parent.mkdir(parents=True)
    active_path.replace(dormant_path)
    source_path = release_root / "core/lifecycle/catalog/test-items.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["items"][0]["files"][0]["source_path"] = dormant_relative
    source_path.write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
    manifest_path = release_root / "System/.installed-files.manifest"
    manifest_paths = manifest_path.read_text(encoding="utf-8").splitlines()
    manifest_paths.remove(".claude/skills/decision-log/SKILL.md")
    manifest_paths.append(dormant_relative)
    manifest_path.write_text("".join(f"{path}\n" for path in sorted(manifest_paths)))

    generated = _generate(release_root)

    assert generated.returncode == 0, generated.stdout + generated.stderr
    catalog = json.loads((release_root / "System/.release-catalog.json").read_text())
    assert catalog["items"][0]["files"][0]["path"] == (
        ".claude/skills/decision-log/SKILL.md"
    )
    assert not active_path.exists()
    covered = subprocess.run(
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
    assert covered.returncode == 0, covered.stdout + covered.stderr

    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["items"][0]["files"][0]["byte_size"] += 1
    source_path.write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
    rejected = subprocess.run(
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
    assert rejected.returncode == 1
    assert "size declaration is stale" in rejected.stderr


def test_distributed_release_catalog_schema_matches_b1_source() -> None:
    source = REPO_ROOT / "core/lifecycle/schemas/release-catalog-v1.schema.json"
    distributed = REPO_ROOT / "packages/dex-contracts/dist/release-catalog-v1.schema.json"

    assert distributed.read_bytes() == source.read_bytes()


def test_official_registry_covers_every_shipped_role_skill_with_exact_payload() -> None:
    registry_path = REPO_ROOT / "core/lifecycle/catalog/official-capabilities.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    shipped = _shipped_role_skills()
    items = {item["id"]: item for item in registry["items"]}

    assert set(items) == set(shipped)
    for item_id, dormant_path in shipped.items():
        item = items[item_id]
        active_relative = f".claude/skills/{item_id}/SKILL.md"
        active_path = REPO_ROOT / active_relative
        if item_id in {"decision-log", "delegate-check", "weekly-reflection"}:
            source_path = active_path
        else:
            source_path = dormant_path
            assert not active_path.exists()
        source_relative = source_path.relative_to(REPO_ROOT).as_posix()
        payload = source_path.read_bytes()
        assert item == {
            "id": item_id,
            "kind": "skill",
            "version": "1.0.0",
            "files": [
                {
                    "path": active_relative,
                    "source_path": source_relative,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "byte_size": len(payload),
                }
            ],
            "dependencies": [],
            "capabilities": [],
        }
