"""DEX-228: Dex-produced leftovers must not keep a healthy re-anchor UNKNOWN.

After a verified catalog (or re-anchor), room-delivered skill copies, the
generated path list, and the generated architecture inventory are Dex's own
files. They are absent from the installed manifest — the release ships the
dormant room sources and regenerates the other two — so they used to stay
``release-identity-unproved``. A genuine leftover brain file, or a room skill
the user actually edited, must still show.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import MappingProxyType

from core import portable_contract
from core.customization_migration.service import assess
from core.lifecycle.customizations import (
    ReleaseBaseline,
    classify_release_state,
    load_release_baseline,
    room_delivered_target_pins,
)
from core.lifecycle.inventory import build_inventory
from core.tests.test_customization_assessment import _install_verified_catalog
from core.tests.lifecycle_test_helpers import write_file

REPO_ROOT = Path(__file__).resolve().parents[2]
UNPROVED = "release-identity-unproved"
PATHS_JSON = "core/paths.json"
INVENTORY_DOC = "docs/architecture/INVENTORY.md"
LEFTOVER = "core/leftover-not-ours.py"


def _room_targets() -> tuple[tuple[str, bytes], ...]:
    current, _previous = room_delivered_target_pins()
    planted: list[tuple[str, bytes]] = []
    for room in portable_contract.CAPABILITIES.values():
        for source in room.get("skill_sources", ()):
            target = str(source["target_path"])
            payload = (REPO_ROOT / str(source["source_path"])).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == current[target]
            planted.append((target, payload))
    return tuple(planted)


def _plant_dex_produced(vault: Path) -> None:
    write_file(vault, PATHS_JSON, b'{"VAULT_ROOT":"."}\n')
    write_file(vault, INVENTORY_DOC, b"# generated inventory\n")
    for target, payload in _room_targets():
        write_file(vault, target, payload)


def _by_path(report):
    return {entry.actual_path: entry for entry in report.entries}


def _unproved(assessment) -> tuple[str, ...]:
    return tuple(
        exclusion.path
        for exclusion in assessment.exclusions
        if exclusion.reason == UNPROVED
    )


def test_paths_json_and_inventory_doc_are_generated_not_brain() -> None:
    paths = portable_contract.resolve(PATHS_JSON)
    inventory = portable_contract.resolve(INVENTORY_DOC)

    assert paths.ownership == "generated"
    assert paths.rule_id == "generated-core-paths"
    assert inventory.ownership == "generated"
    assert inventory.rule_id == "generated-architecture-inventory"


def test_verified_baseline_accepts_current_and_previous_room_pins(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)

    baseline = load_release_baseline(vault)
    current, previous = room_delivered_target_pins()

    assert baseline.identity_state == "VERIFIED"
    assert current
    for target, sha256 in current.items():
        assert baseline.expected_sha256(target) == sha256
        assert sha256 in baseline.acceptable_sha256s(target)
        extras = previous.get(target, frozenset())
        assert extras <= baseline.acceptable_sha256s(target)


def test_dex_produced_leftovers_do_not_block_completeness(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    _plant_dex_produced(vault)

    report = build_inventory(vault)
    entries = _by_path(report)
    assessment = assess(vault)

    assert entries[PATHS_JSON].release_state == "cache"
    assert entries[INVENTORY_DOC].release_state == "cache"
    for target, _payload in _room_targets():
        assert entries[target].ownership_class == "brain"
        assert entries[target].release_state == "stock-unmodified"
    assert PATHS_JSON not in report.unproven_paths
    assert INVENTORY_DOC not in report.unproven_paths
    assert assessment.completeness == "OK"
    assert assessment.verdict == "OK"
    assert _unproved(assessment) == ()


def test_edited_room_skill_still_shows_as_modified(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    _plant_dex_produced(vault)
    edited = ".claude/skills/career-setup/SKILL.md"
    write_file(vault, edited, b"---\nname: career-setup\n---\nI changed this.\n")

    entries = _by_path(build_inventory(vault))
    assessment = assess(vault)

    assert entries[edited].release_state == "stock-modified"
    assert edited not in _unproved(assessment)
    assert any(record.source_paths == (edited,) for record in assessment.records)
    assert assessment.completeness == "OK"


def test_genuine_brain_leftover_stays_unproved(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    _plant_dex_produced(vault)
    write_file(vault, LEFTOVER, b"pre-merge leftover bytes\n")

    entries = _by_path(build_inventory(vault))
    assessment = assess(vault)

    assert entries[LEFTOVER].ownership_class == "brain"
    assert entries[LEFTOVER].release_state == "unknown"
    assert LEFTOVER in _unproved(assessment)
    assert assessment.completeness == "UNKNOWN"


def test_previous_room_payload_classifies_as_stock_unmodified() -> None:
    current, previous = room_delivered_target_pins()
    target = ".claude/skills/career-setup/SKILL.md"
    prior = next(iter(previous[target]))
    baseline = ReleaseBaseline(
        "VERIFIED",
        "1.73.0",
        frozenset(),
        MappingProxyType({target: current[target]}),
        (),
        alternate_hashes=MappingProxyType({target: frozenset({prior})}),
    )

    assert (
        classify_release_state(
            canonical_path=target,
            kind="file",
            ownership_class="brain",
            denied=False,
            actual_sha256=prior,
            baseline=baseline,
        )
        == "stock-unmodified"
    )
    assert (
        classify_release_state(
            canonical_path=target,
            kind="file",
            ownership_class="brain",
            denied=False,
            actual_sha256="f" * 64,
            baseline=baseline,
        )
        == "stock-modified"
    )
