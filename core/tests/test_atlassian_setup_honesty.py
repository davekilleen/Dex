"""Atlassian setup must not promise skill surfaces those skills do not show."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / ".claude" / "skills" / "atlassian-setup" / "SKILL.md"
CATALOG = REPO_ROOT / ".claude" / "skills" / "README.md"
DAILY_PLAN = REPO_ROOT / ".claude" / "skills" / "daily-plan" / "SKILL.md"
PROJECT_HEALTH = REPO_ROOT / ".claude" / "skills" / "project-health" / "SKILL.md"
MEETING_PREP = REPO_ROOT / ".claude" / "skills" / "meeting-prep" / "SKILL.md"
WEEK_REVIEW = REPO_ROOT / ".claude" / "skills" / "week-review" / "SKILL.md"
TRIAGE = REPO_ROOT / ".claude" / "skills" / "triage" / "SKILL.md"

OVERCLAIM_PHRASES = (
    "shows Jira sprint status and assigned tickets",
    "includes sprint velocity and blocked tickets",
    "surfaces Jira tickets and Confluence docs for attendees",
    "includes tickets closed and sprint progress",
    "these skills automatically gain new powers",
    "Jira tickets and Confluence docs in daily plans",
)


def test_named_skills_do_not_mention_jira_or_confluence() -> None:
    for path in (DAILY_PLAN, PROJECT_HEALTH, MEETING_PREP, WEEK_REVIEW, TRIAGE):
        text = path.read_text(encoding="utf-8").casefold()
        assert "jira" not in text
        assert "confluence" not in text
        assert "atlassian" not in text


def test_atlassian_setup_does_not_overclaim_those_skills() -> None:
    text = SKILL.read_text(encoding="utf-8")
    lowered = text.casefold()
    for phrase in OVERCLAIM_PHRASES:
        assert phrase not in lowered
    assert "do not currently add sprint status" in lowered
    assert "do not automatically show sprint status" in lowered
    assert "ask if you want that looked up" in lowered
    assert "Jira tickets and Confluence docs in daily plans" not in CATALOG.read_text(
        encoding="utf-8"
    )
