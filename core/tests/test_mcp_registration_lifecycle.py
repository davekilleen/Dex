"""Receipt-backed repair of one missing Dex-owned MCP registration."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from core import portable_contract
from core.customization_migration.registration import mcp_registration_snippet
from core.lifecycle import service
from core.transaction.engine import PlanRejected

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_NAME = "customization-migration-mcp"


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "System/.mcp.json.example", vault / "System/.mcp.json.example")
    (vault / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "user-owned": {
                        "command": "user-mcp",
                        "args": ["--keep-this-exactly"],
                        "env": {"USER_TOKEN": "synthetic-user-secret"},
                    }
                },
                "unrelated_user_setting": {"preserve": True},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return vault


def test_mcp_registration_is_previewed_and_adds_only_the_missing_dex_entry(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    before = json.loads((vault / ".mcp.json").read_text(encoding="utf-8"))

    previewed = service.build_and_preview_mcp_registration(vault)
    executed = service.execute_approved_mcp_registration(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )

    after = json.loads((vault / ".mcp.json").read_text(encoding="utf-8"))
    assert previewed["preview"]["registration"]["server_name"] == SERVER_NAME
    assert after["mcpServers"]["user-owned"] == before["mcpServers"]["user-owned"]
    assert after["unrelated_user_setting"] == before["unrelated_user_setting"]
    assert SERVER_NAME in after["mcpServers"]
    assert executed["receipt"]["purpose"] == "mcp-registration"

    already_current = service.build_and_preview_mcp_registration(vault)
    assert already_current == {
        "api_version": service.api_version,
        "needed": False,
        "preview": None,
        "approval_token": None,
    }


def test_mcp_registration_contract_allows_only_the_explicit_user_approved_file() -> None:
    assert portable_contract.update_write_verdict(
        ".mcp.json", exists=True, operation="mcp-registration"
    ).allowed
    assert not portable_contract.update_write_verdict(
        "System/user-profile.yaml", exists=True, operation="mcp-registration"
    ).allowed


def test_legacy_qmd_reconciliation_contract_is_a_separate_single_file_exception() -> None:
    verdict = portable_contract.update_write_verdict(
        ".mcp.json",
        exists=True,
        operation="legacy-qmd-reconciliation",
    )
    assert verdict.allowed
    assert verdict.action == "write-explicitly-approved-legacy-qmd-reconciliation"
    assert not portable_contract.update_write_verdict(
        "System/user-profile.yaml",
        exists=True,
        operation="legacy-qmd-reconciliation",
    ).allowed


def test_mcp_registration_refuses_if_user_configuration_changes_after_preview(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    previewed = service.build_and_preview_mcp_registration(vault)
    config = vault / ".mcp.json"
    changed = json.loads(config.read_text(encoding="utf-8"))
    changed["unrelated_user_setting"]["changed_after_preview"] = True
    config.write_text(json.dumps(changed, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(PlanRejected, match="approval does not match"):
        service.execute_approved_mcp_registration(
            vault,
            previewed["preview"],
            previewed["approval_token"],
        )

    after = json.loads(config.read_text(encoding="utf-8"))
    assert SERVER_NAME not in after["mcpServers"]
    assert after["unrelated_user_setting"]["changed_after_preview"] is True


def test_mcp_registration_uses_the_delivered_definition_not_a_preserved_seed(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    stale_seed = json.loads((vault / "System/.mcp.json.example").read_text(encoding="utf-8"))
    stale_seed["mcpServers"].pop(SERVER_NAME, None)
    (vault / "System/.mcp.json.example").write_text(
        json.dumps(stale_seed, indent=2) + "\n", encoding="utf-8"
    )

    previewed = service.build_and_preview_mcp_registration(vault)
    service.execute_approved_mcp_registration(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )

    configured = json.loads((vault / ".mcp.json").read_text(encoding="utf-8"))
    assert configured["mcpServers"][SERVER_NAME] == {
        "type": "stdio",
        "command": f"{vault}/.venv/bin/python",
        "args": [f"{vault}/core/mcp/customization_migration_server.py"],
        "env": {"VAULT_PATH": str(vault)},
    }


def test_shipped_registration_definition_matches_the_fresh_install_template() -> None:
    template = json.loads((REPO_ROOT / "System/.mcp.json.example").read_text(encoding="utf-8"))
    assert mcp_registration_snippet()[SERVER_NAME] == template["mcpServers"][SERVER_NAME]


# The only registration an update can add to a vault that already exists is
# SERVER_NAME above: `_mcp_registration_preview` names exactly one server, and
# the code that performs an update is the *installed* release's code, so a
# server added to this repo today can never be registered by any release a user
# is already running. Doctor's `mcp.orphans` check requires every
# `core/mcp/*_server.py` in the vault to be registered in `.mcp.json`, so a new
# file in that directory makes Doctor report BROKEN on every upgraded install --
# which is exactly what the historic-fleet upgrade gate caught when
# `core/mcp/pipedrive_server.py` was added.
#
# Adding to this tuple therefore is not a formality: it is a claim that every
# released version can register the new server. An opt-in integration server
# belongs at `core/integrations/<name>/<name>_server.py`, where its setup skill
# registers it when the user connects it.
CORE_MCP_SERVERS = (
    "analytics_server.py",
    "calendar_server.py",
    "career_server.py",
    "customization_migration_server.py",
    "dex_improvements_server.py",
    "granola_server.py",
    "onboarding_server.py",
    "resume_server.py",
    "session_memory_server.py",
    "work_server.py",
)


def test_core_mcp_server_set_is_pinned() -> None:
    """No release may add a core MCP server no installed version can register."""
    shipped = tuple(sorted(p.name for p in (REPO_ROOT / "core/mcp").glob("*_server.py")))
    assert shipped == CORE_MCP_SERVERS


def test_every_core_mcp_server_is_registered_for_fresh_installs() -> None:
    template = json.loads((REPO_ROOT / "System/.mcp.json.example").read_text(encoding="utf-8"))
    registered = {
        Path(argument).name
        for entry in template["mcpServers"].values()
        for argument in entry.get("args", [])
        if isinstance(argument, str) and "/core/mcp/" in argument
    }
    assert set(CORE_MCP_SERVERS) <= registered
