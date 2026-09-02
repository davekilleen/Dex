"""Discovery gates for Dex Lens skill capabilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.lens_catalog_discovery import LensDiscoveryError, discover_active_skills

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_skill(root: Path, skill_id: str, *, name: str | None = None, description: str = "Useful work.") -> Path:
    path = root / ".claude" / "skills" / skill_id / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'---\nname: {name or skill_id}\ndescription: "{description}"\n---\n\n# Skill\n',
        encoding="utf-8",
    )
    return path


def test_shipped_release_has_exactly_66_active_first_party_skills() -> None:
    candidates = discover_active_skills(REPO_ROOT)

    assert len(candidates) == 66
    assert tuple(candidate.capability_id for candidate in candidates) == tuple(
        sorted(candidate.capability_id for candidate in candidates)
    )
    assert all(candidate.source_path == f".claude/skills/{candidate.capability_id}/SKILL.md" for candidate in candidates)
    assert all(not candidate.capability_id.startswith("anthropic-") for candidate in candidates)
    assert all("/_available/" not in candidate.source_path for candidate in candidates)
    assert {"dex-orient", "getting-started", "process-meetings"} <= {
        candidate.capability_id for candidate in candidates
    }


def test_discovery_uses_only_direct_first_party_children(tmp_path: Path) -> None:
    _write_skill(tmp_path, "zeta", description="Do zeta work.")
    _write_skill(tmp_path, "alpha", description="Do alpha work.")
    _write_skill(tmp_path, "anthropic-pdf")
    _write_skill(tmp_path / ".claude/skills/_available", "dormant")

    candidates = discover_active_skills(tmp_path)

    assert [(candidate.capability_id, candidate.name, candidate.description) for candidate in candidates] == [
        ("alpha", "alpha", "Do alpha work."),
        ("zeta", "zeta", "Do zeta work."),
    ]


@pytest.mark.parametrize(
    ("skill_id", "content", "message"),
    [
        ("missing-frontmatter", "# Skill\n", "has no frontmatter"),
        ("missing-name", "---\ndescription: Useful.\n---\n", "has no name"),
        ("missing-description", "---\nname: missing-description\n---\n", "has no description"),
        ("wrong-name", "---\nname: another-name\ndescription: Useful.\n---\n", "does not match its directory"),
    ],
)
def test_discovery_rejects_malformed_frontmatter(
    tmp_path: Path,
    skill_id: str,
    content: str,
    message: str,
) -> None:
    path = tmp_path / ".claude" / "skills" / skill_id / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")

    with pytest.raises(LensDiscoveryError, match=message):
        discover_active_skills(tmp_path)


def test_discovery_rejects_symlinked_skill_payload(tmp_path: Path) -> None:
    target = tmp_path / "outside.md"
    target.write_text("---\nname: linked\ndescription: Useful.\n---\n", encoding="utf-8")
    link = tmp_path / ".claude" / "skills" / "linked" / "SKILL.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)

    with pytest.raises(LensDiscoveryError, match="not a regular file"):
        discover_active_skills(tmp_path)


def test_discovery_rejects_symlinked_first_party_skill_directory(tmp_path: Path) -> None:
    target = tmp_path / "outside-skill"
    target.mkdir()
    (target / "SKILL.md").write_text(
        "---\nname: linked\ndescription: Useful.\n---\n",
        encoding="utf-8",
    )
    skills_root = tmp_path / ".claude" / "skills"
    skills_root.mkdir(parents=True)
    (skills_root / "linked").symlink_to(target, target_is_directory=True)

    with pytest.raises(LensDiscoveryError, match="skill directory is missing or unsafe"):
        discover_active_skills(tmp_path)
