"""Contract tests for the temporary Dex_System documentation bridge."""

from __future__ import annotations

from pathlib import Path

from core import portable_contract


REPO_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_GUIDES = (
    "Background_Processing_Guide.md",
    "Calendar_Setup.md",
    "Dex_Jobs_to_Be_Done.md",
    "Dex_System_Guide.md",
    "Dex_Technical_Guide.md",
    "Distribution_Checklist.md",
    "Distribution_Strategy.md",
    "Folder_Structure.md",
    "Memory_Ownership.md",
    "Named_Sessions_Guide.md",
    "Obsidian_Guide.md",
    "Updating_Dex.md",
)


def test_bridge_guides_are_derived_byte_for_byte_from_current_legacy_docs() -> None:
    for filename in BRIDGE_GUIDES:
        legacy = REPO_ROOT / "06-Resources" / "Dex_System" / filename
        bridge = REPO_ROOT / "docs" / "Dex_System" / filename
        assert bridge.read_bytes() == legacy.read_bytes(), filename


def test_bridge_readme_points_to_both_homes_without_replacing_legacy_docs() -> None:
    pointer = (REPO_ROOT / "docs" / "Dex_System" / "README.md").read_text(encoding="utf-8")

    assert "06-Resources/Dex_System/" in pointer
    assert "docs/Dex_System/" in pointer
    assert "temporary bridge" in pointer.lower()
    assert (REPO_ROOT / "06-Resources" / "Dex_System" / "README.md").is_file()


def test_docs_bridge_is_brain_owned_by_the_existing_docs_directory_rule() -> None:
    for filename in (*BRIDGE_GUIDES, "README.md"):
        resolution = portable_contract.resolve(f"docs/Dex_System/{filename}")
        assert resolution.ownership == "brain"
        assert resolution.rule_id == "brain-docs"
