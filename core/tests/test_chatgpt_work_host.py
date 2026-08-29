"""ChatGPT Work desktop is not Codex, and the install contract is local-plugin + vault."""

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
    assert "Codex" not in result.detail
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
