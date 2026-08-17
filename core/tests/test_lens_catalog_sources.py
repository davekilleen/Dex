"""Closed source-authority contract for adoptable Dex Lens catalogue skills."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from core.lens_catalog_sources import (
    SkillSourceError,
    resolve_room_skill_sources,
    resolve_skill_source,
)


def _write(path: Path, content: bytes | str) -> bytes:
    payload = content.encode("utf-8") if isinstance(content, str) else content
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _pin(payload: bytes) -> tuple[str, int]:
    return hashlib.sha256(payload).hexdigest(), len(payload)


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _split_release_tree(root: Path, *, source_tracked: bool = True) -> str:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.com")
    _git(root, "config", "user.name", "Dex tests")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "release")

    source = root / ".claude/skills/_available/capabilities/career/skills/career-setup/SKILL.md"
    if not source_tracked:
        payload = source.read_bytes()
        _git(root, "rm", "-q", source.relative_to(root).as_posix())
        _git(root, "commit", "-qm", "release without room source")
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(payload)

    installed = _git(root, "rev-parse", "HEAD")
    brain = root / ".dex/brain.git"
    brain.parent.mkdir()
    shutil.move(str(root / ".git"), brain)
    _git(root, f"--git-dir={brain}", "update-ref", "refs/dex/installed", installed)
    (brain / "dex-brain-v2").write_text(
        json.dumps({"schemaVersion": 1, "role": "brain", "installed": installed}),
        encoding="utf-8",
    )

    _git(root, "init", "-q")
    (root / ".git/dex-vault-v2").write_text(
        json.dumps({"schemaVersion": 1, "role": "vault"}),
        encoding="utf-8",
    )
    topology = root / "System/.dex/topology.json"
    topology.parent.mkdir(parents=True)
    topology.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "topology": "brain-vault-split",
                "vaultGitDir": ".git",
                "brainGitDir": ".dex/brain.git",
                "installedRelease": installed,
                "environment": {"DEX_VAULT": str(root)},
            }
        ),
        encoding="utf-8",
    )
    return installed


def _fixture(root: Path) -> dict[str, object]:
    active = _write(
        root / ".claude/skills/pipeline-sync/SKILL.md",
        "---\nname: pipeline-sync\ndescription: Use when reconciling a sales pipeline.\n---\n",
    )
    lifecycle = _write(
        root / ".claude/skills/_available/sales/account-plan/SKILL.md",
        "---\nname: account-plan\ndescription: Use when planning a strategic account.\n---\n",
    )
    room = _write(
        root / ".claude/skills/_available/capabilities/career/skills/career-setup/SKILL.md",
        "---\nname: career-setup\ndescription: Use when setting up career evidence.\n---\n",
    )
    active_sha, active_size = _pin(active)
    lifecycle_sha, lifecycle_size = _pin(lifecycle)
    room_sha, room_size = _pin(room)

    lifecycle_catalog = root / "core/lifecycle/catalog/official-capabilities.json"
    _write(
        lifecycle_catalog,
        json.dumps(
            {
                "catalog_source_version": 1,
                "items": [
                    {
                        "id": "account-plan",
                        "kind": "skill",
                        "version": "1.0.0",
                        "files": [
                            {
                                "path": ".claude/skills/account-plan/SKILL.md",
                                "source_path": ".claude/skills/_available/sales/account-plan/SKILL.md",
                                "sha256": lifecycle_sha,
                                "byte_size": lifecycle_size,
                            }
                        ],
                        "dependencies": [],
                        "capabilities": [],
                    }
                ],
            }
        ),
    )

    contract_path = root / "packages/dex-contracts/dist/portable-vault.contract.json"
    _write(
        contract_path,
        json.dumps(
            {
                "capabilities": {
                    "career": {
                        "folders": ["05-Areas/Career"],
                        "skills": ["career-setup"],
                        "default_enabled": True,
                        "skill_sources": [
                            {
                                "room": "career",
                                "skill": "career-setup",
                                "source_path": ".claude/skills/_available/capabilities/career/skills/career-setup/SKILL.md",
                                "target_path": ".claude/skills/career-setup/SKILL.md",
                                "sha256": room_sha,
                                "byte_size": room_size,
                                "previous_payloads": [],
                            }
                        ],
                    }
                }
            }
        ),
    )
    return {
        "active": {
            "kind": "active-skill",
            "path": ".claude/skills/pipeline-sync/SKILL.md",
            "sha256": active_sha,
            "byte_size": active_size,
        },
        "lifecycle": {"kind": "lifecycle-skill", "item_id": "account-plan"},
        "room": {"kind": "room-skill", "room": "career", "skill": "career-setup"},
        "lifecycle_catalog": lifecycle_catalog,
        "contract": contract_path,
    }


def _resolve(root: Path, reference: dict[str, object], fixture: dict[str, object]):
    return resolve_skill_source(
        reference,
        root,
        lifecycle_catalog_path=fixture["lifecycle_catalog"],
        portable_contract_path=fixture["contract"],
    )


def test_closed_source_kinds_resolve_to_one_verified_pin(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    active = _resolve(tmp_path, fixture["active"], fixture)
    lifecycle = _resolve(tmp_path, fixture["lifecycle"], fixture)
    room = _resolve(tmp_path, fixture["room"], fixture)

    assert (active.kind, active.source_path, active.target_path) == (
        "active-skill",
        ".claude/skills/pipeline-sync/SKILL.md",
        ".claude/skills/pipeline-sync/SKILL.md",
    )
    assert (lifecycle.kind, lifecycle.source_path, lifecycle.target_path) == (
        "lifecycle-skill",
        ".claude/skills/_available/sales/account-plan/SKILL.md",
        ".claude/skills/account-plan/SKILL.md",
    )
    assert (room.kind, room.source_path, room.target_path) == (
        "room-skill",
        ".claude/skills/_available/capabilities/career/skills/career-setup/SKILL.md",
        ".claude/skills/career-setup/SKILL.md",
    )
    assert all(pin.path.read_bytes() for pin in (active, lifecycle, room))


def test_split_vault_uses_installed_brain_tree_for_source_identity(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _split_release_tree(tmp_path)

    room = _resolve(tmp_path, fixture["room"], fixture)

    assert room.path.read_bytes()


def test_split_vault_rejects_source_missing_from_installed_brain_tree(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _split_release_tree(tmp_path, source_tracked=False)

    with pytest.raises(SkillSourceError, match="not tracked.*installed.*tree"):
        _resolve(tmp_path, fixture["room"], fixture)


def test_split_vault_rejects_inconsistent_brain_identity(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _split_release_tree(tmp_path)
    marker = tmp_path / ".dex/brain.git/dex-brain-v2"
    document = json.loads(marker.read_text(encoding="utf-8"))
    document["installed"] = "0" * 40
    marker.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(SkillSourceError, match="brain.*installed.*does not match"):
        _resolve(tmp_path, fixture["room"], fixture)


@pytest.mark.parametrize(
    "reference",
    (
        {"kind": "skill", "path": ".claude/skills/pipeline-sync/SKILL.md"},
        {"kind": "active-skill", "path": ".claude/skills/pipeline-sync/SKILL.md"},
        {"kind": "lifecycle-skill", "item_id": "account-plan", "sha256": "0" * 64},
        {"kind": "room-skill", "room": "career", "skill": "career-setup", "path": "x"},
        {"kind": "unknown"},
    ),
)
def test_source_kinds_and_fields_are_closed(tmp_path: Path, reference: dict[str, object]) -> None:
    fixture = _fixture(tmp_path)

    with pytest.raises(SkillSourceError):
        _resolve(tmp_path, reference, fixture)


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda item: item.update(id="missing"), "not found"),
        (lambda item: item.update(kind="hook"), "kind"),
        (
            lambda item: item["files"].append(dict(item["files"][0])),
            "exactly one file",
        ),
        (
            lambda item: item["files"][0].update(path=".claude/skills/wrong/SKILL.md"),
            "target",
        ),
    ),
)
def test_lifecycle_reference_fails_closed_on_wrong_official_identity(tmp_path: Path, mutate, message: str) -> None:
    fixture = _fixture(tmp_path)
    catalog_path = fixture["lifecycle_catalog"]
    document = json.loads(catalog_path.read_text(encoding="utf-8"))
    mutate(document["items"][0])
    catalog_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(SkillSourceError, match=message):
        _resolve(tmp_path, fixture["lifecycle"], fixture)


def test_lifecycle_reference_rejects_duplicate_item_identity(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    catalog_path = fixture["lifecycle_catalog"]
    document = json.loads(catalog_path.read_text(encoding="utf-8"))
    document["items"].append(dict(document["items"][0]))
    catalog_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(SkillSourceError, match="duplicate.*account-plan"):
        _resolve(tmp_path, fixture["lifecycle"], fixture)


def test_lifecycle_reference_rejects_a_source_swapped_from_another_skill(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    catalog_path = fixture["lifecycle_catalog"]
    document = json.loads(catalog_path.read_text(encoding="utf-8"))
    swapped = _write(
        tmp_path / ".claude/skills/_available/sales/call-prep/SKILL.md",
        "---\nname: call-prep\ndescription: Different skill bytes.\n---\n",
    )
    sha256, byte_size = _pin(swapped)
    document["items"][0]["files"][0].update(
        source_path=".claude/skills/_available/sales/call-prep/SKILL.md",
        sha256=sha256,
        byte_size=byte_size,
    )
    catalog_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(SkillSourceError, match="source.*account-plan|identity"):
        _resolve(tmp_path, fixture["lifecycle"], fixture)


@pytest.mark.parametrize("mutation", ("missing", "extra", "duplicate", "wrong-room"))
def test_room_authority_must_exactly_cover_declared_room_skills(tmp_path: Path, mutation: str) -> None:
    fixture = _fixture(tmp_path)
    contract_path = fixture["contract"]
    document = json.loads(contract_path.read_text(encoding="utf-8"))
    career = document["capabilities"]["career"]
    if mutation == "missing":
        career["skill_sources"] = []
    elif mutation == "extra":
        career["skill_sources"].append(
            {
                **career["skill_sources"][0],
                "skill": "career-extra",
                "source_path": ".claude/skills/_available/capabilities/career/skills/career-extra/SKILL.md",
                "target_path": ".claude/skills/career-extra/SKILL.md",
            }
        )
    elif mutation == "duplicate":
        career["skill_sources"].append(dict(career["skill_sources"][0]))
    else:
        career["skill_sources"][0]["room"] = "quarter_goals"
    contract_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(SkillSourceError, match="room.*authority|skill_sources"):
        resolve_room_skill_sources("career", tmp_path, portable_contract_path=contract_path)


@pytest.mark.parametrize("mutation", ("bytes", "extra-file", "source-symlink"))
def test_room_source_payload_identity_is_verified(tmp_path: Path, mutation: str) -> None:
    fixture = _fixture(tmp_path)
    source = tmp_path / ".claude/skills/_available/capabilities/career/skills/career-setup/SKILL.md"
    if mutation == "bytes":
        source.write_text("changed\n", encoding="utf-8")
    elif mutation == "extra-file":
        _write(source.parent / "UNPINNED.md", "extra\n")
    else:
        original = source.parent / "ORIGINAL.md"
        source.rename(original)
        source.symlink_to(original.name)

    with pytest.raises(SkillSourceError):
        _resolve(tmp_path, fixture["room"], fixture)


def test_room_source_identifies_one_exact_previous_release_payload(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    contract_path = fixture["contract"]
    document = json.loads(contract_path.read_text(encoding="utf-8"))
    previous = b"---\nname: career-setup\ndescription: Prior published release.\n---\n"
    previous_sha256, previous_byte_size = _pin(previous)
    document["capabilities"]["career"]["skill_sources"][0]["previous_payloads"] = [
        {
            "release": "v1.95.2",
            "sha256": previous_sha256,
            "byte_size": previous_byte_size,
        }
    ]
    contract_path.write_text(json.dumps(document), encoding="utf-8")

    resolved = _resolve(tmp_path, fixture["room"], fixture)

    assert resolved.identify_payload(resolved.path.read_bytes()) == "current"
    assert resolved.identify_payload(previous) == "v1.95.2"
    assert resolved.identify_payload(b"user-owned custom bytes") is None


@pytest.mark.parametrize(
    "mutation",
    ("missing-field", "extra-field", "bad-release", "boolean-size", "current-payload"),
)
def test_previous_room_payload_authority_is_closed(tmp_path: Path, mutation: str) -> None:
    fixture = _fixture(tmp_path)
    contract_path = fixture["contract"]
    document = json.loads(contract_path.read_text(encoding="utf-8"))
    current = document["capabilities"]["career"]["skill_sources"][0]
    previous = {
        "release": "v1.95.2",
        "sha256": "1" * 64,
        "byte_size": 42,
    }
    if mutation == "missing-field":
        previous.pop("byte_size")
    elif mutation == "extra-field":
        previous["path"] = "not-authoritative"
    elif mutation == "bad-release":
        previous["release"] = "latest"
    elif mutation == "boolean-size":
        previous["byte_size"] = True
    else:
        previous["sha256"] = current["sha256"]
        previous["byte_size"] = current["byte_size"]
    current["previous_payloads"] = [previous]
    contract_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(SkillSourceError, match="previous|fields|release|byte_size|payload"):
        _resolve(tmp_path, fixture["room"], fixture)


def test_source_pin_rejects_actual_byte_drift(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    lifecycle_source = tmp_path / ".claude/skills/_available/sales/account-plan/SKILL.md"
    lifecycle_source.write_text("changed\n", encoding="utf-8")

    with pytest.raises(SkillSourceError, match="sha256|byte_size|bytes"):
        _resolve(tmp_path, fixture["lifecycle"], fixture)
