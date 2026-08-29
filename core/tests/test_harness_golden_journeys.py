"""Outcome-level truth checks for every advertised harness journey."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

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
    "claude-desktop",
    "codex",
    "copilot-cli",
    "cowork",
    "cursor",
    "gemini-cli",
    "obsidian",
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
    mac_home_prefix = "/" + "Users" + "/"
    assert "/home/" not in encoded and mac_home_prefix not in encoded


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
    chatgpt_limits = " ".join(get_profile("chatgpt-work").limitations).lower()
    assert "web" in chatgpt_limits
    assert "desktop" in chatgpt_limits
    assert "vault" in chatgpt_limits
    assert "person" in chatgpt_limits
    guide = (REPO_ROOT / "docs" / "HARNESS-PORTABILITY.md").read_text(encoding="utf-8")
    assert "only leftover that still needs Dave is granting the Dex vault folder" in guide

    claude = _rows("claude-code")
    assert claude["hooks"]["status"] == "native"
    assert claude["session-lifecycle"]["mode"] == "automatic"

    desktop = _rows("claude-desktop")
    assert desktop["mcp"]["status"] == "native"
    assert desktop["hooks"]["mode"] == "unavailable"

    codex = _rows("codex")
    assert codex["hooks"]["status"] == "native"
    assert codex["hooks"]["mode"] == "guided"
    assert "ide" in " ".join(get_profile("codex").limitations).lower()

    copilot = _rows("copilot-cli")
    assert copilot["agent-plugins"]["status"] == "native"
    assert copilot["hooks"]["status"] == "not-verified"
    assert copilot["hooks"]["mode"] == "unavailable"
    copilot_limits = " ".join(get_profile("copilot-cli").limitations).lower()
    assert "person" in copilot_limits
    assert "copilot plugin install" in copilot_limits
    assert "ubuntu cloud" in copilot_limits
    assert "no recorded live session" in copilot_limits

    cowork = _rows("cowork")
    assert cowork["agent-skills"]["status"] == "native"
    assert cowork["mcp"]["mode"] == "guided"
    assert "public" in " ".join(get_profile("cowork").limitations).lower()

    cursor = _rows("cursor")
    assert cursor["agent-plugins"]["status"] == "native"
    assert cursor["hooks"]["status"] == "native"

    gemini = _rows("gemini-cli")
    assert gemini["agent-skills"]["status"] == "native"
    assert gemini["session-lifecycle"]["mode"] == "automatic"

    obsidian = _rows("obsidian")
    assert obsidian["vault"]["status"] == "native"
    assert obsidian["mcp"]["mode"] == "unavailable"
    assert obsidian["agent-skills"]["mode"] == "unavailable"
    obsidian_limits = " ".join(get_profile("obsidian").limitations).lower()
    assert "read-only" in obsidian_limits
    assert "community store" in obsidian_limits
    assert "ubuntu cloud" in obsidian_limits

    pi = _rows("pi")
    assert get_profile("pi").adapter["kind"] == "pi-extension"
    assert pi["session-lifecycle"]["mode"] == "automatic"
    assert pi["mcp"]["mode"] == "unavailable"


def _pi_checkout() -> Path | None:
    """Return an explicitly supplied or canonical local Pi checkout, if present."""
    candidates = []
    configured = os.environ.get("DEX_PI_CHECKOUT", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        return candidate if (candidate / ".git").exists() and candidate.is_dir() else None
    candidates.extend((REPO_ROOT.parent / "dex-pi", Path("/srv/dex-dev/src/dex-pi")))
    for candidate in candidates:
        if (candidate / ".git").exists() and candidate.is_dir():
            return candidate
    return None


def test_pi_descriptor_pins_an_exact_repository_manifest_and_claim_evidence() -> None:
    """Native/automatic Pi claims must carry reviewable, exact-head evidence."""
    adapter = get_profile("pi").adapter
    evidence = adapter.get("evidence")

    assert isinstance(evidence, dict)
    assert evidence["repository_url"].startswith("https://")
    assert len(evidence["commit"]) == 40
    assert all(character in "0123456789abcdef" for character in evidence["commit"])
    assert evidence["manifest_path"] == "extensions/dex/package.json"
    assert len(evidence["manifest_sha256"]) == 64
    assert set(evidence["claims"]) == {
        row["id"]
        for row in get_profile("pi").capability_rows()
        if row["status"] == "native" or row["mode"] == "automatic"
    }


def test_pi_pinned_checkout_matches_manifest_and_lifecycle_evidence() -> None:
    """When the pinned Pi checkout is available, verify its actual source bytes."""
    checkout = _pi_checkout()
    if checkout is None:
        message = (
            "Pi checkout unavailable; set DEX_PI_CHECKOUT for exact-head conformance "
            "(release verification must fail with DEX_PI_REQUIRE_CONFORMANCE=1)."
        )
        if os.environ.get("DEX_PI_REQUIRE_CONFORMANCE") == "1":
            pytest.fail(message)
        pytest.skip(message)

    evidence = get_profile("pi").adapter["evidence"]
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, check=True, capture_output=True, text=True
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert head == evidence["commit"]
    assert status == ""

    manifest = checkout / evidence["manifest_path"]
    assert manifest.is_file()
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == evidence["manifest_sha256"]

    for claim in evidence["claims"].values():
        source = checkout / claim["path"]
        assert source.is_file(), claim["path"]
        assert claim["marker"] in source.read_text(encoding="utf-8"), claim["marker"]


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
    plan = (REPO_ROOT / "docs" / "plans" / "2026-08-25-harness-portable-dex.md").read_text(
        encoding="utf-8"
    )
    for label in (
        "Codex",
        "ChatGPT",
        "Claude Code",
        "Claude Desktop",
        "Claude Cowork",
        "GitHub Copilot CLI",
        "Cursor",
        "Gemini CLI",
        "Obsidian",
        "Agent Plugins v1",
        "Pi",
        "BB",
    ):
        assert label in guide
    assert "Unreleased build" in guide
    assert "have not been merged, published" in guide
    assert "Do not run an actual destructive command" in guide
    assert "`codex/harness-portable-dex-resume`" in guide
    assert "**Branch:** `codex/harness-portable-dex-resume`" in plan
    assert "| macOS | Native CI required on each review head |" in guide
    assert "| Windows | Native CI required on each review head |" in guide
    assert "Exact-commit native evidence belongs to the draft pull request" in guide
    assert "| macOS | Release-ready |" not in guide
    assert "| Windows | Release-ready |" not in guide
