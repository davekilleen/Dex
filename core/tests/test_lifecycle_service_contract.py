"""Frozen lifecycle-service API contract coverage."""

from __future__ import annotations

import hashlib
import inspect
import json
import plistlib
import re
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from core.lifecycle import service
from core.lifecycle.bridge import ACTIVATION_RELATIVE
from core.lifecycle.engine import (
    AdoptionReceiptPersistenceError,
    rewind_acknowledgement_token,
)
from core.tests.test_adoption_transaction import _setup
from core.tests.test_lifecycle_bridge import _write_bridge_release
from core.update import apply_update
from core.utils import automation_ownership

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "lifecycle" / "contracts" / "api.schema.json"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _json_type(value: object, expected: str) -> bool:
    return {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "boolean": type(value) is bool,
        "null": value is None,
    }[expected]


def _validate(schema: dict[str, object], node: object, value: object, path: str = "$") -> None:
    assert isinstance(node, Mapping), f"{path}: schema node is not an object"
    if "$ref" in node:
        reference = node["$ref"]
        assert isinstance(reference, str) and reference.startswith("#/$defs/")
        _validate(schema, schema["$defs"][reference.removeprefix("#/$defs/")], value, path)
        return
    for child in node.get("allOf", []):
        _validate(schema, child, value, path)
    if "anyOf" in node:
        failures = []
        for child in node["anyOf"]:
            try:
                _validate(schema, child, value, path)
                break
            except AssertionError as error:
                failures.append(str(error))
        else:
            raise AssertionError(f"{path}: no anyOf branch matched: {failures}")
    expected_type = node.get("type")
    if expected_type is not None:
        assert isinstance(expected_type, str) and _json_type(value, expected_type), (
            f"{path}: expected {expected_type}, found {type(value).__name__}"
        )
    if "const" in node:
        assert value == node["const"], f"{path}: expected constant {node['const']!r}"
    if isinstance(value, str):
        assert len(value) >= node.get("minLength", 0), f"{path}: string is too short"
        if "pattern" in node:
            assert re.search(node["pattern"], value), f"{path}: string does not match pattern"
    if type(value) is int:
        assert value >= node.get("minimum", value), f"{path}: integer is below minimum"
        assert value <= node.get("maximum", value), f"{path}: integer is above maximum"
    if isinstance(value, list):
        assert len(value) >= node.get("minItems", 0), f"{path}: array has too few items"
        if node.get("uniqueItems") is True:
            encoded = [json.dumps(item, sort_keys=True) for item in value]
            assert len(encoded) == len(set(encoded)), f"{path}: array items are not unique"
        if "items" in node:
            for index, item in enumerate(value):
                _validate(schema, node["items"], item, f"{path}[{index}]")
    if isinstance(value, Mapping):
        required = node.get("required", [])
        missing = set(required) - set(value)
        assert not missing, f"{path}: missing fields {sorted(missing)}"
        properties = node.get("properties", {})
        if node.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            assert not unknown, f"{path}: unknown fields {sorted(unknown)}"
        for field, child in properties.items():
            if field in value:
                _validate(schema, child, value[field], f"{path}.{field}")


def _assert_conforms(schema: dict[str, object], operation: str, request: dict[str, object], response: object) -> None:
    operation_schema = schema["x-operations"][operation]
    _validate(schema, operation_schema["request"], request)
    _validate(schema, operation_schema["response"], response)


def test_frozen_service_inputs_and_outputs_conform_to_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, _document, _catalog, _inventory, _plan, _loader = _setup(tmp_path, item_ids=("alpha",))
    _write_bridge_release(vault)
    release_root = tmp_path / "release"
    shutil.copytree(vault, release_root)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    inventory_request = {"vault_root": str(vault)}
    inventory_response = service.build_inventory_and_plan(vault)
    assert (vault / ACTIVATION_RELATIVE).is_file()
    _assert_conforms(
        schema,
        "build_inventory_and_plan",
        inventory_request,
        inventory_response,
    )
    mcp_vault = tmp_path / "mcp-vault"
    (mcp_vault / "System").mkdir(parents=True)
    shutil.copy2(
        REPO_ROOT / "System/.mcp.json.example",
        mcp_vault / "System/.mcp.json.example",
    )
    (mcp_vault / ".mcp.json").write_text('{"mcpServers": {}}\n', encoding="utf-8")
    mcp_preview_request = {"vault_root": str(mcp_vault)}
    mcp_preview_response = service.build_and_preview_mcp_registration(mcp_vault)
    _assert_conforms(
        schema,
        "build_and_preview_mcp_registration",
        mcp_preview_request,
        mcp_preview_response,
    )
    mcp_execute_request = {
        "vault_root": str(mcp_vault),
        "preview": mcp_preview_response["preview"],
        "approved_token": mcp_preview_response["approval_token"],
    }
    mcp_execute_response = service.execute_approved_mcp_registration(
        mcp_vault,
        mcp_preview_response["preview"],
        mcp_preview_response["approval_token"],
    )
    _assert_conforms(
        schema,
        "execute_approved_mcp_registration",
        mcp_execute_request,
        mcp_execute_response,
    )

    onboarding_vault = tmp_path / "onboarding-vault"
    (onboarding_vault / "System").mkdir(parents=True)
    (onboarding_vault / "System" / "user-profile.yaml").write_text(
        "name: Example User\n",
        encoding="utf-8",
    )
    onboarding_request = {
        "vault_root": str(onboarding_vault),
        "working_context": {"role_focus": "Lead product work", "key_people": []},
        "calendar_source": {"provider": "apple", "work_calendar": "Work"},
    }
    onboarding_response = service.build_and_preview_onboarding_context(
        onboarding_vault,
        onboarding_request["working_context"],
        onboarding_request["calendar_source"],
    )
    _assert_conforms(
        schema,
        "build_and_preview_onboarding_context",
        onboarding_request,
        onboarding_response,
    )
    onboarding_execute_request = {
        "vault_root": str(onboarding_vault),
        "preview": onboarding_response["preview"],
        "approved_token": onboarding_response["approval_token"],
    }
    onboarding_execute_response = service.execute_approved_onboarding_context(
        onboarding_vault,
        onboarding_response["preview"],
        onboarding_response["approval_token"],
    )
    _assert_conforms(
        schema,
        "execute_approved_onboarding_context",
        onboarding_execute_request,
        onboarding_execute_response,
    )

    presence_vault = tmp_path / "presence-vault"
    (presence_vault / "System").mkdir(parents=True)
    (presence_vault / "System" / "user-profile.yaml").write_text(
        "name: Example User\n",
        encoding="utf-8",
    )
    presence_fields = {"photo": "System/maya.png", "title": "Designer", "company": ""}
    presence_request = {
        "vault_root": str(presence_vault),
        "fields": presence_fields,
    }
    presence_response = service.build_and_preview_room_presence(
        presence_vault,
        presence_fields,
    )
    _assert_conforms(
        schema,
        "build_and_preview_room_presence",
        presence_request,
        presence_response,
    )
    presence_execute_request = {
        "vault_root": str(presence_vault),
        "preview": presence_response["preview"],
        "approved_token": presence_response["approval_token"],
    }
    presence_execute_response = service.execute_approved_room_presence(
        presence_vault,
        presence_response["preview"],
        presence_response["approval_token"],
    )
    _assert_conforms(
        schema,
        "execute_approved_room_presence",
        presence_execute_request,
        presence_execute_response,
    )
    share_request = {
        "vault_root": str(presence_vault),
        "room_id": "design-sync",
    }
    share_response = service.build_and_preview_room_presence_share(
        presence_vault,
        "design-sync",
    )
    _assert_conforms(
        schema,
        "build_and_preview_room_presence_share",
        share_request,
        share_response,
    )
    share_execute_request = {
        "vault_root": str(presence_vault),
        "preview": share_response["preview"],
        "approved_token": share_response["approval_token"],
        "consent": "yes",
    }
    share_execute_response = service.execute_approved_room_presence_share(
        presence_vault,
        share_response["preview"],
        share_response["approval_token"],
        "yes",
    )
    _assert_conforms(
        schema,
        "execute_approved_room_presence_share",
        share_execute_request,
        share_execute_response,
    )

    automation_vault = tmp_path / "automation-vault"
    (automation_vault / "System").mkdir(parents=True)
    home = tmp_path / "automation-home"
    label = "com.dex.smoke-nightly"
    plist_relative = f"Library/LaunchAgents/{label}.plist"
    plist = home / plist_relative
    plist.parent.mkdir(parents=True)
    with plist.open("wb") as handle:
        plistlib.dump({"Label": label, "ProgramArguments": ["/bin/bash"]}, handle)
    monkeypatch.setattr(automation_ownership, "_home_root", lambda: home)
    claim = {
        "automation_id": label,
        "owner_id": "dex-solo",
        "plist_relative_path": plist_relative,
        "plist_sha256": hashlib.sha256(plist.read_bytes()).hexdigest(),
        "launchd_state": "unloaded",
    }
    claim_preview = service.build_and_preview_automation_claim(automation_vault, claim)
    _assert_conforms(
        schema,
        "build_and_preview_automation_claim",
        {"vault_root": str(automation_vault), "claim": claim},
        claim_preview,
    )
    claim_execute = service.execute_approved_automation_claim(
        automation_vault,
        claim_preview["preview"],
        claim_preview["approval_token"],
    )
    _assert_conforms(
        schema,
        "execute_approved_automation_claim",
        {
            "vault_root": str(automation_vault),
            "preview": claim_preview["preview"],
            "approved_token": claim_preview["approval_token"],
        },
        claim_execute,
    )
    release = {
        "automation_id": label,
        "owner_id": "dex-solo",
        "scheduler_state": "stopped",
    }
    release_preview = service.build_and_preview_automation_release(
        automation_vault,
        release,
    )
    _assert_conforms(
        schema,
        "build_and_preview_automation_release",
        {"vault_root": str(automation_vault), "release": release},
        release_preview,
    )
    release_execute = service.execute_approved_automation_release(
        automation_vault,
        release_preview["preview"],
        release_preview["approval_token"],
    )
    _assert_conforms(
        schema,
        "execute_approved_automation_release",
        {
            "vault_root": str(automation_vault),
            "preview": release_preview["preview"],
            "approved_token": release_preview["approval_token"],
        },
        release_execute,
    )

    preview_request = {
        "vault_root": str(vault),
        "release_root": str(release_root),
        "requested_item_ids": ["alpha"],
    }
    preview_response = service.build_and_preview_adoption(vault, release_root, ("alpha",))
    _assert_conforms(
        schema,
        "build_and_preview_adoption",
        preview_request,
        preview_response,
    )

    execute_request = {
        "vault_root": str(vault),
        "release_root": str(release_root),
        "preview": preview_response["preview"],
        "approved_token": preview_response["approval_token"],
    }
    execute_response = service.execute_approved_adoption(
        vault,
        release_root,
        preview_response["preview"],
        preview_response["approval_token"],
    )
    _assert_conforms(
        schema,
        "execute_approved_adoption",
        execute_request,
        execute_response,
    )

    receipt = execute_response["receipt"]
    rewind_request = {
        "vault_root": str(vault),
        "receipt": receipt,
        "acknowledgement_token": rewind_acknowledgement_token(receipt),
    }
    rewind_response = service.rewind_adoption_by_receipt(
        vault,
        receipt,
        rewind_request["acknowledgement_token"],
    )
    _assert_conforms(
        schema,
        "rewind_adoption_by_receipt",
        rewind_request,
        rewind_response,
    )

    conflict_path = ".claude/skills/alpha/SKILL.md"
    (vault / conflict_path).write_bytes(b"# alpha\n\nMy local instructions.\n")
    resolutions = [{"item_id": "alpha", "strategy": "keep-both"}]
    conflict_preview_request = {
        "vault_root": str(vault),
        "release_root": str(release_root),
        "resolutions": resolutions,
    }
    conflict_preview_response = service.build_and_preview_conflict_resolution(
        vault,
        release_root,
        resolutions,
    )
    _assert_conforms(
        schema,
        "build_and_preview_conflict_resolution",
        conflict_preview_request,
        conflict_preview_response,
    )

    conflict_execute_request = {
        "vault_root": str(vault),
        "release_root": str(release_root),
        "preview": conflict_preview_response["preview"],
        "approved_token": conflict_preview_response["approval_token"],
    }
    conflict_execute_response = service.execute_approved_conflict_resolution(
        vault,
        release_root,
        conflict_preview_response["preview"],
        conflict_preview_response["approval_token"],
    )
    _assert_conforms(
        schema,
        "execute_approved_conflict_resolution",
        conflict_execute_request,
        conflict_execute_response,
    )

    conflict_receipt = conflict_execute_response["receipt"]
    conflict_rewind_request = {
        "vault_root": str(vault),
        "receipt": conflict_receipt,
        "acknowledgement_token": rewind_acknowledgement_token(conflict_receipt),
    }
    conflict_rewind_response = service.rewind_adoption_by_receipt(
        vault,
        conflict_receipt,
        conflict_rewind_request["acknowledgement_token"],
    )
    _assert_conforms(
        schema,
        "rewind_adoption_by_receipt",
        conflict_rewind_request,
        conflict_rewind_response,
    )

    state_request = {"vault_root": str(vault)}
    state_response = service.read_lifecycle_state(vault)
    _assert_conforms(
        schema,
        "read_lifecycle_state",
        state_request,
        state_response,
    )


def test_service_recovery_refuses_damage_before_activation_mutates(tmp_path: Path) -> None:
    vault, _document, _catalog, _inventory, _plan, _loader = _setup(tmp_path, item_ids=("alpha",))
    _write_bridge_release(vault)
    journal = vault / "System/.dex/tx/damaged/journal.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        AdoptionReceiptPersistenceError,
        match="incomplete or quarantined",
    ):
        service.build_inventory_and_plan(vault)

    assert not (vault / ACTIVATION_RELATIVE).exists()


def test_api_version_is_present_and_frozen_in_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert service.api_version == "1.5.0"
    assert schema["properties"]["api_version"] == {"const": service.api_version}


def test_additive_public_surface_preserves_every_existing_operation() -> None:
    assert service.__all__ == [
        "api_version",
        "build_inventory_and_plan",
        "build_and_preview_adoption",
        "execute_approved_adoption",
        "rewind_adoption_by_receipt",
        "read_lifecycle_state",
        "deliver_latest_release",
        "build_and_preview_delivered_release",
        "execute_approved_delivered_release",
        "build_and_preview_mcp_registration",
        "execute_approved_mcp_registration",
        "build_and_preview_onboarding_context",
        "execute_approved_onboarding_context",
        "build_and_preview_room_presence",
        "execute_approved_room_presence",
        "build_and_preview_room_presence_share",
        "execute_approved_room_presence_share",
        "build_and_preview_automation_claim",
        "execute_approved_automation_claim",
        "build_and_preview_automation_release",
        "execute_approved_automation_release",
        "deliver_and_apply_latest_release",
        "build_and_preview_conflict_resolution",
        "execute_approved_conflict_resolution",
        "build_archive_removal_preview",
        "execute_approved_archive_removal",
        "build_and_preview_topology_migration",
        "execute_approved_topology_migration",
        "execute_approved_rebuild_capsule",
        "execute_approved_rebuild_staging",
        "execute_approved_rebuild_verification",
        "execute_approved_rebuild_activation",
        "rewind_rebuild_activation_by_receipt",
        "abandon_rebuild_capsule",
        "recover_rebuild_transactions",
        "TopologyMigrationError",
    ]
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(schema["x-operations"])[-7:] == [
        "execute_approved_rebuild_capsule",
        "execute_approved_rebuild_staging",
        "execute_approved_rebuild_verification",
        "execute_approved_rebuild_activation",
        "rewind_rebuild_activation_by_receipt",
        "abandon_rebuild_capsule",
        "recover_rebuild_transactions",
    ]


def test_room_presence_operations_have_frozen_signatures() -> None:
    assert str(inspect.signature(service.build_and_preview_room_presence)) == (
        "(vault_root: 'str | Path', fields: 'Mapping[str, object]') -> 'dict[str, object]'"
    )
    assert str(inspect.signature(service.execute_approved_room_presence)) == (
        "(vault_root: 'str | Path', preview: 'Mapping[str, object]', approved_token: 'str') -> 'dict[str, object]'"
    )
    assert str(inspect.signature(service.build_and_preview_room_presence_share)) == (
        "(vault_root: 'str | Path', room_id: 'str') -> 'dict[str, object]'"
    )
    assert str(inspect.signature(service.execute_approved_room_presence_share)) == (
        "(vault_root: 'str | Path', preview: 'Mapping[str, object]', approved_token: 'str', "
        "consent: 'str') -> 'dict[str, object]'"
    )


def test_onboarding_context_operations_have_frozen_signatures() -> None:
    assert str(inspect.signature(service.build_and_preview_onboarding_context)) == (
        "(vault_root: 'str | Path', working_context: 'Mapping[str, object]', "
        "calendar_source: 'Mapping[str, object]') -> 'dict[str, object]'"
    )
    assert str(inspect.signature(service.execute_approved_onboarding_context)) == (
        "(vault_root: 'str | Path', preview: 'Mapping[str, object]', approved_token: 'str') -> 'dict[str, object]'"
    )
    assert "version bump" in service.__doc__.lower()
    assert "bridge" in service.__doc__.lower()


def test_automation_ownership_operations_have_frozen_signatures() -> None:
    assert str(inspect.signature(service.build_and_preview_automation_claim)) == (
        "(vault_root: 'str | Path', claim: 'Mapping[str, object]') -> 'dict[str, object]'"
    )
    assert str(inspect.signature(service.execute_approved_automation_claim)) == (
        "(vault_root: 'str | Path', preview: 'Mapping[str, object]', approved_token: 'str') -> 'dict[str, object]'"
    )
    assert str(inspect.signature(service.build_and_preview_automation_release)) == (
        "(vault_root: 'str | Path', release: 'Mapping[str, object]') -> 'dict[str, object]'"
    )
    assert str(inspect.signature(service.execute_approved_automation_release)) == (
        "(vault_root: 'str | Path', preview: 'Mapping[str, object]', approved_token: 'str') -> 'dict[str, object]'"
    )


def test_release_delivery_is_non_mutating_and_exposed_only_through_the_lifecycle_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    expected = {
        "status": "delivered",
        "release": {
            "tag": "dist/release/v1.65.0-0123456789abcdef0123456789abcdef01234567",
            "tag_object": "0123456789abcdef0123456789abcdef01234567",
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "tree": "0123456789abcdef0123456789abcdef01234567",
            "version": "1.65.0",
            "channel": "stable",
        },
    }
    called_with: list[Path] = []

    def fake_delivery(vault_root: Path) -> dict[str, object]:
        called_with.append(vault_root)
        return expected

    monkeypatch.setattr(apply_update, "deliver_latest_release", fake_delivery)

    response = service.deliver_latest_release(vault)

    assert called_with == [vault]
    assert response == {"api_version": service.api_version, **expected}
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    _assert_conforms(
        schema,
        "deliver_latest_release",
        {"vault_root": str(vault)},
        response,
    )


def test_release_delivery_reports_missing_channel_reader_dependency(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    profile = vault / "System" / "user-profile.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_text("updates:\n  channel: stable\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "yaml", None)

    response = service.deliver_latest_release(vault)

    assert response == {
        "api_version": service.api_version,
        "status": "not-delivered",
        "evidence": {
            "status": "UNKNOWN",
            "reason": "missing-dependency",
        },
    }


def test_legacy_release_delivery_operation_is_a_non_mutating_bridge(tmp_path: Path) -> None:
    response = service.deliver_and_apply_latest_release(tmp_path / "vault")

    assert response == {
        "api_version": service.api_version,
        "status": "not-delivered",
        "evidence": {
            "status": "deprecated",
            "reason": "use-deliver-preview-execute",
        },
    }
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    _assert_conforms(
        schema,
        "deliver_and_apply_latest_release",
        {"vault_root": str(tmp_path / "vault")},
        response,
    )


def test_delivered_release_preview_and_execute_contracts_bind_one_identity() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    identity = {
        "tag": "dist/release/v1.65.0-0123456789abcdef0123456789abcdef01234567",
        "tag_object": "0123456789abcdef0123456789abcdef01234567",
        "commit": "0123456789abcdef0123456789abcdef01234567",
        "tree": "0123456789abcdef0123456789abcdef01234567",
        "version": "1.65.0",
        "channel": "stable",
    }
    preview = {
        "release": identity,
        "previous_commit": "89abcdef0123456789abcdef0123456789abcdef",
        "writes": [
            {
                "path": "README.md",
                "action": "write",
                "sha256": "a" * 64,
                "byte_size": 10,
                "mode": 420,
                "current": {"exists": True},
            }
        ],
    }
    token = "b" * 64
    preview_response = {
        "api_version": service.api_version,
        "preview": preview,
        "approval_token": token,
    }
    _assert_conforms(
        schema,
        "build_and_preview_delivered_release",
        {"vault_root": "/tmp/vault", "release": identity},
        preview_response,
    )
    _assert_conforms(
        schema,
        "execute_approved_delivered_release",
        {"vault_root": "/tmp/vault", "preview": preview, "approved_token": token},
        {"api_version": service.api_version, "receipt": {}, "release": identity},
    )


def test_archive_removal_is_previewed_approved_and_receipted(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    archive = vault / ".dex/pre-split-archive.git"
    archive.mkdir(parents=True)
    (archive / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (archive / "objects").mkdir()
    (archive / "objects" / "sample").write_bytes(b"archive bytes")

    preview = service.build_archive_removal_preview(vault)

    assert preview["api_version"] == "1.5.0"
    assert preview["preview"]["archive_relative"] == ".dex/pre-split-archive.git"
    assert preview["preview"]["size_bytes"] == len(b"ref: refs/heads/main\narchive bytes")
    assert preview["preview"]["retention"] == "one full release cycle after conversion"
    assert archive.exists()

    receipt = service.execute_approved_archive_removal(vault, preview["approval_token"])

    assert not archive.exists()
    assert receipt["receipt"]["archive_sha256"] == preview["preview"]["archive_sha256"]
    receipt_path = vault / receipt["receipt"]["receipt_relative"]
    assert receipt_path.is_file()
    assert hashlib.sha256(receipt_path.read_bytes()).hexdigest()
