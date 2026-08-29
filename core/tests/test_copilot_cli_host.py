"""Copilot CLI is a started local-plugin journey, not a recorded live session."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

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
# Named by the adapter's direct-install cache plus the existing detection path
# `~/.copilot/installed-plugins/_direct/source`. Do not invent a new product path.
DIRECT_SOURCE_ID = "source"


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


def _reviewed_install_target() -> Path:
    """Resolve the path a person would pass to `copilot plugin install`."""
    adapter = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
    example = adapter["example"]
    local_package = example["local_package"]
    assert example["install_command"] == f"copilot plugin install {local_package}"
    assert local_package == "./packages/dex-agent-plugin"
    target = (REPO_ROOT / Path(local_package)).resolve()
    assert target == PLUGIN_ROOT.resolve()
    return target


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


def test_install_argument_is_the_reviewed_open_plugin_layout() -> None:
    """packages/dex-agent-plugin is the installable Open Plugin folder, not a live session."""
    adapter = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
    example = adapter["example"]
    target = _reviewed_install_target()
    manifest = json.loads((target / "plugin.json").read_text(encoding="utf-8"))
    mcp = json.loads((target / "mcp.json").read_text(encoding="utf-8"))
    skills = list((target / "skills").glob("*/SKILL.md"))
    limitations = " ".join(get_profile("copilot-cli").limitations)

    assert adapter["kind"] == "open-plugin-spec"
    assert adapter["native_paths"] == ["plugin.json", "skills/", "mcp.json"]
    assert example["manifest"] == "packages/dex-agent-plugin/plugin.json"
    assert example["mcp_file"] == "mcp.json"
    assert (target / "plugin.json").is_file()
    assert (target / "mcp.json").is_file()
    assert (target / "skills").is_dir()
    assert target.relative_to(REPO_ROOT.resolve()) == Path("packages/dex-agent-plugin")
    assert manifest["$schema"] == example["open_plugin_schema"]
    assert manifest["name"] == "dex-agent-plugin"
    assert "hooks" not in manifest
    assert mcp["$schema"] == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
    assert "mcpServers" in mcp
    assert mcp["mcpServers"]["dex-core"]["cwd"] == "${PLUGIN_ROOT}"
    assert skills
    assert "hooks/" not in adapter["native_paths"]
    assert not (target / "hooks" / "copilot.json").exists()
    assert example["install_command"] in limitations
    assert "no recorded live session" in limitations.lower()
    assert "hooks are not included" in limitations.lower()


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
    assert "_direct" in guide
    assert "fixture is not a live install" in guide


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


def _expand_plugin_vars(value: str, plugin_root: Path, plugin_data: Path) -> str:
    return value.replace("${PLUGIN_ROOT}", str(plugin_root)).replace(
        "${PLUGIN_DATA}", str(plugin_data)
    )


def _named_direct_cache(home: Path) -> Path:
    adapter = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
    relative = adapter["example"]["direct_install_cache"]
    assert relative.startswith("~/")
    assert relative == "~/.copilot/installed-plugins/_direct/"
    return home.joinpath(*Path(relative[2:]).parts)


def _install_reviewed_package_into_direct_cache(home: Path) -> Path:
    """Copy the reviewed package the way `copilot plugin install` would, without a binary."""
    installed = _named_direct_cache(home) / DIRECT_SOURCE_ID
    shutil.copytree(
        PLUGIN_ROOT,
        installed,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return installed


def _list_direct_plugins(home: Path) -> list[dict[str, Any]]:
    """Read the named `_direct` cache the way `copilot plugin list` would inspect it."""
    cache = _named_direct_cache(home)
    listed: list[dict[str, Any]] = []
    if not cache.is_dir():
        return listed
    for child in sorted(cache.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "plugin.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        author = manifest.get("author") or {}
        listed.append(
            {
                "name": manifest.get("name", ""),
                "author": author.get("name", "") if isinstance(author, Mapping) else "",
                "source_id": child.name,
                "path": child,
            }
        )
    return listed


def _refuse_copilot_binary(command: Sequence[str]) -> None:
    names = [Path(str(part)).name for part in command]
    assert "copilot" not in names
    assert all("copilot plugin" not in str(part) for part in command)


def _write_dex_folder_vault(root: Path) -> Path:
    vault = root / "Dex"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "pillars.yaml").write_text(
        'pillars:\n  - id: focus\n    name: "Focus"\n    description: "Do the important work"\n',
        encoding="utf-8",
    )
    return vault


def _copilot_mcp_roundtrip(
    plugin_root: Path, vault: Path, plugin_data: Path
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    mcp = json.loads((plugin_root / "mcp.json").read_text(encoding="utf-8"))
    server = mcp["mcpServers"]["dex-core"]
    args = [
        _expand_plugin_vars(argument, plugin_root, plugin_data)
        for argument in server["args"]
    ]
    env = {
        **os.environ,
        "PYTHONNOUSERSITE": "1",
    }
    for key, value in server.get("env", {}).items():
        env[key] = _expand_plugin_vars(value, plugin_root, plugin_data)
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
    command = [server["command"], *args]
    _refuse_copilot_binary(command)
    completed = subprocess.run(
        command,
        input=payload,
        text=True,
        capture_output=True,
        cwd=vault,
        env=env,
        check=True,
    )
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    return server, args, responses


def test_copilot_mcp_json_can_read_a_vault_without_opening_the_cli(tmp_path: Path) -> None:
    plugin_data = tmp_path / "plugin-data"
    plugin_data.mkdir()
    vault = _write_dex_folder_vault(tmp_path)
    server, args, responses = _copilot_mcp_roundtrip(PLUGIN_ROOT, vault, plugin_data)
    names = {tool["name"] for tool in responses[1]["result"]["tools"]}
    skills = list((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))
    limitations = " ".join(get_profile("copilot-cli").limitations).lower()

    assert server["command"] == "node"
    assert "--stdio" in args
    assert "${PLUGIN_ROOT}" not in " ".join(args)
    assert skills
    assert names == {
        "dex_harness_profiles",
        "boot_today",
        "get_person_context",
        "check_safety_gate",
    }
    assert responses[2]["result"]["structuredContent"]["pillars"][0]["name"] == "Focus"
    assert responses[3]["result"]["structuredContent"]["refused"] is True
    assert "copilot" not in args
    assert "no recorded live session" in limitations
    assert "hooks are not included" in limitations
    assert get_profile("copilot-cli").capability_rows()
    rows = {row["id"]: row for row in get_profile("copilot-cli").capability_rows()}
    assert rows["hooks"]["mode"] == "unavailable"
    assert rows["hooks"]["status"] == "not-verified"


def test_direct_install_fixture_completes_the_written_path_without_opening_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
    example = adapter["example"]
    home = tmp_path / "home"
    plugin_data = tmp_path / "plugin-data"
    plugin_data.mkdir()
    vault = _write_dex_folder_vault(tmp_path)
    before_files = {path.resolve() for path in vault.rglob("*") if path.is_file()}

    installed = _install_reviewed_package_into_direct_cache(home)
    listed = _list_direct_plugins(home)
    listed_text = " ".join(
        f"{row['name']} {row['author']}" for row in listed
    ).lower()
    server, args, responses = _copilot_mcp_roundtrip(installed, vault, plugin_data)
    skills = list((installed / "skills").glob("*/SKILL.md"))
    after_files = {path.resolve() for path in vault.rglob("*") if path.is_file()}
    limitations = list(get_profile("copilot-cli").limitations)
    joined_limits = " ".join(limitations).lower()
    rows = {row["id"]: row for row in get_profile("copilot-cli").capability_rows()}

    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    doctor_context = doctor.DoctorContext(
        vault_root=vault, repo_root=vault, home=home, now=NOW
    )
    receipt = build_receipt_for_ids(
        ["copilot-cli"],
        detected_ids=("copilot-cli",),
        source="user-confirmed",
        generated_at=NOW,
    )
    receipt_path = doctor_context.vault_root / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(canonical_receipt_bytes(receipt))
    doctor_result = doctor._probe_harness_capabilities(doctor_context)
    inspected = onboarding_server.inspect_harnesses(["copilot-cli"])
    setup_limits = " ".join(
        next(row["limitations"] for row in inspected["profiles"] if row["id"] == "copilot-cli")
    ).lower()
    guide = (REPO_ROOT / "docs" / "HARNESS-PORTABILITY.md").read_text(encoding="utf-8")

    source = _reviewed_install_target()
    assert example["install_command"] == "copilot plugin install ./packages/dex-agent-plugin"
    assert example["inspect_command"] == "copilot plugin list"
    assert example["direct_install_cache"] == "~/.copilot/installed-plugins/_direct/"
    assert installed == home / ".copilot" / "installed-plugins" / "_direct" / DIRECT_SOURCE_ID
    assert installed != PLUGIN_ROOT
    assert source == PLUGIN_ROOT.resolve()
    assert (source / "plugin.json").is_file()
    assert (source / "mcp.json").is_file()
    assert (source / "skills").is_dir()
    assert (installed / "plugin.json").is_file()
    assert (installed / "mcp.json").is_file()
    assert (installed / "skills").is_dir()
    assert "hooks/" not in adapter["native_paths"]
    assert not (installed / "hooks" / "copilot.json").exists()
    assert "hooks" not in json.loads((installed / "plugin.json").read_text(encoding="utf-8"))
    assert listed
    assert "dex" in listed_text
    assert any(row["name"] == "dex-agent-plugin" for row in listed)
    assert any((row["author"] or "").lower() == "dex" for row in listed)
    assert vault.name == "Dex"
    assert skills
    assert server["command"] == "node"
    assert server["cwd"] == "${PLUGIN_ROOT}"
    assert "--stdio" in args
    assert str(installed) in " ".join(args)
    assert str(PLUGIN_ROOT) not in " ".join(args)
    assert "${PLUGIN_ROOT}" not in " ".join(args)
    assert responses[2]["result"]["structuredContent"]["pillars"][0]["name"] == "Focus"
    assert responses[3]["result"]["structuredContent"]["refused"] is True
    assert after_files == before_files
    assert rows["hooks"]["mode"] == "unavailable"
    assert rows["hooks"]["status"] == "not-verified"
    assert "no recorded live session" in joined_limits
    assert "copilot plugin install ./packages/dex-agent-plugin" in joined_limits
    assert "detection tests and ci" in joined_limits
    assert "person still has to" in joined_limits
    assert "ubuntu cloud" in joined_limits
    assert "hooks are not included" in joined_limits
    assert doctor_result.verdict == "OK"
    assert "person" in doctor_result.detail.lower()
    assert "ubuntu cloud" in doctor_result.detail.lower()
    assert "fully automatic" not in doctor_result.detail.lower()
    assert "copilot plugin install" in setup_limits
    assert "person" in setup_limits
    assert "ubuntu cloud" in setup_limits
    assert "fixture is not a live install" in guide
    assert shutil.which("copilot") is None or "copilot" not in args
