"""Copilot CLI is a started local-plugin journey, not a recorded live session."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.harnesses.registry import detect_harnesses, get_profile
from core.mcp import onboarding_server
from core.onboarding.harness_receipt import (
    build_receipt_for_ids,
    canonical_receipt_bytes,
)
from core.utils import doctor

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "packages" / "dex-agent-plugin"
ADAPTER_PATH = REPO_ROOT / "core" / "harnesses" / "adapters" / "copilot-cli.json"


@pytest.fixture
def context(tmp_path: Path) -> doctor.DoctorContext:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "core").mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return doctor.DoctorContext(vault_root=vault, repo_root=vault, home=home, now=NOW)


def test_copilot_cli_markers_do_not_select_chatgpt_work() -> None:
    for env in (
        {"COPILOT_CLI": "1"},
        {"GH_COPILOT": "1"},
        {"GITHUB_COPILOT": "1"},
    ):
        detected = [profile.id for profile in detect_harnesses(env=env)]
        assert detected == ["copilot-cli"]

    for path in (Path("/tmp/.copilot/session"), Path("/tmp/copilot/bin")):
        detected = [profile.id for profile in detect_harnesses(env={}, paths=[path])]
        assert detected == ["copilot-cli"]

    assert [profile.id for profile in detect_harnesses(env={"CHATGPT_WORK": "1"})] == [
        "chatgpt-work"
    ]


def test_direct_install_cache_is_not_a_recorded_live_session() -> None:
    cache = Path("/tmp/.copilot/installed-plugins/_direct/source")
    detected = [profile.id for profile in detect_harnesses(env={}, paths=[cache])]
    assert detected == ["copilot-cli"]
    joined = " ".join(get_profile("copilot-cli").limitations).lower()
    assert "no recorded live session" in joined
    assert "ubuntu cloud" in joined
    assert "detection tests and ci" in joined


def test_copilot_cli_plugin_uses_the_open_package_layout() -> None:
    adapter = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
    manifest = json.loads((PLUGIN_ROOT / "plugin.json").read_text(encoding="utf-8"))
    mcp = json.loads((PLUGIN_ROOT / "mcp.json").read_text(encoding="utf-8"))
    claude_mcp = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))

    assert adapter["native_paths"] == ["plugin.json", "skills/", "mcp.json"]
    assert adapter["status"] == "native-local"
    assert manifest["$schema"] == adapter["example"]["open_plugin_schema"]
    assert manifest["name"] == "dex-agent-plugin"
    assert "skills" not in manifest
    assert "mcpServers" not in manifest
    assert "hooks" not in manifest
    assert mcp["mcpServers"]["dex-core"]["cwd"] == "${PLUGIN_ROOT}"
    assert "${PLUGIN_ROOT}" in json.dumps(mcp)
    assert "CLAUDE_PLUGIN_ROOT" not in json.dumps(mcp)
    assert "CLAUDE_PLUGIN_ROOT" in json.dumps(claude_mcp)
    for relative in adapter["native_paths"]:
        assert (PLUGIN_ROOT / relative).exists()
    assert not (PLUGIN_ROOT / "AGENTS.md").exists()


def test_copilot_cli_install_contract_names_local_plugin_and_folder() -> None:
    adapter = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
    example = adapter["example"]
    guide = example["install_guide"].lower()

    assert example["local_package"] == "./packages/dex-agent-plugin"
    assert example["install_command"] == "copilot plugin install ./packages/dex-agent-plugin"
    assert example["inspect_command"] == "copilot plugin list"
    assert example["mcp_file"] == "mcp.json"
    assert example["direct_install_cache"] == "~/.copilot/installed-plugins/_direct/"
    assert "dex folder" in example["vault_grant"].lower()
    assert "current working directory" in example["vault_grant"].lower()
    assert "./packages/dex-agent-plugin" in guide
    assert "copilot plugin install" in guide
    assert "copilot plugin list" in guide
    assert "dex folder" in guide
    assert "ubuntu cloud" in guide
    assert "not a live install" in guide
    assert "hooks are not bundled" in guide


def test_developer_guide_names_the_copilot_cli_terminal_steps() -> None:
    guide = (REPO_ROOT / "docs" / "HARNESS-PORTABILITY.md").read_text(encoding="utf-8")

    assert "copilot plugin install ./packages/dex-agent-plugin" in guide
    assert "copilot plugin list" in guide
    assert "Ubuntu Cloud is not that journey" in guide
    assert "Detection tests and CI are not a live install" in guide


def test_doctor_names_copilot_person_and_hook_limits_without_calling_it_chatgpt_work(
    context: doctor.DoctorContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    receipt = build_receipt_for_ids(
        ["copilot-cli"],
        detected_ids=("copilot-cli",),
        source="user-confirmed",
        generated_at=NOW,
    )
    receipt_path = context.vault_root / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(canonical_receipt_bytes(receipt))

    result = doctor._probe_harness_capabilities(context)
    limitations = list(get_profile("copilot-cli").limitations)
    joined = " ".join(limitations).lower()

    assert result.verdict == "OK"
    assert "GitHub Copilot CLI" in result.detail
    assert "ChatGPT Work" not in result.detail
    assert "hook" in result.detail.lower()
    assert "person" in result.detail.lower()
    assert "ubuntu cloud" in result.detail.lower()
    assert "fully automatic" not in result.detail.lower()
    assert "copilot plugin install" in joined
    assert "./packages/dex-agent-plugin" in joined
    assert "no recorded live session" in joined
    assert "chatgpt" not in joined
    assert result.structured_detail["selected"] == ["copilot-cli"]
    assert result.structured_detail["limitations"] == {"copilot-cli": limitations}
    rows = {row["id"]: row for row in get_profile("copilot-cli").capability_rows()}
    assert rows["hooks"]["status"] == "not-verified"
    assert rows["hooks"]["mode"] == "unavailable"
    assert get_profile("copilot-cli").adapter["status"] == "native-local"


def test_setup_preview_keeps_copilot_cli_separate_from_chatgpt_work() -> None:
    inspected = onboarding_server.inspect_harnesses(["copilot-cli"])

    assert inspected["selected"] == ["copilot-cli"]
    assert "chatgpt-work" not in inspected["selected"]
    by_id = {row["id"]: row for row in inspected["profiles"]}
    assert by_id["copilot-cli"]["limitations"] == list(
        get_profile("copilot-cli").limitations
    )
    joined = " ".join(by_id["copilot-cli"]["limitations"]).lower()
    assert "hook" in joined
    assert "person" in joined
    assert "copilot plugin install" in joined
    assert "ubuntu cloud" in joined
    assert "chatgpt" not in joined
    assert "microsoft 365" not in joined
