"""Skill-disable guidance must match Claude Code's /skills and /skill-doctor."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CREATE_SKILL = REPO_ROOT / ".claude" / "skills" / "create-skill" / "SKILL.md"
DEX_DOCTOR = REPO_ROOT / ".claude" / "skills" / "dex-doctor" / "SKILL.md"
STANDARD = (
    REPO_ROOT / ".claude" / "skills" / "create-skill" / "references" / "dex-skill-standard.md"
)


def _texts() -> tuple[str, ...]:
    return (
        CREATE_SKILL.read_text(encoding="utf-8"),
        DEX_DOCTOR.read_text(encoding="utf-8"),
        STANDARD.read_text(encoding="utf-8"),
    )


def test_disable_guidance_names_skill_overrides_and_skill_doctor() -> None:
    create_skill, dex_doctor, standard = _texts()
    for text in (create_skill, dex_doctor, standard):
        assert "skillOverrides" in text
        assert "/skill-doctor" in text
        assert "disabledSkills" in text

    assert "open /skills, highlight it, press Space until it is off" in create_skill
    assert "open `/skills`, highlight the skill, press Space until it is **off**" in dex_doctor
    assert "turn them off from `/plugin`" in dex_doctor
    assert "`skillOverrides` does not apply" in dex_doctor
    assert "Claude Code does not load that folder" in dex_doctor


def test_disable_guidance_never_treats_disabled_skills_as_a_real_setting() -> None:
    for text in _texts():
        lowered = " ".join(text.casefold().split())
        assert "write disabledskills" not in lowered
        assert "does not honor" in lowered or "does not honor that key" in text
