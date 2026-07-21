"""B5 adoption planning semantics and E6 holdback isolation."""

from __future__ import annotations

import copy
import hashlib
import random
from pathlib import Path

import pytest

from core.lifecycle.inventory import build_inventory
from core.lifecycle.model import AdoptionState, ReleaseCatalog
from core.lifecycle.plan import (
    AdoptionPlan,
    AdoptionPlanError,
    build_adoption_plan,
    canonical_adoption_plan_bytes,
)
from core.tests.lifecycle_test_helpers import SOURCE_COMMIT, write_file, write_manifest


def _catalog(manifest: bytes, expected: dict[str, bytes]) -> ReleaseCatalog:
    items = []
    for item_id, content in sorted(expected.items()):
        path = f".claude/skills/{item_id}/SKILL.md"
        items.append(
            {
                "id": item_id,
                "kind": "skill",
                "version": "1.0.0",
                "files": [
                    {
                        "path": path,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "ownership_class": "brain",
                    }
                ],
                "dependencies": [],
                "capabilities": [],
                "rewind": {
                    "acknowledgement_required": True,
                    "token": f"rewind:{item_id}@1.0.0",
                },
            }
        )
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
                    "sha256": hashlib.sha256(manifest).hexdigest(),
                },
            },
            "items": items,
            "integrity": {"catalog_sha256": "a" * 64, "signatures": []},
        }
    )


def _scenario(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    expected = {
        "adopted": b"adopted release\n",
        "conflict": b"conflict release\n",
        "held": b"held release\n",
        "missing": b"missing release\n",
        "ready": b"ready release\n",
        "unknown": b"unknown release\n",
    }
    paths = [f".claude/skills/{item_id}/SKILL.md" for item_id in expected]
    manifest = write_manifest(vault, paths)
    catalog = _catalog(manifest, expected)
    for item_id, content in expected.items():
        if item_id == "missing":
            continue
        actual = b"user changed this\n" if item_id == "conflict" else content
        write_file(vault, f".claude/skills/{item_id}/SKILL.md", actual)
    unknown = vault / ".claude/skills/unknown/SKILL.md"
    unknown.unlink()
    unknown.symlink_to(vault / ".claude/skills/ready/SKILL.md")
    inventory = build_inventory(vault, catalog=catalog)
    return catalog, inventory


def _items_by_id(plan: AdoptionPlan):
    return {item.item_id: item for item in plan.items}


def test_plan_classifies_each_catalog_item_from_its_own_evidence(tmp_path: Path) -> None:
    catalog, inventory = _scenario(tmp_path)

    plan = build_adoption_plan(
        catalog,
        inventory,
        customizations=inventory.customizations,
        adoption_states={"adopted": AdoptionState.ADOPTED},
        held_back={"held"},
    )

    by_id = _items_by_id(plan)
    assert by_id["ready"].action == "adopt"
    assert by_id["ready"].reasons[0].code == "release-files-ready"
    assert by_id["adopted"].action == "already-adopted"
    assert by_id["held"].action == "skip-held-back"
    assert by_id["conflict"].action == "conflict"
    assert by_id["conflict"].reasons[0].paths == (
        ".claude/skills/conflict/SKILL.md",
    )
    assert by_id["missing"].action == "conflict"
    assert by_id["unknown"].action == "unknown"
    assert plan.counts == {
        "adopt": 1,
        "already-adopted": 1,
        "skip-held-back": 1,
        "conflict": 2,
        "unknown": 1,
    }


def test_no_recorded_adoption_state_means_nothing_is_already_adopted(tmp_path: Path) -> None:
    catalog, inventory = _scenario(tmp_path)

    plan = build_adoption_plan(catalog, inventory)

    assert _items_by_id(plan)["adopted"].action == "adopt"
    assert plan.counts["already-adopted"] == 0


def test_e6_random_holdbacks_never_change_non_held_item_plans(tmp_path: Path) -> None:
    catalog, inventory = _scenario(tmp_path)
    states = {"adopted": AdoptionState.ADOPTED}
    baseline = _items_by_id(
        build_adoption_plan(catalog, inventory, adoption_states=states)
    )
    item_ids = sorted(baseline)
    random_source = random.Random(20260721)

    for _ in range(100):
        held_back = {
            item_id for item_id in item_ids if random_source.choice((False, True))
        }
        candidate = _items_by_id(
            build_adoption_plan(
                catalog,
                inventory,
                adoption_states=states,
                held_back=held_back,
            )
        )
        for item_id in set(item_ids) - held_back:
            assert candidate[item_id] == baseline[item_id]


def test_conflict_and_unknown_items_do_not_block_ready_items(tmp_path: Path) -> None:
    catalog, inventory = _scenario(tmp_path)

    plan = _items_by_id(build_adoption_plan(catalog, inventory))

    assert plan["conflict"].action == "conflict"
    assert plan["unknown"].action == "unknown"
    assert plan["ready"].action == "adopt"


def test_plan_round_trip_and_canonical_bytes_are_deterministic(tmp_path: Path) -> None:
    catalog, inventory = _scenario(tmp_path)
    plan = build_adoption_plan(catalog, inventory, held_back={"held"})

    reparsed = AdoptionPlan.from_dict(plan.to_dict())

    assert reparsed == plan
    assert canonical_adoption_plan_bytes(reparsed) == canonical_adoption_plan_bytes(plan)
    assert [item.item_id for item in plan.items] == sorted(item.id for item in catalog.items)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw.update({"surprise": True}),
        lambda raw: raw.pop("catalog_sha256"),
        lambda raw: raw.update({"plan_version": True}),
        lambda raw: raw["items"][0].update({"action": "maybe"}),
        lambda raw: raw["items"][0].update({"action": "already-adopted"}),
        lambda raw: raw["items"][0]["reasons"][0].update({"code": "guess"}),
        lambda raw: raw["items"][0]["reasons"][0].update({"paths": "not-an-array"}),
        lambda raw: raw["items"][0]["reasons"][0].update({"paths": []}),
        lambda raw: raw["items"][0]["reasons"][0].update({"paths": ["../escape"]}),
        lambda raw: raw.update({"counts": {"adopt": 999}}),
        lambda raw: raw["items"].append(copy.deepcopy(raw["items"][0])),
    ],
)
def test_plan_parser_fails_closed_on_ambiguous_documents(
    tmp_path: Path, mutation
) -> None:
    catalog, inventory = _scenario(tmp_path)
    raw = build_adoption_plan(catalog, inventory).to_dict()
    mutation(raw)

    with pytest.raises(AdoptionPlanError, match="UNKNOWN"):
        AdoptionPlan.from_dict(raw)


def test_planner_rejects_unknown_ids_and_untyped_receipt_states(tmp_path: Path) -> None:
    catalog, inventory = _scenario(tmp_path)

    with pytest.raises(AdoptionPlanError, match="unknown held-back item"):
        build_adoption_plan(catalog, inventory, held_back={"not-in-catalog"})
    with pytest.raises(AdoptionPlanError, match="unknown adoption-state item"):
        build_adoption_plan(
            catalog,
            inventory,
            adoption_states={"not-in-catalog": AdoptionState.ADOPTED},
        )
    with pytest.raises(AdoptionPlanError, match="must be an AdoptionState"):
        build_adoption_plan(catalog, inventory, adoption_states={"ready": "adopted"})
