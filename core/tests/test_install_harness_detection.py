"""The installer delegates harness detection to the shared registry."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_installer_uses_shared_multi_harness_detection() -> None:
    installer = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")

    assert "-m core.harnesses.registry detect --format json" in installer
    assert "DEX_HARNESSES_JSON" in installer
    assert "Open one of these apps" in installer
    assert "if command -v claude" not in installer
    assert 'DEX_CHAT_APP="your AI app"' not in installer


def test_installer_leaves_capability_confirmation_to_setup() -> None:
    installer = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")

    assert "Dex detected" in installer
    assert "confirm one or several harnesses" in installer
    assert "type: /setup" in installer
