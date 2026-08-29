"""VS Code and Kiro use the shipped package. Settings stay off; Kiro wakes when named."""

from __future__ import annotations

import json
import os
import subprocess
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
VSCODE_ADAPTER = REPO_ROOT / "core" / "harnesses" / "adapters" / "vscode.json"
KIRO_ADAPTER = REPO_ROOT / "core" / "harnesses" / "adapters" / "kiro.json"


@pytest.fixture
def context(tmp_path: Path) -> doctor.DoctorContext:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "core").mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return doctor.DoctorContext(vault_root=vault, repo_root=vault, home=home, now=NOW)


def test_vscode_and_kiro_markers_stay_apart_from_cursor_and_each_other() -> None:
    assert [profile.id for profile in detect_harnesses(env={"VSCODE": "1"})] == ["vscode"]
    assert [profile.id for profile in detect_harnesses(env={"VSCODE_HARNESS": "1"})] == [
        "vscode"
    ]
    assert [profile.id for profile in detect_harnesses(env={"KIRO": "1"})] == ["kiro"]
    assert [profile.id for profile in detect_harnesses(env={"KIRO_IDE": "1"})] == ["kiro"]
    assert [profile.id for profile in detect_harnesses(env={"KIRO_CLI": "1"})] == ["kiro"]
    assert [profile.id for profile in detect_harnesses(env={"CURSOR_TRACE_ID": "x"})] == [
        "cursor"
    ]

    assert [
        profile.id
        for profile in detect_harnesses(
            env={}, paths=[Path("/Applications/Visual Studio Code.app")]
        )
    ] == ["vscode"]
    assert [
        profile.id
        for profile in detect_harnesses(env={}, paths=[Path("/tmp/.kiro/session")])
    ] == ["kiro"]
    assert [
        profile.id
        for profile in detect_harnesses(env={}, paths=[Path("/tmp/.cursor/projects")])
    ] == ["cursor"]


def test_shared_vscode_pid_is_not_enough_to_guess_the_host() -> None:
    detected = [profile.id for profile in detect_harnesses(env={"VSCODE_PID": "99"})]
    assert detected == []


def test_shipped_package_already_names_dex_for_kiro() -> None:
    manifest = json.loads((PLUGIN_ROOT / "plugin.json").read_text(encoding="utf-8"))
    adapter = json.loads(KIRO_ADAPTER.read_text(encoding="utf-8"))

    assert adapter["example"]["wake_when_named"] == "dex"
    assert "dex" in manifest["keywords"]
    assert manifest["$schema"] == adapter["example"]["open_plugin_schema"]
    assert (PLUGIN_ROOT / "skills").is_dir()
    assert (PLUGIN_ROOT / "mcp.json").is_file()


def test_vscode_install_contract_names_off_by_default_settings_and_setup_picker() -> None:
    adapter = json.loads(VSCODE_ADAPTER.read_text(encoding="utf-8"))
    example = adapter["example"]
    guide = example["install_guide"].lower()

    assert example["local_package"] == "./packages/dex-agent-plugin"
    assert example["enable_setting"] == "chat.plugins.enabled"
    assert example["plugin_locations_setting"] == "chat.pluginLocations"
    assert example["plugin_locations_entry"] == "./packages/dex-agent-plugin"
    assert example["settings_off_by_default"] == ["chat.plugins.enabled"]
    assert "off" in guide
    assert "chat.plugins.enabled" in guide
    assert "chat.pluginlocations" in guide
    assert "./packages/dex-agent-plugin" in guide
    assert "/setup" in example["setup_picker"]
    assert "ubuntu cloud" in guide
    assert "hooks are not part of this path" in guide
    assert "chatgpt" not in guide
    for relative in adapter["native_paths"]:
        assert (PLUGIN_ROOT / relative).exists()


def test_kiro_install_contract_names_folder_import_and_wake_when_named() -> None:
    adapter = json.loads(KIRO_ADAPTER.read_text(encoding="utf-8"))
    example = adapter["example"]
    guide = example["install_guide"].lower()

    assert example["local_package"] == "./packages/dex-agent-plugin"
    assert "Import power from a folder" in example["install_ui"]
    assert example["wake_when_named"] == "dex"
    assert "packages/dex-agent-plugin" in guide
    assert "name dex" in guide
    assert "powers panel" in guide
    assert "/setup" in example["setup_picker"]
    assert "ubuntu cloud" in guide
    assert "hooks are not part of this path" in guide
    assert "chatgpt" not in guide
    for relative in adapter["native_paths"]:
        assert (PLUGIN_ROOT / relative).exists()


def test_developer_guide_names_the_vscode_and_kiro_desktop_steps() -> None:
    guide = (REPO_ROOT / "docs" / "HARNESS-PORTABILITY.md").read_text(encoding="utf-8")

    assert "chat.plugins.enabled" in guide
    assert "chat.pluginLocations" in guide
    assert "./packages/dex-agent-plugin" in guide
    assert "Import power from a folder" in guide
    assert "name Dex" in guide
    assert "/setup" in guide
    assert "Ubuntu Cloud is not that journey" in guide


def test_doctor_names_vscode_settings_and_setup_picker_without_calling_it_chatgpt_work(
    context: doctor.DoctorContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    receipt = build_receipt_for_ids(
        ["vscode"],
        detected_ids=("vscode",),
        source="user-confirmed",
        generated_at=NOW,
    )
    receipt_path = context.vault_root / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(canonical_receipt_bytes(receipt))

    result = doctor._probe_harness_capabilities(context)
    limitations = list(get_profile("vscode").limitations)
    joined = " ".join(limitations).lower()

    assert result.verdict == "OK"
    assert "Visual Studio Code" in result.detail
    assert "ChatGPT Work" not in result.detail
    assert "off by default" in joined
    assert "chat.plugins.enabled" in joined
    assert "/setup" in joined
    assert "person" in joined
    assert "ubuntu cloud" in joined
    assert "hooks are not included" in joined
    assert "chatgpt" not in joined
    assert result.structured_detail["selected"] == ["vscode"]
    assert result.structured_detail["limitations"] == {"vscode": limitations}
    rows = {row["id"]: row for row in get_profile("vscode").capability_rows()}
    assert rows["hooks"]["status"] == "not-verified"
    assert rows["hooks"]["mode"] == "unavailable"
    assert get_profile("vscode").adapter["status"] == "native-local"


def test_doctor_names_kiro_wake_and_setup_picker_without_calling_it_chatgpt_work(
    context: doctor.DoctorContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    receipt = build_receipt_for_ids(
        ["kiro"],
        detected_ids=("kiro",),
        source="user-confirmed",
        generated_at=NOW,
    )
    receipt_path = context.vault_root / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(canonical_receipt_bytes(receipt))

    result = doctor._probe_harness_capabilities(context)
    limitations = list(get_profile("kiro").limitations)
    joined = " ".join(limitations).lower()

    assert result.verdict == "OK"
    assert "Kiro" in result.detail
    assert "ChatGPT Work" not in result.detail
    assert "name dex" in joined
    assert "/setup" in joined
    assert "person" in joined
    assert "ubuntu cloud" in joined
    assert "hooks are not included" in joined
    assert "chatgpt" not in joined
    assert result.structured_detail["selected"] == ["kiro"]
    assert result.structured_detail["limitations"] == {"kiro": limitations}
    rows = {row["id"]: row for row in get_profile("kiro").capability_rows()}
    assert rows["hooks"]["status"] == "not-verified"
    assert rows["hooks"]["mode"] == "unavailable"
    assert get_profile("kiro").adapter["status"] == "native-local"


def test_setup_preview_keeps_vscode_and_kiro_separate_from_chatgpt_work() -> None:
    vscode = onboarding_server.inspect_harnesses(["vscode"])
    kiro = onboarding_server.inspect_harnesses(["kiro"])

    assert vscode["selected"] == ["vscode"]
    assert kiro["selected"] == ["kiro"]
    assert "chatgpt-work" not in vscode["selected"]
    assert "chatgpt-work" not in kiro["selected"]
    by_vscode = {row["id"]: row for row in vscode["profiles"]}
    by_kiro = {row["id"]: row for row in kiro["profiles"]}
    vscode_limits = " ".join(by_vscode["vscode"]["limitations"]).lower()
    kiro_limits = " ".join(by_kiro["kiro"]["limitations"]).lower()
    assert "chat.plugins.enabled" in vscode_limits
    assert "off by default" in vscode_limits
    assert "/setup" in vscode_limits
    assert "name dex" in kiro_limits
    assert "/setup" in kiro_limits
    assert "chatgpt" not in vscode_limits
    assert "chatgpt" not in kiro_limits


def _expand_plugin_vars(value: str, plugin_root: Path, plugin_data: Path) -> str:
    return value.replace("${PLUGIN_ROOT}", str(plugin_root)).replace(
        "${PLUGIN_DATA}", str(plugin_data)
    )


def test_shipped_mcp_json_can_read_a_vault_without_opening_vscode_or_kiro(
    tmp_path: Path,
) -> None:
    mcp = json.loads((PLUGIN_ROOT / "mcp.json").read_text(encoding="utf-8"))
    server = mcp["mcpServers"]["dex-core"]
    plugin_data = tmp_path / "plugin-data"
    plugin_data.mkdir()
    vault = tmp_path / "Dex"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "pillars.yaml").write_text(
        'pillars:\n  - id: focus\n    name: "Focus"\n    description: "Do the important work"\n',
        encoding="utf-8",
    )
    args = [
        _expand_plugin_vars(argument, PLUGIN_ROOT, plugin_data)
        for argument in server["args"]
    ]
    env = {
        **os.environ,
        "PYTHONNOUSERSITE": "1",
    }
    for key, value in server.get("env", {}).items():
        env[key] = _expand_plugin_vars(value, PLUGIN_ROOT, plugin_data)
    payload = "".join(
        json.dumps(message) + "\n"
        for message in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "boot_today", "arguments": {"vault_path": str(vault)}},
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "check_safety_gate",
                    "arguments": {"vault_path": str(vault), "command": "rm -rf /"},
                },
            },
        )
    )
    completed = subprocess.run(
        [server["command"], *args],
        input=payload,
        text=True,
        capture_output=True,
        cwd=vault,
        env=env,
        check=True,
    )
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    names = {tool["name"] for tool in responses[1]["result"]["tools"]}
    skills = list((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))

    assert server["command"] == "node"
    assert "--stdio" in args
    assert skills
    assert names == {
        "dex_harness_profiles",
        "boot_today",
        "get_person_context",
        "check_safety_gate",
    }
    assert responses[2]["result"]["structuredContent"]["pillars"][0]["name"] == "Focus"
    assert responses[3]["result"]["structuredContent"]["refused"] is True
    assert get_profile("vscode").capability_rows()
    assert get_profile("kiro").capability_rows()
