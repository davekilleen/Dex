"""Lane D read-only customization-migration MCP adapter contracts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

from core.customization_migration import service as migration_service
from core.customization_migration.capsule import create_capsule, preview_capsule
from core.customization_migration.capsule_model import EVIDENCE_SECTIONS_V0
from core.mcp import customization_migration_server as server
from core.tests.test_customization_assessment import _linked_customized_vault
from core.tests.vault_observed_writes import snapshot_vault
from core.utils.mcp_handshake import mcp_stdio_handshake

REPO_ROOT = Path(__file__).resolve().parents[3]


TOOL_NAMES = (
    "assess_customizations",
    "preview_customization_capsule",
    "read_customization_migration_status",
    "read_staging_status",
    "read_activation_status",
    "read_customization_capsule_section",
    "read_customization_capsule_blob",
)


def _payload(result: list[object]) -> dict[str, object]:
    return json.loads(result[0].text)


def _call(
    monkeypatch,
    vault: Path,
    name: str,
    arguments: dict[str, object] | None = None,
) -> dict[str, object]:
    monkeypatch.setenv("VAULT_PATH", str(vault))
    return _payload(asyncio.run(server.handle_call_tool(name, arguments or {})))


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()


def test_tool_listing_is_exact_and_every_schema_is_closed() -> None:
    tools = asyncio.run(server.handle_list_tools())

    assert tuple(tool.name for tool in tools) == TOOL_NAMES
    assert tuple(server.TOOL_REGISTRY) == TOOL_NAMES
    for tool in tools:
        assert tool.inputSchema["type"] == "object"
        assert tool.inputSchema["additionalProperties"] is False
    section_tool = next(
        tool
        for tool in tools
        if tool.name == "read_customization_capsule_section"
    )
    assert section_tool.inputSchema["properties"]["section"]["enum"] == sorted(
        EVIDENCE_SECTIONS_V0
    )


def test_assess_and_preview_happy_paths(tmp_path: Path, monkeypatch) -> None:
    vault = _linked_customized_vault(tmp_path)

    assessment = _call(monkeypatch, vault, "assess_customizations")
    preview = _call(monkeypatch, vault, "preview_customization_capsule")

    assert assessment["feature_status"] == "ok"
    assert assessment["assessment"]["verdict"] == "OK"
    assert preview["feature_status"] == "ok"
    assert preview["preview"]["files"]


def test_preview_tool_never_returns_the_cli_confirmation_token(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _linked_customized_vault(tmp_path)
    real_token = migration_service.preview_to_dict(vault)["preview_sha256"]
    monkeypatch.setenv("VAULT_PATH", str(vault))

    response = asyncio.run(server.handle_call_tool("preview_customization_capsule", {}))
    serialized_response = response[0].text

    assert isinstance(real_token, str)
    assert real_token not in serialized_response
    assert "use the Dex CLI preview command to obtain the confirmation token" in (
        serialized_response
    )


def test_status_includes_validation_for_each_capsule(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _linked_customized_vault(tmp_path)
    preview = preview_capsule(vault)
    create_capsule(vault, preview, preview.preview_sha256)
    before = snapshot_vault(vault)

    payload = _call(monkeypatch, vault, "read_customization_migration_status")

    assert payload["feature_status"] == "ok"
    assert payload["migration_status"]["capsules"] == [
        {
            "capsule_id": preview.capsule_id,
            "state": "capsule-created",
            "validation": {"status": "OK", "mismatches": []},
            "staging": {
                "capsule_id": preview.capsule_id,
                "proposals": [],
                "truncated": False,
            },
            "verification_verdicts": {
                "OK": 0,
                "BLOCKED": 0,
                "UNKNOWN": 0,
            },
            "pending_rebuild": True,
            "activation": {
                "capsule_id": preview.capsule_id,
                "proposal_id": None,
                "state": "unknown",
                "reason": "activation-not-found",
                "activation_receipt_present": False,
                "rewindable": False,
            },
            "activation_receipt_present": False,
            "rewindable": False,
        }
    ]
    assert snapshot_vault(vault) == before


def test_staging_and_activation_status_tools_are_read_only(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _linked_customized_vault(tmp_path)
    preview = preview_capsule(vault)
    create_capsule(vault, preview, preview.preview_sha256)
    before = snapshot_vault(vault)

    staging = _call(
        monkeypatch,
        vault,
        "read_staging_status",
        {"capsule_id": preview.capsule_id},
    )
    activation = _call(
        monkeypatch,
        vault,
        "read_activation_status",
        {"capsule_id": preview.capsule_id},
    )

    assert staging["feature_status"] == "ok"
    assert staging["staging_status"] == {
        "capsule_id": preview.capsule_id,
        "proposals": [],
        "truncated": False,
    }
    assert activation["feature_status"] == "ok"
    assert activation["activation_status"] == {
        "capsule_id": preview.capsule_id,
        "proposal_id": None,
        "state": "unknown",
        "reason": "activation-not-found",
        "activation_receipt_present": False,
        "rewindable": False,
    }
    assert snapshot_vault(vault) == before


def test_section_pagination_walks_all_records_and_binds_digest(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _linked_customized_vault(tmp_path)
    for index in range(125):
        target = vault / f".scripts/custom-{index:03d}.py"
        target.write_text(f"print({index!r})\n", encoding="utf-8")
    preview = preview_capsule(vault)
    create_capsule(vault, preview, preview.preview_sha256)

    records: list[object] = []
    cursor: int | None = None
    pages = 0
    while True:
        args: dict[str, object] = {
            "capsule_id": preview.capsule_id,
            "section": "customizations",
        }
        if cursor is not None:
            args["cursor"] = cursor
        page = _call(
            monkeypatch,
            vault,
            "read_customization_capsule_section",
            args,
        )
        assert page["feature_status"] == "ok"
        assert len(page["records"]) <= 100
        assert len(_canonical(page["records"])) <= 256 * 1024
        records.extend(page["records"])
        pages += 1
        if page["complete"]:
            assert page["next_cursor"] is None
            assert page["total_record_count"] == len(records)
            assert page["section_digest"] == hashlib.sha256(
                _canonical(records)
            ).hexdigest()
            break
        cursor = page["next_cursor"]

    assert pages >= 2


def test_blob_tool_returns_digest_bound_text_and_writes_nothing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = _linked_customized_vault(tmp_path)
    preview = preview_capsule(vault)
    create_capsule(vault, preview, preview.preview_sha256)
    source = preview.blob_sources[0]
    before = snapshot_vault(vault)

    payload = _call(
        monkeypatch,
        vault,
        "read_customization_capsule_blob",
        {
            "capsule_id": preview.capsule_id,
            "sha256": source.sha256,
        },
    )

    assert payload["feature_status"] == "ok"
    assert payload["capsule_id"] == preview.capsule_id
    assert payload["sha256"] == source.sha256
    assert payload["byte_size"] == source.byte_size
    assert payload["text"] == (vault / source.source_path).read_text(
        encoding="utf-8"
    )
    assert snapshot_vault(vault) == before


def test_malformed_unknown_and_missing_inputs_are_structured_errors(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _linked_customized_vault(tmp_path)

    cases = (
        ("does_not_exist", {}, "unknown-tool"),
        ("assess_customizations", {"extra": True}, "malformed-arguments"),
        (
            "read_customization_capsule_section",
            {"capsule_id": "cap-" + "0" * 16, "section": "customizations"},
            "unknown-capsule",
        ),
        (
            "read_customization_capsule_section",
            {"capsule_id": "bad", "section": "customizations"},
            "malformed-arguments",
        ),
        (
            "read_customization_capsule_section",
            {"capsule_id": "cap-" + "0" * 16, "section": "not-a-section"},
            "invalid-section",
        ),
    )
    for name, arguments, code in cases:
        payload = _call(monkeypatch, vault, name, arguments)
        assert payload["feature_status"] in {"broken", "unknown"}
        assert payload["error"]["code"] == code


def test_invalid_cursor_is_structured(tmp_path: Path, monkeypatch) -> None:
    vault = _linked_customized_vault(tmp_path)
    preview = preview_capsule(vault)
    create_capsule(vault, preview, preview.preview_sha256)

    payload = _call(
        monkeypatch,
        vault,
        "read_customization_capsule_section",
        {
            "capsule_id": preview.capsule_id,
            "section": "customizations",
            "cursor": 999,
        },
    )

    assert payload["feature_status"] == "broken"
    assert payload["error"]["code"] == "invalid-cursor"


def test_large_assessment_and_preview_are_explicitly_truncated(monkeypatch, tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    assessment = {"verdict": "OK", "records": [{"n": n} for n in range(501)]}
    preview = {
        "preview_sha256": "a" * 64,
        "assessment": assessment,
        "files": [{"n": n} for n in range(501)],
    }
    monkeypatch.setattr(server.migration_service, "assess_to_dict", lambda _root: assessment)
    monkeypatch.setattr(server.migration_service, "preview_to_dict", lambda _root: preview)

    assessed = _call(monkeypatch, vault, "assess_customizations")
    previewed = _call(monkeypatch, vault, "preview_customization_capsule")

    assert len(assessed["assessment"]["records"]) == 500
    assert assessed["truncated"] is True
    assert assessed["complete_via"] == "read_customization_capsule_section"
    assert len(previewed["preview"]["files"]) == 500
    assert len(previewed["preview"]["assessment"]["records"]) == 500
    assert previewed["truncated"] is True
    assert previewed["complete_via"] == "read_customization_capsule_section"


def test_server_source_has_no_mutation_surface_or_network_imports() -> None:
    source = Path(server.__file__).read_text(encoding="utf-8")

    forbidden = (
        "Transaction",
        "create_" + "capsule",
        "abandon_" + "capsule",
        "os.replace",
        "os.write",
        "socket",
        "urllib",
        "requests",
        "httpx",
    )
    assert not [name for name in forbidden if name in source]


def test_tool_list_cannot_gain_customization_mutation_names() -> None:
    names = {tool.name for tool in asyncio.run(server.handle_list_tools())}
    mutating_names = {
        "create_capsule",
        "stage_candidate",
        "write_verification_report",
        "activate",
        "rewind",
        "stage_regeneration",
        "activate_customizations",
        "rewind_customizations",
        "create_confirmed_capsule",
        "abandon_existing_capsule",
        "stage_confirmed_candidate",
        "verify_staging_to_dict",
        "activate_confirmed",
        "rewind_acknowledged",
    }

    assert names.isdisjoint(mutating_names)


def test_unregistered_dispatch_name_is_rejected_before_dispatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = _linked_customized_vault(tmp_path)

    payload = _call(
        monkeypatch,
        vault,
        "read_customization_capsule_blob_hidden_alias",
        {},
    )

    assert payload["feature_status"] == "broken"
    assert payload["error"]["code"] == "unknown-tool"


def test_every_registered_handler_is_observed_read_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = _linked_customized_vault(tmp_path)
    preview = preview_capsule(vault)
    create_capsule(vault, preview, preview.preview_sha256)
    source = preview.blob_sources[0]
    mutators = (
        "create_confirmed_capsule",
        "abandon_existing_capsule",
        "stage_confirmed_candidate",
        "verify_staging_to_dict",
        "activate_confirmed",
        "rewind_acknowledged",
        "recover_confirmed",
    )

    def mutation_trap(*_args, **_kwargs):
        raise AssertionError("registered MCP handler reached a mutator")

    for name in mutators:
        monkeypatch.setattr(
            server.migration_service,
            name,
            mutation_trap,
            raising=False,
        )

    arguments = {
        "assess_customizations": {},
        "preview_customization_capsule": {},
        "read_customization_migration_status": {},
        "read_staging_status": {"capsule_id": preview.capsule_id},
        "read_activation_status": {"capsule_id": preview.capsule_id},
        "read_customization_capsule_section": {
            "capsule_id": preview.capsule_id,
            "section": "customizations",
        },
        "read_customization_capsule_blob": {
            "capsule_id": preview.capsule_id,
            "sha256": source.sha256,
        },
    }
    before = snapshot_vault(vault)

    for name in server.TOOL_REGISTRY:
        payload = _call(monkeypatch, vault, name, arguments[name])
        assert payload["feature_status"] in {"ok", "unknown"}
        assert snapshot_vault(vault) == before


def test_stdio_server_boots_lists_tools_and_exits_cleanly(
    tmp_path: Path,
) -> None:
    vault = _linked_customized_vault(tmp_path)
    env = {
        "HOME": str(tmp_path),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(REPO_ROOT),
        "PYTHONUNBUFFERED": "1",
        "VAULT_PATH": str(vault),
    }

    result = mcp_stdio_handshake(
        [sys.executable, "-m", "core.mcp.customization_migration_server"],
        cwd=REPO_ROOT,
        env=env,
        # Hang-guard, not a perf assertion: server boot competes with other
        # pytest-xdist workers for CPU, so keep several multiples of headroom.
        timeout=30,
    )

    assert result.ok, f"{result.error}\nstderr:\n{result.stderr}"
    assert result.response is not None
    assert result.response["result"]["serverInfo"]["name"] == (
        "dex-customization-migration-mcp"
    )
