"""D3 effective behavior for the first official catalog items."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from core import portable_contract
from core.lifecycle import engine as adoption_engine
from core.lifecycle.catalog import canonical_catalog_bytes, loads_catalog, with_catalog_identity
from core.lifecycle.engine import (
    AdoptionRewindError,
    execute_adoption,
    rewind_acknowledgement_token,
    rewind_adoption,
)
from core.lifecycle.inventory import build_inventory
from core.lifecycle.ledger import project_state
from core.lifecycle.model import AdoptionState, ReleaseCatalog
from core.lifecycle.plan import AdoptionPlan, build_adoption_plan
from core.lifecycle.preview import build_adoption_preview
from core.tests.lifecycle_test_helpers import SOURCE_COMMIT
from core.transaction.engine import PlanEntry, Transaction

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "core/lifecycle/catalog/official-capabilities.json"
CATALOG_PATH = "System/.release-catalog.json"
TRIO = ("decision-log", "delegate-check", "weekly-reflection")


def _items_by_id(plan: AdoptionPlan):
    return {item.item_id: item for item in plan.items}


def _source_registry() -> tuple[dict[str, object], dict[str, bytes]]:
    source = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert source["catalog_source_version"] == 1
    assert tuple(item["id"] for item in source["items"]) == TRIO

    payloads: dict[str, bytes] = {}
    for item in source["items"]:
        for declared_file in item["files"]:
            path = declared_file["path"]
            content = (REPO_ROOT / path).read_bytes()
            assert declared_file["sha256"] == hashlib.sha256(content).hexdigest()
            assert declared_file["byte_size"] == len(content)
            payloads[path] = content
    return source, payloads


def _catalog_from_source(source: dict[str, object], manifest: bytes) -> ReleaseCatalog:
    items = []
    for source_item in source["items"]:
        files = []
        for declared_file in source_item["files"]:
            path = declared_file["path"]
            resolution = portable_contract.resolve(path)
            files.append(
                {
                    "path": path,
                    "sha256": declared_file["sha256"],
                    "ownership_class": resolution.ownership,
                }
            )
        item_id = source_item["id"]
        version = source_item["version"]
        items.append(
            {
                "id": item_id,
                "kind": source_item["kind"],
                "version": version,
                "files": files,
                "dependencies": source_item["dependencies"],
                "capabilities": source_item["capabilities"],
                "rewind": {
                    "acknowledgement_required": True,
                    "token": f"rewind:{item_id}@{version}",
                },
            }
        )
    document = with_catalog_identity(
        {
            "catalog_version": 1,
            "release": {
                "version": "1.67.0",
                "channel": "release",
                "immutable_distribution_tag": "dist/release/v1.67.0-0123456",
                "source_commit": SOURCE_COMMIT,
                "manifest": {
                    "path": "System/.installed-files.manifest",
                    "sha256": hashlib.sha256(manifest).hexdigest(),
                },
            },
            "items": items,
            "integrity": {"catalog_sha256": "0" * 64, "signatures": []},
        }
    )
    return loads_catalog(json.dumps(document), manifest_bytes=manifest)


def _fresh_vault(tmp_path: Path):
    source, payloads = _source_registry()
    vault = tmp_path / "vault"
    vault.mkdir()
    manifest_paths = sorted(
        set(payloads) | {"System/.installed-files.manifest", CATALOG_PATH}
    )
    manifest = "".join(f"{path}\n" for path in manifest_paths).encode()
    catalog = _catalog_from_source(source, manifest)

    prior_path = ".claude/skills/weekly-reflection/SKILL.md"
    bootstrap = [
        PlanEntry("System/.installed-files.manifest", manifest),
        PlanEntry(CATALOG_PATH, canonical_catalog_bytes(catalog)),
        PlanEntry(prior_path, payloads[prior_path], mode=0o600),
    ]
    Transaction.begin(vault, bootstrap).run()
    return vault, catalog, payloads, prior_path


def _ledger_states(vault: Path) -> dict[str, AdoptionState]:
    adopted = project_state(vault)["adopted"]
    assert isinstance(adopted, dict)
    return {item_id: AdoptionState.ADOPTED for item_id in adopted}


def test_trio_adoption_is_effective_replans_and_rewinds_exactly(tmp_path: Path) -> None:
    vault, catalog, payloads, prior_path = _fresh_vault(tmp_path)
    inventory = build_inventory(vault, catalog=catalog)
    plan = build_adoption_plan(catalog, inventory)
    assert {item.item_id: item.action.value for item in plan.items} == {
        item_id: "adopt" for item_id in TRIO
    }

    preview = build_adoption_preview(catalog, inventory, plan, TRIO, payloads.__getitem__)
    receipt = execute_adoption(vault, preview, preview.sha256, payloads.__getitem__)

    assert receipt.items_adopted == TRIO
    for path, expected in payloads.items():
        assert (vault / path).read_bytes() == expected
    assert stat.S_IMODE((vault / prior_path).stat().st_mode) == 0o644

    adopted_plan = build_adoption_plan(
        catalog,
        build_inventory(vault, catalog=catalog),
        adoption_states=_ledger_states(vault),
    )
    assert {item.item_id: item.action.value for item in adopted_plan.items} == {
        item_id: "already-adopted" for item_id in TRIO
    }

    rewind = rewind_adoption(vault, receipt, rewind_acknowledgement_token(receipt))
    restored = {entry.path: entry.existed_before_adoption for entry in rewind.files_restored}
    assert restored == {
        ".claude/skills/decision-log/SKILL.md": False,
        ".claude/skills/delegate-check/SKILL.md": False,
        prior_path: True,
    }
    assert not (vault / ".claude/skills/decision-log/SKILL.md").exists()
    assert not (vault / ".claude/skills/delegate-check/SKILL.md").exists()
    assert (vault / prior_path).read_bytes() == payloads[prior_path]
    assert stat.S_IMODE((vault / prior_path).stat().st_mode) == 0o600
    assert project_state(vault)["adopted"] == {}


def test_trio_rewind_refuses_an_edited_created_skill_and_preserves_its_bytes(
    tmp_path: Path,
) -> None:
    vault, catalog, payloads, _prior_path = _fresh_vault(tmp_path)
    inventory = build_inventory(vault, catalog=catalog)
    plan = build_adoption_plan(catalog, inventory)
    preview = build_adoption_preview(catalog, inventory, plan, TRIO, payloads.__getitem__)
    receipt = execute_adoption(vault, preview, preview.sha256, payloads.__getitem__)
    created_path = ".claude/skills/decision-log/SKILL.md"
    receipt_file = next(
        entry for entry in receipt.files_written if entry.path == created_path
    )

    current_modes, drifted = adoption_engine._current_adopted_modes(vault, receipt)
    assert drifted == ()
    rewind_plan, _restored = adoption_engine._snapshot_rewind_plan(
        vault, receipt, current_modes
    )
    deletion = next(entry for entry in rewind_plan if entry.relative == created_path)
    assert deletion.content is None
    assert deletion.expected_current_sha256 == receipt_file.sha256

    edited = b"# user edit that rewind must preserve\n"
    target = vault / created_path
    target.write_bytes(edited)

    with pytest.raises(AdoptionRewindError) as raised:
        rewind_adoption(vault, receipt, rewind_acknowledgement_token(receipt))

    assert "files changed after adoption and were left untouched" in str(raised.value)
    assert created_path in str(raised.value)
    assert target.read_bytes() == edited


def test_holding_back_one_trio_item_never_changes_the_other_two(tmp_path: Path) -> None:
    for held_item in TRIO:
        scenario = tmp_path / held_item
        scenario.mkdir()
        vault, catalog, payloads, _prior_path = _fresh_vault(scenario)
        inventory = build_inventory(vault, catalog=catalog)
        baseline = _items_by_id(build_adoption_plan(catalog, inventory))
        held_path = f".claude/skills/{held_item}/SKILL.md"
        held_target = vault / held_path
        held_bytes = held_target.read_bytes() if held_target.exists() else None
        held_mode = stat.S_IMODE(held_target.stat().st_mode) if held_target.exists() else None

        held = _items_by_id(
            build_adoption_plan(catalog, inventory, held_back={held_item})
        )
        assert held[held_item].action.value == "skip-held-back"
        other_items = tuple(sorted(set(TRIO) - {held_item}))
        for other_item in other_items:
            assert held[other_item] == baseline[other_item]

        held_plan = build_adoption_plan(catalog, inventory, held_back={held_item})
        preview = build_adoption_preview(
            catalog,
            inventory,
            held_plan,
            other_items,
            payloads.__getitem__,
        )
        receipt = execute_adoption(vault, preview, preview.sha256, payloads.__getitem__)

        assert receipt.items_adopted == other_items
        for other_item in other_items:
            other_path = f".claude/skills/{other_item}/SKILL.md"
            assert (vault / other_path).read_bytes() == payloads[other_path]
        if held_bytes is None:
            assert not held_target.exists()
        else:
            assert held_target.read_bytes() == held_bytes
            assert stat.S_IMODE(held_target.stat().st_mode) == held_mode
