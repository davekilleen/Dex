"""ChatGPT Work desktop is not Codex, and the install contract is local-plugin + vault."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from core.harnesses.chatgpt_work_personal_copy import (
    STALE_WORK_COPY_SENTENCE,
    write_personal_copy,
)
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
ADAPTER_PATH = REPO_ROOT / "core" / "harnesses" / "adapters" / "chatgpt-work.json"


@pytest.fixture
def context(tmp_path: Path) -> doctor.DoctorContext:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "core").mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return doctor.DoctorContext(vault_root=vault, repo_root=vault, home=home, now=NOW)


def test_chatgpt_work_markers_do_not_select_codex() -> None:
    for env in (
        {"CHATGPT_WORK": "1"},
        {"OPENAI_WORK": "1"},
        {"CHATGPT_WORK_COMPANION": "1"},
    ):
        detected = [profile.id for profile in detect_harnesses(env=env)]
        assert detected == ["chatgpt-work"]

    detected = [
        profile.id
        for profile in detect_harnesses(env={}, paths=[Path("/tmp/.chatgpt-work/app")])
    ]
    assert detected == ["chatgpt-work"]

    assert [profile.id for profile in detect_harnesses(env={"CODEX_CLI": "1"})] == ["codex"]
    assert [
        profile.id
        for profile in detect_harnesses(env={}, paths=[Path("/tmp/.codex/session")])
    ] == ["codex"]


def test_shared_plugin_cache_is_not_chatgpt_work_proof() -> None:
    cache = Path("/tmp/.codex/plugins/cache/dex-unreleased/dex/local")
    detected = [profile.id for profile in detect_harnesses(env={}, paths=[cache])]
    assert detected == ["codex"]
    assert "chatgpt-work" not in detected


def test_chatgpt_work_plugin_uses_the_shared_desktop_layout() -> None:
    adapter = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
    manifest = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text())

    assert adapter["native_paths"] == [
        ".codex-plugin/plugin.json",
        "skills/",
        "hooks/codex.json",
        ".codex-mcp.json",
    ]
    assert manifest["name"] == "dex"
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./.codex-mcp.json"
    assert manifest["hooks"] == "./hooks/codex.json"
    for relative in adapter["native_paths"]:
        assert (PLUGIN_ROOT / relative).exists()


def test_chatgpt_work_install_contract_names_marketplace_and_vault_grant() -> None:
    adapter = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
    example = adapter["example"]
    guide = example["install_guide"].lower()

    assert example["repo_marketplace"] == ".agents/plugins/marketplace.json"
    assert example["personal_marketplace"] == "~/.agents/plugins/marketplace.json"
    assert example["personal_marketplace_root"] == "~"
    assert example["personal_plugin_copy"] == "~/.codex/plugins/dex"
    assert example["install_cache"] == "~/.codex/plugins/cache/dex-unreleased/dex/local/"
    assert "work locally" in example["vault_grant"].lower()
    assert "dex vault folder" in example["vault_grant"].lower()
    assert "~/.codex/plugins/dex" in guide
    assert "marketplace.json" in guide
    assert "./.codex/plugins/dex" in guide
    assert "marketplace root" in guide
    assert "not the .agents/plugins folder" in guide
    assert "restart" in guide
    assert "work locally" in guide
    assert "dex vault folder" in guide
    assert "ubuntu cloud" in guide
    assert example["personal_marketplace_document"] == {
        "name": "dex-unreleased",
        "interface": {"displayName": "Dex (unreleased local build)"},
        "plugins": [
            {
                "name": "dex",
                "source": {"source": "local", "path": "./.codex/plugins/dex"},
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            }
        ],
    }


def test_developer_guide_names_the_chatgpt_work_desktop_steps() -> None:
    guide = (REPO_ROOT / "docs" / "HARNESS-PORTABILITY.md").read_text(encoding="utf-8")

    assert "ChatGPT Work desktop" in guide
    assert "~/.codex/plugins/dex" in guide
    assert "./.codex/plugins/dex" in guide
    assert "Work locally" in guide
    assert "Ubuntu Cloud is not that journey" in guide
    assert "shared plugin cache on disk is not ChatGPT Work proof" in guide
    assert "will not invent that grant" in guide
    assert "personal-copy + home marketplace write is not that grant" in guide
    assert "doctor stays silent when that personal copy is current or missing" in guide.lower()
    assert "pointing at this copy step" in guide.lower()


def test_personal_marketplace_path_resolves_from_home_not_agents_plugins() -> None:
    adapter = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
    example = adapter["example"]
    relative = example["personal_marketplace_document"]["plugins"][0]["source"]["path"]
    marketplace_layout = Path(".agents") / "plugins" / "marketplace.json"

    assert relative == "./.codex/plugins/dex"
    assert relative.startswith("./")
    assert ".." not in Path(relative).parts

    home = Path("/home/person")
    marketplace = home / marketplace_layout
    marketplace_root = marketplace
    for part in reversed(marketplace_layout.parts):
        assert marketplace_root.name == part
        marketplace_root = marketplace_root.parent

    resolved = (marketplace_root / relative.removeprefix("./")).resolve()
    assert marketplace_root == home
    assert resolved == (home / ".codex" / "plugins" / "dex").resolve()
    assert resolved != (marketplace.parent / "dex").resolve()


def test_repo_marketplace_stays_inside_the_dex_checkout() -> None:
    marketplace = json.loads(
        (REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text()
    )
    plugin_path = marketplace["plugins"][0]["source"]["path"]

    assert marketplace["name"] == "dex-unreleased"
    assert marketplace["interface"]["displayName"] == "Dex (unreleased local build)"
    assert plugin_path.startswith("./")
    assert ".." not in Path(plugin_path).parts
    resolved = (REPO_ROOT / plugin_path).resolve()
    resolved.relative_to(REPO_ROOT.resolve())
    assert resolved == (PLUGIN_ROOT).resolve()


def test_doctor_names_chatgpt_work_desktop_and_web_limits_without_calling_it_codex(
    context: doctor.DoctorContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    receipt = build_receipt_for_ids(
        ["chatgpt-work"],
        detected_ids=("chatgpt-work",),
        source="user-confirmed",
        generated_at=NOW,
    )
    receipt_path = context.vault_root / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(canonical_receipt_bytes(receipt))

    result = doctor._probe_harness_capabilities(context)
    limitations = list(get_profile("chatgpt-work").limitations)
    joined = " ".join(limitations).lower()

    assert result.verdict == "OK"
    assert "ChatGPT Work" in result.detail
    assert "You confirmed Codex." not in result.detail
    assert "Codex is a written door and this checkup cannot see whether you have opened it." in (
        result.detail
    )
    assert "Codex is a written door you have never opened." not in result.detail
    assert "web" in result.detail.lower()
    assert "https" in result.detail.lower()
    assert "desktop" in result.detail.lower()
    assert "vault" in result.detail.lower()
    assert "person" in result.detail.lower()
    assert "detection tests and ci" in joined
    assert "shared plugin cache" in joined
    assert "codex" not in joined
    assert result.structured_detail["selected"] == ["chatgpt-work"]
    assert result.structured_detail["limitations"] == {"chatgpt-work": limitations}
    assert STALE_WORK_COPY_SENTENCE not in result.detail
    _assert_no_granted_true_signal(result.structured_detail)


def test_setup_preview_keeps_chatgpt_work_separate_from_codex() -> None:
    inspected = onboarding_server.inspect_harnesses(["chatgpt-work"])

    assert inspected["selected"] == ["chatgpt-work"]
    assert "codex" not in inspected["selected"]
    by_id = {row["id"]: row for row in inspected["profiles"]}
    assert by_id["chatgpt-work"]["limitations"] == list(
        get_profile("chatgpt-work").limitations
    )
    joined = " ".join(by_id["chatgpt-work"]["limitations"]).lower()
    assert "web" in joined
    assert "https" in joined
    assert "desktop" in joined
    assert "vault" in joined
    assert "person" in joined
    assert "codex" not in joined


def _chatgpt_work_mcp_roundtrip(plugin_root: Path, vault: Path) -> list[dict]:
    mcp = json.loads((plugin_root / ".codex-mcp.json").read_text(encoding="utf-8"))
    server = mcp["dex-core"]
    args = [
        argument.replace("${PLUGIN_ROOT}", str(plugin_root))
        for argument in server["args"]
    ]
    payload = "".join(
        json.dumps(message) + "\n"
        for message in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "boot_today", "arguments": {"vault_path": str(vault)}},
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
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
        cwd=plugin_root,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
        check=True,
    )
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def _write_vault(root: Path) -> Path:
    vault = root / "Dex Vault"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "pillars.yaml").write_text(
        'pillars:\n  - id: focus\n    name: "Focus"\n    description: "Do the important work"\n',
        encoding="utf-8",
    )
    return vault


def _assert_no_granted_true_signal(payload: Any) -> None:
    encoded = json.dumps(payload, default=str).lower()
    assert '"granted": true' not in encoded
    assert '"granted":true' not in encoded
    assert "granted=true" not in encoded
    if isinstance(payload, dict):
        assert payload.get("granted") is not True
        for nested in payload.values():
            _assert_no_granted_true_signal(nested)
    elif isinstance(payload, list):
        for nested in payload:
            _assert_no_granted_true_signal(nested)


def _assert_no_folder_grant(home: Path, vault: Path) -> None:
    assert not (REPO_ROOT / "core" / "harnesses" / "chatgpt_work_grant.py").exists()
    assert not (home / ".chatgpt-work").exists()
    assert not any(home.rglob("*grant*"))
    assert not any(vault.rglob("*grant*"))
    env_blob = " ".join(
        "%s=%s" % (key, value) for key, value in os.environ.items()
    ).lower()
    assert "chatgpt_work_grant" not in env_blob
    assert "openai_work_grant" not in env_blob


def test_personal_marketplace_copy_can_read_a_vault_without_inventing_the_folder_grant(
    tmp_path: Path,
) -> None:
    adapter = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
    example = adapter["example"]
    home = tmp_path / "home"
    vault = _write_vault(tmp_path)
    layout = write_personal_copy(home=home, plugin_root=PLUGIN_ROOT)

    relative = example["personal_marketplace_document"]["plugins"][0]["source"]["path"]
    resolved = (home / relative.removeprefix("./")).resolve()
    responses = _chatgpt_work_mcp_roundtrip(layout.plugin_copy, vault)
    skills = list((layout.plugin_copy / "skills").glob("*/SKILL.md"))
    limitations = " ".join(get_profile("chatgpt-work").limitations).lower()

    assert layout.plugin_copy == home / ".codex" / "plugins" / "dex"
    assert layout.marketplace == home / ".agents" / "plugins" / "marketplace.json"
    assert layout.source_path == "./.codex/plugins/dex"
    assert resolved == layout.plugin_copy.resolve()
    assert (layout.plugin_copy / ".codex-plugin" / "plugin.json").is_file()
    assert skills
    assert responses[1]["result"]["structuredContent"]["pillars"][0]["name"] == "Focus"
    assert responses[2]["result"]["structuredContent"]["refused"] is True
    assert "grant the dex vault folder" in limitations
    assert "detection tests and ci" in limitations
    assert "grant" in example["vault_grant"].lower()
    assert "grant" in layout.leftover.lower()
    assert not hasattr(layout, "granted")
    _assert_no_folder_grant(home, vault)
    assert "folder grant" not in json.dumps(example["personal_marketplace_document"]).lower()


def test_personal_copy_path_stays_fail_closed_without_a_folder_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
    example = adapter["example"]
    home = tmp_path / "home"
    vault = _write_vault(tmp_path)
    before_files = {path.resolve() for path in vault.rglob("*") if path.is_file()}

    layout = write_personal_copy(home=home, plugin_root=PLUGIN_ROOT)
    marketplace = json.loads(layout.marketplace.read_text(encoding="utf-8"))
    responses = _chatgpt_work_mcp_roundtrip(layout.plugin_copy, vault)
    after_files = {path.resolve() for path in vault.rglob("*") if path.is_file()}
    rows = {row["id"]: row for row in get_profile("chatgpt-work").capability_rows()}
    limitations = list(get_profile("chatgpt-work").limitations)
    joined_limits = " ".join(limitations).lower()

    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    doctor_context = doctor.DoctorContext(
        vault_root=vault, repo_root=vault, home=home, now=NOW
    )
    receipt = build_receipt_for_ids(
        ["chatgpt-work"],
        detected_ids=("chatgpt-work",),
        source="user-confirmed",
        generated_at=NOW,
    )
    receipt_path = doctor_context.vault_root / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(canonical_receipt_bytes(receipt))
    doctor_result = doctor._probe_harness_capabilities(doctor_context)
    inspected = onboarding_server.inspect_harnesses(["chatgpt-work"])
    setup_row = next(row for row in inspected["profiles"] if row["id"] == "chatgpt-work")
    detected_from_copy = [
        profile.id
        for profile in detect_harnesses(env={}, paths=[layout.plugin_copy])
    ]
    guide = (REPO_ROOT / "docs" / "HARNESS-PORTABILITY.md").read_text(encoding="utf-8")

    assert example["personal_plugin_copy"] == "~/.codex/plugins/dex"
    assert example["personal_marketplace"] == "~/.agents/plugins/marketplace.json"
    assert layout.plugin_copy != PLUGIN_ROOT
    assert marketplace["plugins"][0]["source"]["path"] == "./.codex/plugins/dex"
    assert responses[1]["result"]["structuredContent"]["pillars"][0]["name"] == "Focus"
    assert responses[2]["result"]["structuredContent"]["refused"] is True
    assert after_files == before_files
    assert rows["vault"]["mode"] == "guided"
    assert rows["vault"]["status"] == "partial"
    assert "grant the dex vault folder" in joined_limits
    assert "detection tests and ci" in joined_limits
    assert "person still has to" in joined_limits
    assert detected_from_copy == ["codex"]
    assert "chatgpt-work" not in detected_from_copy
    assert doctor_result.verdict == "OK"
    assert "chatgpt work" in doctor_result.detail.lower()
    assert "grant the dex vault folder" in doctor_result.detail.lower()
    assert doctor_result.structured_detail["selected"] == ["chatgpt-work"]
    assert doctor_result.structured_detail["fully_automatic"] is False
    vault_row = next(row for row in setup_row["capabilities"] if row["id"] == "vault")
    assert vault_row["mode"] == "guided"
    assert vault_row["status"] == "partial"
    _assert_no_granted_true_signal(doctor_result.structured_detail)
    _assert_no_granted_true_signal(inspected)
    _assert_no_granted_true_signal(receipt)
    _assert_no_folder_grant(home, vault)
    assert STALE_WORK_COPY_SENTENCE not in doctor_result.detail
    assert "will not invent that grant" in guide
    assert "not that grant" in guide.lower()
    assert "doctor stays silent when that personal copy is current or missing" in guide.lower()


def _plant_work_plugin(root: Path, version: str) -> Path:
    plugin = root / "packages" / "dex-agent-plugin"
    manifest = plugin / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"name": "dex", "version": version}) + "\n",
        encoding="utf-8",
    )
    return plugin


def _plant_personal_work_copy(home: Path, version: str) -> Path:
    plugin = home / ".codex" / "plugins" / "dex"
    manifest = plugin / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"name": "dex", "version": version}) + "\n",
        encoding="utf-8",
    )
    return plugin


def _chatgpt_work_doctor_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> doctor.DoctorContext:
    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    home.mkdir()
    receipt = build_receipt_for_ids(
        ["chatgpt-work"],
        detected_ids=("chatgpt-work",),
        source="user-confirmed",
        generated_at=NOW,
    )
    receipt_path = vault / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(canonical_receipt_bytes(receipt))
    return doctor.DoctorContext(vault_root=vault, repo_root=repo, home=home, now=NOW)


def test_doctor_stays_silent_when_the_personal_work_copy_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _chatgpt_work_doctor_context(tmp_path, monkeypatch)
    _plant_work_plugin(context.repo_root, "1.0.1")
    rows = {row["id"]: row for row in get_profile("chatgpt-work").capability_rows()}

    result = doctor._probe_harness_capabilities(context)
    rendered = doctor._result_json(
        next(check for check in doctor.QUICK_CHECKS if check.id == "harness.capabilities"),
        result,
    )

    assert result.verdict == "OK"
    assert rows["vault"]["mode"] == "guided"
    assert rows["vault"]["status"] == "partial"
    assert "grant the dex vault folder" in result.detail.lower()
    assert STALE_WORK_COPY_SENTENCE not in result.detail
    assert STALE_WORK_COPY_SENTENCE not in rendered["detail"]
    assert "behind this folder" not in result.detail.lower()
    _assert_no_granted_true_signal(result.structured_detail)
    _assert_no_granted_true_signal(rendered)
    _assert_no_folder_grant(context.home, context.vault_root)


def test_doctor_stays_silent_when_the_personal_work_copy_matches_this_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _chatgpt_work_doctor_context(tmp_path, monkeypatch)
    _plant_work_plugin(context.repo_root, "1.0.1")
    _plant_personal_work_copy(context.home, "1.0.1")

    result = doctor._probe_harness_capabilities(context)
    rendered = doctor._result_json(
        next(check for check in doctor.QUICK_CHECKS if check.id == "harness.capabilities"),
        result,
    )

    assert result.verdict == "OK"
    assert STALE_WORK_COPY_SENTENCE not in result.detail
    assert STALE_WORK_COPY_SENTENCE not in rendered["detail"]
    assert "behind this folder" not in result.detail.lower()
    assert result.detail.endswith(STALE_WORK_COPY_SENTENCE) is False
    _assert_no_granted_true_signal(result.structured_detail)
    _assert_no_granted_true_signal(rendered)
    _assert_no_folder_grant(context.home, context.vault_root)


def test_doctor_names_the_copy_step_only_when_the_personal_work_copy_is_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _chatgpt_work_doctor_context(tmp_path, monkeypatch)
    _plant_work_plugin(context.repo_root, "1.0.1")
    _plant_personal_work_copy(context.home, "1.0.0")
    rows = {row["id"]: row for row in get_profile("chatgpt-work").capability_rows()}

    result = doctor._probe_harness_capabilities(context)
    rendered = doctor._result_json(
        next(check for check in doctor.QUICK_CHECKS if check.id == "harness.capabilities"),
        result,
    )

    assert result.verdict == "OK"
    assert result.detail.endswith(STALE_WORK_COPY_SENTENCE)
    assert rendered["detail"].endswith(STALE_WORK_COPY_SENTENCE)
    assert "packages/dex-agent-plugin" in STALE_WORK_COPY_SENTENCE
    assert "~/.codex/plugins/dex" in STALE_WORK_COPY_SENTENCE
    assert result.detail.count(STALE_WORK_COPY_SENTENCE) == 1
    assert rows["vault"]["mode"] == "guided"
    assert rows["vault"]["status"] == "partial"
    assert result.structured_detail["fully_automatic"] is False
    _assert_no_granted_true_signal(result.structured_detail)
    _assert_no_granted_true_signal(rendered)
    _assert_no_folder_grant(context.home, context.vault_root)
    assert not hasattr(result, "granted")


def test_doctor_does_not_mention_a_stale_work_copy_when_chatgpt_work_is_not_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    home.mkdir()
    _plant_work_plugin(repo, "1.0.1")
    _plant_personal_work_copy(home, "1.0.0")
    receipt = build_receipt_for_ids(
        ["codex"],
        detected_ids=("codex",),
        source="user-confirmed",
        generated_at=NOW,
    )
    receipt_path = vault / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(canonical_receipt_bytes(receipt))
    context = doctor.DoctorContext(vault_root=vault, repo_root=repo, home=home, now=NOW)

    result = doctor._probe_harness_capabilities(context)

    assert result.verdict == "OK"
    assert STALE_WORK_COPY_SENTENCE not in result.detail
    assert "behind this folder" not in result.detail.lower()
    _assert_no_granted_true_signal(result.structured_detail)
