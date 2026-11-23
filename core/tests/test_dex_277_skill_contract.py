"""Instruction contract for the DEX-277 leftover-repair journey."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_doctor_verified_branch_offers_tidy_and_never_dead_ends() -> None:
    skill = _read(".claude/skills/dex-doctor/SKILL.md")
    section = skill.split("#### Offering the release re-anchoring repair", 1)[1].split(
        "### Step 3c:", 1
    )[0]
    verified = section.split("`verified`")[1].split("`rejected` because")[0]

    assert "python3 -m core.customization_migration.cli tidy-dev-leftovers --dry-run" in verified
    assert "--confirm-token" in verified
    assert "nothing to offer" not in verified.lower()
    assert "wait before updating" in verified
    assert "keep them as the user's own files" in verified
    assert "FOUNDER COPY - DRAFT PENDING APPROVAL" in section


def test_dex_update_deep_branch_offers_tidy_or_normal_update() -> None:
    skill = _read(".claude/skills/dex-update/SKILL.md")
    section = skill.split("## Deeply customised setup", 1)[1].split(
        "### Detect and explain", 1
    )[0]

    assert "python3 -m core.customization_migration.cli tidy-dev-leftovers --dry-run" in section
    assert "normal update path" in section
    assert "Never end with \"don't update\" and no next step." in section
    assert "FOUNDER COPY - DRAFT PENDING APPROVAL" in section
    assert "<" not in section
    assert ">=" not in section
