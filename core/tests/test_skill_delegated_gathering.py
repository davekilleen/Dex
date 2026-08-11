"""Keep each heavy skill's SKILL.md and AGENT_INSTRUCTIONS.md paired.

Heavy skills delegate their bulk read-gathering to a subagent whose prompt
lives in AGENT_INSTRUCTIONS.md beside the SKILL.md. The pair only works while
both halves exist and SKILL.md still points at its instructions file, so a
future edit must not silently orphan either side.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / ".claude" / "skills"

# Skills that read across three or more independent sources, or an unbounded
# collection, and therefore delegate gathering (see each skill's
# "Delegated gathering" section).
HEAVY_SKILLS = (
    "daily-plan",
    "daily-review",
    "meeting-prep",
    "process-meetings",
    "week-review",
)


@pytest.mark.parametrize("skill_name", HEAVY_SKILLS)
def test_heavy_skill_ships_agent_instructions(skill_name: str) -> None:
    instructions = SKILLS_ROOT / skill_name / "AGENT_INSTRUCTIONS.md"

    assert instructions.is_file(), (
        f"{skill_name} is a heavy skill but ships no AGENT_INSTRUCTIONS.md; "
        "its delegated gathering (and the inline fallback, which runs the "
        "same file) has nothing to execute."
    )
    assert instructions.read_text(encoding="utf-8").strip(), (
        f"{skill_name}/AGENT_INSTRUCTIONS.md exists but is empty."
    )


@pytest.mark.parametrize("skill_name", HEAVY_SKILLS)
def test_heavy_skill_references_its_agent_instructions(skill_name: str) -> None:
    skill_path = SKILLS_ROOT / skill_name / "SKILL.md"
    body = skill_path.read_text(encoding="utf-8").split("---", 2)[-1]

    assert "AGENT_INSTRUCTIONS.md" in body, (
        f"{skill_name}/SKILL.md never mentions AGENT_INSTRUCTIONS.md, so the "
        "delegated gathering prompt beside it is orphaned and will drift."
    )
    assert f".claude/skills/{skill_name}/AGENT_INSTRUCTIONS.md" in body, (
        f"{skill_name}/SKILL.md must reference its own instructions file by "
        f"path (.claude/skills/{skill_name}/AGENT_INSTRUCTIONS.md) so the "
        "skill reads the right prompt rather than another skill's."
    )


def test_no_orphaned_agent_instructions() -> None:
    """Every shipped AGENT_INSTRUCTIONS.md belongs to a SKILL.md that uses it."""
    orphans = []
    for instructions in sorted(SKILLS_ROOT.glob("*/AGENT_INSTRUCTIONS.md")):
        skill_path = instructions.parent / "SKILL.md"
        if not skill_path.is_file():
            orphans.append(instructions)
            continue
        if "AGENT_INSTRUCTIONS.md" not in skill_path.read_text(encoding="utf-8"):
            orphans.append(instructions)

    assert not orphans, (
        "AGENT_INSTRUCTIONS.md files whose SKILL.md never references them: "
        + ", ".join(str(path.relative_to(REPO_ROOT)) for path in orphans)
    )
