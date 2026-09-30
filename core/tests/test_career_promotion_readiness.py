"""Promotion-readiness score must use real career readers, not dummy points."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from core.mcp import career_server

REPO_ROOT = Path(__file__).resolve().parents[2]
CAREER_COACH = (
    REPO_ROOT
    / ".claude/skills/_available/capabilities/career/skills/career-coach/SKILL.md"
)

STRUCTURED_LADDER = """# Career Ladder

**Company:** Acme
**Current Level:** PM
**Target Level:** Senior PM
**Last Updated:** 2026-08-01

---

## Career Framework

Company ladder used by career-setup.

---

## Current Level: PM

**Expectations:**
- Ship assigned features

---

## Target Level: Senior PM

**Requirements for Promotion:**

### Product Strategy
- Set multi-quarter product direction
- Align the roadmap to company outcomes

### Technical Depth
- Lead a system design review
- Debug a production incident

### Stakeholder Leadership
- Influence without authority
- Run an exec review
"""

COMPETENCY_HEADINGS = [
    "Product Strategy",
    "Technical Depth",
    "Stakeholder Leadership",
]


def _decode(result) -> dict:
    return json.loads(result[0].text)


def _enable_career_room(tmp_path: Path, monkeypatch) -> Path:
    vault = tmp_path / "vault"
    career_dir = vault / "05-Areas" / "Career"
    evidence_dir = career_dir / "Evidence"
    ladder_file = career_dir / "Career_Ladder.md"
    profile_file = vault / "System" / "user-profile.yaml"
    profile_file.parent.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    profile_file.write_text(
        "capabilities:\n  career:\n    enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(career_server, "BASE_DIR", vault)
    monkeypatch.setattr(career_server, "CAREER_DIR", career_dir)
    monkeypatch.setattr(career_server, "EVIDENCE_DIR", evidence_dir)
    monkeypatch.setattr(career_server, "LADDER_FILE", ladder_file)
    monkeypatch.setattr(career_server, "USER_PROFILE_FILE", profile_file)
    return vault


def _write_evidence(path: Path, title: str) -> None:
    path.write_text(
        f"# {title}\n\n**Category:** Achievements\n\nA captured career win.\n",
        encoding="utf-8",
    )


def _write_mapped_evidence(path: Path, title: str, competency: str) -> None:
    path.write_text(
        f"# {title}\n\n"
        "**Category:** Achievements\n\n"
        "## Skills Demonstrated\n"
        f"- {competency}\n\n"
        "## Ladder Alignment\n\n"
        f"**Maps to:** {competency}\n",
        encoding="utf-8",
    )


def _score(arguments: dict | None = None) -> dict:
    return _decode(
        asyncio.run(
            career_server.handle_call_tool(
                "promotion_readiness_score",
                arguments or {"time_in_role_months": 3},
            )
        )
    )


def _skills_gap(arguments: dict | None = None) -> dict:
    return _decode(
        asyncio.run(
            career_server.handle_call_tool(
                "skills_gap_analysis",
                arguments or {"target_level": "Senior PM"},
            )
        )
    )


def _parse_ladder() -> dict:
    return _decode(
        asyncio.run(career_server.handle_call_tool("parse_ladder", {}))
    )


def _required_skill_names(payload: dict) -> list[str]:
    return (
        list(payload.get("skills_gap") or [])
        + [item["skill"] for item in payload.get("actively_developed") or []]
        + [item["skill"] for item in payload.get("stale_skills") or []]
    )


def test_promotion_score_does_not_invent_skills_points_when_ladder_is_empty(
    tmp_path, monkeypatch
):
    _enable_career_room(tmp_path, monkeypatch)

    payload = _score()
    skills = payload["score_breakdown"]["skills_coverage"]

    assert skills["score"] != 15
    assert skills["score"] == 0
    assert skills["max"] == 25


def test_promotion_score_does_not_invent_growth_velocity_when_evidence_is_empty(
    tmp_path, monkeypatch
):
    _enable_career_room(tmp_path, monkeypatch)

    payload = _score()
    velocity = payload["score_breakdown"]["growth_velocity"]

    assert velocity["score"] != 5
    assert velocity["score"] == 0
    assert velocity["max"] == 10


def test_promotion_score_counts_evidence_files_sitting_in_the_evidence_folder(
    tmp_path, monkeypatch
):
    vault = _enable_career_room(tmp_path, monkeypatch)
    evidence_dir = vault / "05-Areas" / "Career" / "Evidence"
    _write_evidence(evidence_dir / "2026-01-10 - Led API migration.md", "Led API migration")
    _write_evidence(evidence_dir / "2026-03-04 - Ran exec review.md", "Ran exec review")
    _write_evidence(evidence_dir / "2026-06-18 - Closed churn gap.md", "Closed churn gap")
    (evidence_dir / "README.md").write_text("# Career Evidence\n", encoding="utf-8")

    payload = _score()
    coverage = payload["score_breakdown"]["evidence_coverage"]

    assert coverage["evidence_count"] == 3
    assert coverage["score"] == 3


def test_promotion_score_uses_real_coverage_for_a_populated_skills_folder(
    tmp_path, monkeypatch
):
    vault = _enable_career_room(tmp_path, monkeypatch)
    career_dir = vault / "05-Areas" / "Career"
    evidence_dir = career_dir / "Evidence"
    (career_dir / "Career_Ladder.md").write_text(STRUCTURED_LADDER, encoding="utf-8")
    _write_mapped_evidence(
        evidence_dir / "2026-01-10 - Strategy memo.md",
        "Strategy memo",
        "Product Strategy",
    )
    _write_mapped_evidence(
        evidence_dir / "2026-02-11 - Design review.md",
        "Design review",
        "Technical Depth",
    )
    _write_mapped_evidence(
        evidence_dir / "2026-03-12 - Exec review.md",
        "Exec review",
        "Stakeholder Leadership",
    )

    payload = _score()
    skills = payload["score_breakdown"]["skills_coverage"]

    # One matching file per competency is "weak" coverage: 0.3 * 25 = 8.
    # A leftover placeholder would still return 15 here.
    assert skills["score"] != 15
    assert skills["score"] == 8
    assert skills["required_competencies"] == 3
    assert skills["coverage"] == {"weak": 3}


def test_skills_gap_reads_a_career_setup_ladder_with_competency_subheadings(
    tmp_path, monkeypatch
):
    vault = _enable_career_room(tmp_path, monkeypatch)
    ladder = vault / "05-Areas" / "Career" / "Career_Ladder.md"
    ladder.write_text(STRUCTURED_LADDER, encoding="utf-8")

    payload = _skills_gap()

    assert payload["required_skills_count"] == 3
    assert payload["success"] is True
    assert _required_skill_names(payload) == COMPETENCY_HEADINGS


def test_skills_gap_and_parse_ladder_agree_on_heading_names(
    tmp_path, monkeypatch
):
    vault = _enable_career_room(tmp_path, monkeypatch)
    ladder = vault / "05-Areas" / "Career" / "Career_Ladder.md"
    ladder.write_text(STRUCTURED_LADDER, encoding="utf-8")

    gap = _skills_gap()
    parsed = _parse_ladder()

    assert parsed["success"] is True
    assert parsed["target_level"] == "Senior PM"
    assert [item["category"] for item in parsed["competencies"]] == COMPETENCY_HEADINGS
    assert _required_skill_names(gap) == [
        item["category"] for item in parsed["competencies"]
    ]


def test_skills_gap_reads_structured_target_level_even_when_metadata_differs(
    tmp_path, monkeypatch
):
    vault = _enable_career_room(tmp_path, monkeypatch)
    ladder = vault / "05-Areas" / "Career" / "Career_Ladder.md"
    # Metadata names a different level than the structured section the caller asks for.
    ladder.write_text(
        STRUCTURED_LADDER.replace("**Target Level:** Senior PM", "**Target Level:** L5"),
        encoding="utf-8",
    )

    payload = _skills_gap({"target_level": "Senior PM"})

    assert payload["required_skills_count"] != 0
    assert payload["required_skills_count"] == 3
    assert payload["required_skills"] == COMPETENCY_HEADINGS
    assert _required_skill_names(payload) == COMPETENCY_HEADINGS


def test_career_coach_live_path_must_call_score_and_gap_tools() -> None:
    text = CAREER_COACH.read_text(encoding="utf-8")

    assert "promotion_readiness_score" in text
    assert "skills_gap_analysis" in text
    assert "never invent" in text.lower() or "do not invent" in text.lower()


def test_download_path_vault_path_uses_real_evidence_not_dummy_15(tmp_path) -> None:
    """The public folder install launches career_server with VAULT_PATH set.

    Monkeypatching module globals is not that path. A fresh interpreter must
    still count Evidence-folder files, refuse the dummy 15, and read a
    structured target level.
    """
    vault = tmp_path / "vault"
    career_dir = vault / "05-Areas" / "Career"
    evidence_dir = career_dir / "Evidence"
    profile = vault / "System" / "user-profile.yaml"
    evidence_dir.mkdir(parents=True)
    profile.parent.mkdir(parents=True)
    profile.write_text("capabilities:\n  career:\n    enabled: true\n", encoding="utf-8")
    (career_dir / "Career_Ladder.md").write_text(STRUCTURED_LADDER, encoding="utf-8")
    for name, competency in (
        ("2026-01-10 - Strategy memo.md", "Product Strategy"),
        ("2026-02-11 - Design review.md", "Technical Depth"),
        ("2026-03-12 - Exec review.md", "Stakeholder Leadership"),
    ):
        (evidence_dir / name).write_text(
            f"# {name}\n\n"
            "**Category:** Achievements\n\n"
            "## Skills Demonstrated\n"
            f"- {competency}\n\n"
            "## Ladder Alignment\n\n"
            f"**Maps to:** {competency}\n",
            encoding="utf-8",
        )
    (evidence_dir / "README.md").write_text("# Career Evidence\n", encoding="utf-8")

    script = r"""
import asyncio, json, sys
from core.mcp import career_server

def decode(result):
    return json.loads(result[0].text)

score = decode(asyncio.run(career_server.handle_call_tool(
    "promotion_readiness_score", {"time_in_role_months": 3, "target_level": "Senior PM"}
)))
gap = decode(asyncio.run(career_server.handle_call_tool(
    "skills_gap_analysis", {"target_level": "Senior PM"}
)))
print(json.dumps({"score": score, "gap": gap}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env={**os.environ, "VAULT_PATH": str(vault)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    skills = payload["score"]["score_breakdown"]["skills_coverage"]
    evidence = payload["score"]["score_breakdown"]["evidence_coverage"]
    gap = payload["gap"]

    assert evidence["evidence_count"] == 3
    assert skills["score"] != 15
    assert skills["score"] == 8
    assert gap["required_skills_count"] == 3
    assert gap["required_skills"] == COMPETENCY_HEADINGS
