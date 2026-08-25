"""Outcome-level truth checks for every advertised harness journey."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.harnesses.registry import get_profile, list_profiles
from core.onboarding.harness_receipt import (
    build_receipt_for_ids,
    canonical_receipt_bytes,
    summarize_receipt,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "packages" / "dex-agent-plugin"
EXPECTED_IDS = (
    "agent-plugin",
    "bb",
    "chatgpt-work",
    "claude-code",
    "codex",
    "copilot-cli",
    "cowork",
    "pi",
)


def _rows(profile_id: str) -> dict[str, dict]:
    return {row["id"]: row for row in get_profile(profile_id).capability_rows()}


def test_multi_harness_onboarding_receipt_preserves_every_delivery_mode() -> None:
    receipt = build_receipt_for_ids(
        EXPECTED_IDS,
        detected_ids=("codex", "claude-code"),
        source="user-confirmed",
        generated_at=datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc),
    )
    summary = summarize_receipt(receipt)
    encoded = canonical_receipt_bytes(receipt).decode("utf-8")

    assert tuple(receipt["selected"]) == EXPECTED_IDS
    assert set(summary["modes"]) == {
        "automatic",
        "on_demand",
        "guided",
        "unavailable",
    }
    assert all(summary["modes"][mode] > 0 for mode in summary["modes"])
    assert summary["fully_automatic"] is False
    assert "/home/" not in encoded and "/Users/" not in encoded


def test_each_harness_has_one_real_surface_and_one_explicit_boundary() -> None:
    assert tuple(profile.id for profile in list_profiles()) == EXPECTED_IDS

    generic = _rows("agent-plugin")
    assert generic["mcp"]["status"] == "native"
    assert generic["hooks"]["mode"] == "unavailable"

    bb = _rows("bb")
    assert bb["agent-plugins"]["status"] == "native"
    assert bb["mcp"]["mode"] == "unavailable"

    chatgpt = _rows("chatgpt-work")
    assert chatgpt["agent-plugins"]["status"] == "native"
    assert chatgpt["mcp"]["mode"] == "guided"
    assert "web" in " ".join(get_profile("chatgpt-work").limitations).lower()

    claude = _rows("claude-code")
    assert claude["hooks"]["status"] == "native"
    assert claude["session-lifecycle"]["mode"] == "automatic"

    codex = _rows("codex")
    assert codex["hooks"]["status"] == "native"
    assert codex["hooks"]["mode"] == "guided"
    assert "ide" in " ".join(get_profile("codex").limitations).lower()

    copilot = _rows("copilot-cli")
    assert copilot["agent-plugins"]["status"] == "native"
    assert copilot["hooks"]["status"] == "not-verified"
    assert copilot["hooks"]["mode"] == "unavailable"

    cowork = _rows("cowork")
    assert cowork["agent-skills"]["status"] == "native"
    assert cowork["mcp"]["mode"] == "guided"
    assert "public" in " ".join(get_profile("cowork").limitations).lower()

    pi = _rows("pi")
    assert get_profile("pi").adapter["kind"] == "pi-extension"
    assert pi["session-lifecycle"]["mode"] == "automatic"
    assert pi["mcp"]["mode"] == "unavailable"


def test_native_package_manifests_point_only_inside_the_package() -> None:
    codex = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text())
    claude = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
    agent_plugin = json.loads((PLUGIN_ROOT / "plugin.json").read_text())

    for relative in (codex["skills"], codex["mcpServers"], codex["hooks"]):
        assert relative.startswith("./")
        resolved = (PLUGIN_ROOT / relative).resolve()
        resolved.relative_to(PLUGIN_ROOT.resolve())
        assert resolved.exists()
    assert claude["name"] == codex["name"] == "dex"
    assert agent_plugin["$schema"].endswith("/1.0.0/plugin.schema.json")


def test_developer_preview_guide_names_every_supported_profile_and_stop_line() -> None:
    guide = (REPO_ROOT / "docs" / "HARNESS-PORTABILITY.md").read_text(encoding="utf-8")
    for label in (
        "Codex",
        "ChatGPT",
        "Claude Code",
        "Claude Cowork",
        "GitHub Copilot CLI",
        "Agent Plugins v1",
        "Pi",
        "BB",
    ):
        assert label in guide
    assert "Unreleased build" in guide
    assert "have not been merged, published" in guide
    assert "Do not run an actual destructive command" in guide
