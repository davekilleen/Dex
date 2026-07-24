"""E3c official capability adoption through the frozen lifecycle service."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from core import portable_contract
from core.lifecycle import service
from core.lifecycle.catalog import (
    canonical_catalog_bytes,
    load_catalog_payload_sources,
    with_catalog_identity,
)
from core.lifecycle.ledger import record_holdback
from core.lifecycle.preview import AdoptionPreviewError
from core.tests.lifecycle_test_helpers import SOURCE_COMMIT, write_file, write_manifest
from core.tests.test_lifecycle_bridge import _write_bridge_release

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "core/lifecycle/catalog/official-capabilities.json"
LEVEL_UP_PATH = REPO_ROOT / ".claude/skills/dex-level-up/SKILL.md"
SOURCE_REGISTRY_PATH = "core/lifecycle/catalog/official-capabilities.json"
CATALOG_PATH = "System/.release-catalog.json"
RELEASE_VERSION = "1.67.0"


def _registry_items() -> dict[str, dict[str, object]]:
    source = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert source["catalog_source_version"] == 1
    return {item["id"]: item for item in source["items"]}


def _service_fixture(
    tmp_path: Path,
    item_ids: tuple[str, ...],
    *,
    source_registry_path: str = SOURCE_REGISTRY_PATH,
) -> tuple[Path, Path]:
    registry = _registry_items()
    vault = tmp_path / "vault"
    release = tmp_path / "release"
    vault.mkdir()
    release.mkdir()

    selected_source_items = [registry[item_id] for item_id in sorted(item_ids)]
    source_registry = {
        "catalog_source_version": 1,
        "items": selected_source_items,
    }
    source_registry_bytes = (json.dumps(source_registry, indent=2) + "\n").encode()
    write_file(vault, source_registry_path, source_registry_bytes)
    write_file(release, source_registry_path, source_registry_bytes)

    catalog_items = []
    manifest_paths = [CATALOG_PATH, source_registry_path]
    for item_id in sorted(item_ids):
        source_item = registry[item_id]
        files = []
        for declared_file in source_item["files"]:
            target_path = declared_file["path"]
            source_path = declared_file["source_path"]
            payload = (REPO_ROOT / source_path).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == declared_file["sha256"]
            assert len(payload) == declared_file["byte_size"]
            write_file(vault, source_path, payload)
            write_file(release, source_path, payload)
            manifest_paths.append(source_path)
            files.append(
                {
                    "path": target_path,
                    "sha256": declared_file["sha256"],
                    "ownership_class": portable_contract.resolve(target_path).ownership,
                }
            )
        catalog_items.append(
            {
                "id": item_id,
                "kind": source_item["kind"],
                "version": source_item["version"],
                "files": files,
                "dependencies": source_item["dependencies"],
                "capabilities": source_item["capabilities"],
                "rewind": {
                    "acknowledgement_required": True,
                    "token": f"rewind:{item_id}@{source_item['version']}",
                },
            }
        )

    manifest = write_manifest(vault, manifest_paths)
    document = with_catalog_identity(
        {
            "catalog_version": 1,
            "release": {
                "version": RELEASE_VERSION,
                "channel": "release",
                "immutable_distribution_tag": "dist/release/v1.67.0-0123456",
                "source_commit": SOURCE_COMMIT,
                "manifest": {
                    "path": "System/.installed-files.manifest",
                    "sha256": hashlib.sha256(manifest).hexdigest(),
                },
            },
            "items": catalog_items,
            "integrity": {"catalog_sha256": "0" * 64, "signatures": []},
        }
    )
    write_file(vault, CATALOG_PATH, canonical_catalog_bytes(document))
    _write_bridge_release(vault, RELEASE_VERSION)
    _write_bridge_release(release, RELEASE_VERSION)
    return vault, release


def _plan_actions(vault: Path) -> dict[str, str]:
    response = service.build_inventory_and_plan(vault)
    return {item["item_id"]: item["action"] for item in response["plan"]["items"]}


def test_lifecycle_catalog_never_declares_composed_claude_md() -> None:
    # The engine builds its complete write set from catalog declarations. CLAUDE.md
    # contains composed user instructions, so it must remain outside that write set.
    declared_paths = load_catalog_payload_sources(REPO_ROOT)

    assert "CLAUDE.md" not in declared_paths, (
        "CLAUDE.md contains the user's personal instructions; declaring it in a lifecycle "
        "catalog item would let the live update route plan an overwrite or deletion"
    )


def test_real_service_adopts_replans_and_rewinds_an_official_capability(
    tmp_path: Path,
) -> None:
    vault, release = _service_fixture(tmp_path, ("roadmap",))
    item = _registry_items()["roadmap"]
    expected_files = {
        declared["path"]: (REPO_ROOT / declared["source_path"]).read_bytes()
        for declared in item["files"]
    }

    assert _plan_actions(vault) == {"roadmap": "adopt"}
    previewed = service.build_and_preview_adoption(vault, release, ("roadmap",))
    executed = service.execute_approved_adoption(
        vault,
        release,
        previewed["preview"],
        previewed["approval_token"],
    )

    assert executed["receipt"]["items_adopted"] == ["roadmap"]
    for path, expected in expected_files.items():
        assert (vault / path).read_bytes() == expected
    assert _plan_actions(vault) == {"roadmap": "already-adopted"}

    rewound = service.rewind_adoption_by_receipt(
        vault,
        executed["receipt"],
        executed["rewind_acknowledgement_token"],
    )
    assert [entry["path"] for entry in rewound["rewind_receipt"]["files_restored"]] == sorted(
        expected_files
    )
    assert all(not (vault / path).exists() for path in expected_files)
    assert _plan_actions(vault) == {"roadmap": "adopt"}


def test_service_holdback_is_isolated_to_one_official_item(tmp_path: Path) -> None:
    vault, release = _service_fixture(tmp_path, ("roadmap", "tech-debt"))
    record_holdback(vault, "tech-debt")

    assert _plan_actions(vault) == {
        "roadmap": "adopt",
        "tech-debt": "skip-held-back",
    }
    previewed = service.build_and_preview_adoption(vault, release, ("roadmap",))
    executed = service.execute_approved_adoption(
        vault,
        release,
        previewed["preview"],
        previewed["approval_token"],
    )

    assert executed["receipt"]["items_adopted"] == ["roadmap"]
    assert (vault / ".claude/skills/roadmap/SKILL.md").is_file()
    assert not (vault / ".claude/skills/tech-debt/SKILL.md").exists()
    assert _plan_actions(vault)["tech-debt"] == "skip-held-back"


def test_dormant_payload_bytes_must_be_proved_before_plan_can_offer_adoption(
    tmp_path: Path,
) -> None:
    vault, _release = _service_fixture(tmp_path, ("roadmap",))
    source_path = _registry_items()["roadmap"]["files"][0]["source_path"]
    (vault / source_path).write_bytes(b"tampered dormant payload\n")

    assert _plan_actions(vault) == {"roadmap": "unknown"}


def test_runtime_loads_dormant_mapping_from_any_publisher_catalog_fragment(
    tmp_path: Path,
) -> None:
    vault, release = _service_fixture(
        tmp_path,
        ("roadmap",),
        source_registry_path="core/lifecycle/catalog/product-capabilities.json",
    )

    previewed = service.build_and_preview_adoption(vault, release, ("roadmap",))

    assert previewed["preview"]["items"][0]["item_id"] == "roadmap"


def test_user_custom_skill_is_not_adoptable_through_official_catalog(
    tmp_path: Path,
) -> None:
    vault, release = _service_fixture(tmp_path, ("roadmap",))
    custom_path = vault / ".claude/skills-custom/private-coach/SKILL.md"
    custom_path.parent.mkdir(parents=True)
    custom_bytes = b"---\nname: private-coach\n---\n\n# Mine\n"
    custom_path.write_bytes(custom_bytes)

    with pytest.raises(AdoptionPreviewError, match="private-coach"):
        service.build_and_preview_adoption(vault, release, ("private-coach",))

    assert custom_path.read_bytes() == custom_bytes
    assert "private-coach" not in _registry_items()


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_provisioner_defers_optional_catalog_items_to_level_up(tmp_path: Path) -> None:
    vault, _release = _service_fixture(tmp_path, ("roadmap",))
    registry_path = vault / SOURCE_REGISTRY_PATH
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["items"][0]["id"] = "stale-registry-id"
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    script = """
const provision = require('./core/provision.cjs');
const result = provision.routeAdoptionThroughLifecycleService(process.argv[1]);
process.stdout.write(JSON.stringify(result));
"""

    completed = subprocess.run(
        ["node", "-e", script, str(vault)],
        cwd=REPO_ROOT,
        env={**dict(os.environ), "DEX_LIFECYCLE_PYTHON": sys.executable},
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["previewed"] == []
    assert result["receipt"] is None
    assert not (vault / ".claude/skills/roadmap/SKILL.md").exists()


def test_dex_level_up_routes_adoption_only_through_the_lifecycle_service() -> None:
    instructions = LEVEL_UP_PATH.read_text(encoding="utf-8")

    for service_operation in (
        "build_inventory_and_plan",
        "build_and_preview_adoption",
        "execute_approved_adoption",
        "read_lifecycle_state",
    ):
        assert service_operation in instructions
    for forbidden in ("cp -r", "copy skill folder", "direct cop", "shutil.copy", "fs.cp"):
        assert forbidden not in instructions.casefold()
    assert "five-group" in instructions.casefold()
    assert "explicit" in instructions.casefold()
    assert "receipt" in instructions.casefold()
    assert "fresh session" in instructions.casefold()
