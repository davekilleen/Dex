"""career-mcp score and gap tools must compute or fail honestly.

Locks #539 on the path the public folder actually runs (VAULT_PATH +
career_server.py). Does not touch test_career_promotion_readiness.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from core.mcp import career_server

REPO_ROOT = Path(__file__).resolve().parents[2]

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

UNREADABLE_LADDER = """# Career Ladder

**Company:** Acme
**Current Level:** PM
**Target Level:** Senior PM

## Current Level: PM

- Ship assigned features
"""


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
                arguments or {"time_in_role_months": 3, "target_level": "Senior PM"},
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


def _write_download_vault(tmp_path: Path, *, ladder: str | None = None) -> Path:
    vault = tmp_path / "vault"
    career_dir = vault / "05-Areas" / "Career"
    evidence_dir = career_dir / "Evidence"
    profile = vault / "System" / "user-profile.yaml"
    evidence_dir.mkdir(parents=True)
    profile.parent.mkdir(parents=True)
    profile.write_text("capabilities:\n  career:\n    enabled: true\n", encoding="utf-8")
    if ladder is not None:
        (career_dir / "Career_Ladder.md").write_text(ladder, encoding="utf-8")
    return vault


def _run_on_download_path(vault: Path) -> dict:
    """Score and gap as the public folder launch does: VAULT_PATH, no monkeypatch."""
    script = r"""
import asyncio, json
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
    return json.loads(result.stdout)


def test_well_formed_ladder_and_evidence_return_computed_score_not_dummy_15(
    tmp_path, monkeypatch
):
    vault = _enable_career_room(tmp_path, monkeypatch)
    career_dir = vault / "05-Areas" / "Career"
    evidence_dir = career_dir / "Evidence"
    (career_dir / "Career_Ladder.md").write_text(STRUCTURED_LADDER, encoding="utf-8")
    for name, competency in (
        ("2026-01-10 - Strategy memo.md", "Product Strategy"),
        ("2026-02-11 - Design review.md", "Technical Depth"),
        ("2026-03-12 - Exec review.md", "Stakeholder Leadership"),
    ):
        _write_mapped_evidence(evidence_dir / name, name, competency)

    payload = _score()
    skills = payload["score_breakdown"]["skills_coverage"]
    evidence = payload["score_breakdown"]["evidence_coverage"]

    assert payload["success"] is True
    assert "feature_status" not in payload or payload.get("feature_status") == "ok"
    assert evidence["evidence_count"] == 3
    assert skills["score"] != 15
    assert skills["score"] == 8
    assert skills["required_competencies"] == 3


def test_skills_gap_returns_structured_target_level_skills(tmp_path, monkeypatch):
    vault = _enable_career_room(tmp_path, monkeypatch)
    (vault / "05-Areas" / "Career" / "Career_Ladder.md").write_text(
        STRUCTURED_LADDER, encoding="utf-8"
    )

    payload = _skills_gap()

    assert payload["success"] is True
    assert payload["required_skills_count"] == 3
    assert payload["required_skills"] == COMPETENCY_HEADINGS


def test_target_level_argument_reads_structured_section_when_metadata_differs(
    tmp_path, monkeypatch
):
    vault = _enable_career_room(tmp_path, monkeypatch)
    ladder = vault / "05-Areas" / "Career" / "Career_Ladder.md"
    ladder.write_text(
        STRUCTURED_LADDER.replace("**Target Level:** Senior PM", "**Target Level:** L5"),
        encoding="utf-8",
    )

    gap = _skills_gap({"target_level": "Senior PM"})
    score = _score({"time_in_role_months": 3, "target_level": "Senior PM"})

    assert gap["success"] is True
    assert gap["required_skills_count"] == 3
    assert gap["required_skills"] == COMPETENCY_HEADINGS
    assert score["success"] is True
    assert score["score_breakdown"]["skills_coverage"]["required_competencies"] == 3
    assert score["score_breakdown"]["skills_coverage"]["score"] != 15


def test_unreadable_existing_ladder_is_a_visible_honest_fail(tmp_path, monkeypatch):
    vault = _enable_career_room(tmp_path, monkeypatch)
    (vault / "05-Areas" / "Career" / "Career_Ladder.md").write_text(
        UNREADABLE_LADDER, encoding="utf-8"
    )

    score = _score()
    gap = _skills_gap()

    for payload in (score, gap):
        assert payload["success"] is False
        assert payload["feature_status"] == "broken"
        assert payload["user_message"]
        assert "15" not in payload["user_message"]
        assert "score_breakdown" not in payload or "dummy" not in json.dumps(payload)


def test_download_path_computes_real_score_or_honest_fail(tmp_path):
    vault = _write_download_vault(tmp_path, ladder=STRUCTURED_LADDER)
    evidence_dir = vault / "05-Areas" / "Career" / "Evidence"
    for name, competency in (
        ("2026-01-10 - Strategy memo.md", "Product Strategy"),
        ("2026-02-11 - Design review.md", "Technical Depth"),
        ("2026-03-12 - Exec review.md", "Stakeholder Leadership"),
    ):
        _write_mapped_evidence(evidence_dir / name, name, competency)

    payload = _run_on_download_path(vault)
    skills = payload["score"]["score_breakdown"]["skills_coverage"]
    evidence = payload["score"]["score_breakdown"]["evidence_coverage"]
    gap = payload["gap"]

    assert payload["score"]["success"] is True
    assert evidence["evidence_count"] == 3
    assert skills["score"] != 15
    assert skills["score"] == 8
    assert gap["success"] is True
    assert gap["required_skills_count"] == 3
    assert gap["required_skills"] == COMPETENCY_HEADINGS


def test_download_path_honest_fail_when_ladder_cannot_be_read(tmp_path):
    vault = _write_download_vault(tmp_path, ladder=UNREADABLE_LADDER)
    payload = _run_on_download_path(vault)

    assert payload["score"]["success"] is False
    assert payload["score"]["feature_status"] == "broken"
    assert payload["score"]["user_message"]
    assert payload["gap"]["success"] is False
    assert payload["gap"]["feature_status"] == "broken"
    assert "15" not in json.dumps(payload)
