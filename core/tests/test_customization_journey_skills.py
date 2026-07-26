"""Shipped instruction guards for the scoped customization journey."""

from __future__ import annotations

from pathlib import Path

from core.update.apply_update import _compose_claude

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_shipped_skills_pin_the_scoped_customization_journey() -> None:
    doctor_skill = (
        REPO_ROOT / ".claude/skills/dex-doctor/SKILL.md"
    ).read_text(encoding="utf-8")
    doctor_section = doctor_skill.split(
        "### Step 3c: Render the customization migration status",
        1,
    )[1].split("### Step 4:", 1)[0]
    for authority_field in (
        "capsule_id",
        "state",
        "validation.status",
        "validation.mismatches",
        "pending",
    ):
        assert f"`{authority_field}`" in doctor_section
    assert (
        "Continue via the registered Customization Migration MCP status tool / "
        "`/dex-update`; never edit capsule files directly."
    ) in doctor_section
    assert "preserved evidence cannot be verified" in " ".join(
        doctor_section.lower().split()
    )

    update_skill = (
        REPO_ROOT / ".claude/skills/dex-update/SKILL.md"
    ).read_text(encoding="utf-8")
    update_section = update_skill.split(
        "## Deeply customised setup",
        1,
    )[1].split("## Five-group preview", 1)[0]
    assert (
        "`customization_assessment.identity.customization_count` is at least 1"
        in update_section
    )
    assert "python -m core.customization_migration.cli preview" in update_section
    assert (
        "python -m core.customization_migration.cli create "
        "--confirm-token <preview_sha256>"
    ) in update_section
    assert "Create this exact snapshot?" in update_section
    assert "capsule_id" in update_section
    assert "file_count" in update_section
    assert "byte_count" in update_section
    assert "transaction_id" in update_section
    assert "migration_status_to_dict" in update_section
    assert "update-replaceable-location" in update_section
    assert "update-untouched-location" in update_section
    assert "python -m core.customization_migration.cli abandon" in update_section
    assert "--acknowledge" in update_section
    assert "Capsule creation is resumable after a crash." in update_section
    assert "MCP tools are read-only" in update_section
    assert "automatic rebuild" in update_section
    for unavailable_call in (
        "stage_approved_regeneration",
        "verify_staged_regeneration",
        "activate_approved_customizations",
        "rewind_customization_activation",
    ):
        assert unavailable_call not in update_section


def test_session_continuity_survives_claude_template_composition(
    tmp_path: Path,
) -> None:
    template = (REPO_ROOT / "CLAUDE.md").read_bytes()
    invariant = (
        "If Doctor reports a pending customization migration, continue through "
        "the registered Customization Migration MCP status tool / `/dex-update`. "
        "Do not search for or edit capsule files directly."
    )
    source = template.decode("utf-8")
    extension_start = source.index("## USER_EXTENSIONS_START")
    extension_end = source.index("## USER_EXTENSIONS_END")
    normalized_source = " ".join(source.split())
    invariant_position = normalized_source.index(invariant)

    assert invariant_position > normalized_source.index("### Release Awareness")
    assert invariant not in source[extension_start:extension_end]

    vault = tmp_path / "composed-vault"
    vault.mkdir()
    (vault / "CLAUDE-custom.md").write_text(
        "## USER_EXTENSIONS_START\nPersonal instructions.\n"
        "## USER_EXTENSIONS_END\n",
        encoding="utf-8",
    )
    composed = _compose_claude(template, vault).decode("utf-8")

    assert invariant in " ".join(composed.split())
    assert "Personal instructions." in composed
