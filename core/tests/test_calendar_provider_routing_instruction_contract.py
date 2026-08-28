"""Instruction-contract checks for calendar.provider routing.

These workflows are prompt-driven, so this suite checks the shipped instructions
at the files that actually choose a calendar source. It does not execute an LLM.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DAILY_SKILL = REPO_ROOT / ".claude/skills/daily-plan/SKILL.md"
DAILY_AGENT = REPO_ROOT / ".claude/skills/daily-plan/AGENT_INSTRUCTIONS.md"
WEEK_PLAN = REPO_ROOT / ".claude/skills/week-plan/SKILL.md"
WEEK_REVIEW_SKILL = REPO_ROOT / ".claude/skills/week-review/SKILL.md"
WEEK_REVIEW_AGENT = REPO_ROOT / ".claude/skills/week-review/AGENT_INSTRUCTIONS.md"
GOOGLE_SETUP = REPO_ROOT / ".claude/skills/google-workspace-setup/SKILL.md"
DOCTOR_SKILL = REPO_ROOT / ".claude/skills/dex-doctor/SKILL.md"
ROUTING_FILES = {
    "daily-plan skill": DAILY_SKILL,
    "daily-plan agent": DAILY_AGENT,
    "week-plan": WEEK_PLAN,
    "week-review skill": WEEK_REVIEW_SKILL,
    "week-review agent": WEEK_REVIEW_AGENT,
}


def test_planning_skills_read_calendar_provider_before_calendar_calls() -> None:
    for label, path in ROUTING_FILES.items():
        body = path.read_text(encoding="utf-8")
        assert "calendar.provider" in body, f"{label} never reads calendar.provider"
        assert "calendar_get_" in body, f"{label} dropped the Apple Calendar path"
        assert "google-workspace-mcp" in body or "Google Workspace MCP" in body, (
            f"{label} has no Google Calendar path"
        )
        assert "list_calendars" in body, f"{label} Google path never lists calendars"
        assert "get_events" in body, f"{label} Google path never reads events"
        if path in {DAILY_SKILL, WEEK_REVIEW_SKILL}:
            continue
        assert "Do not invent new privacy or consent language" in body, (
            f"{label} is missing the no-new-copy guard"
        )
        assert "/google-workspace-setup" in body, f"{label} dropped the existing setup path"


def test_google_calendar_path_does_not_call_eventkit_event_tools() -> None:
    for path in (DAILY_AGENT, WEEK_PLAN, WEEK_REVIEW_AGENT):
        body = path.read_text(encoding="utf-8")
        google_section = body.split("**If `provider` is `google`:**", 1)[1]
        google_section = google_section.split("**If `provider` is `none`:**", 1)[0]
        assert "Use: list_calendars" in google_section
        assert "Use: get_events" in google_section
        assert "Use: calendar_list_calendars" not in google_section
        assert "Use: calendar_get_events" not in google_section
        assert "calendar_id" in google_section
        assert "work_calendar" in google_section
        assert "max_results=2500" in google_section
        assert "display name" in google_section
        assert "single_events" not in google_section
        assert "singleEvents" not in google_section
        assert "calendar_get_today" not in google_section
        assert "calendar_get_events_with_attendees" not in google_section
        assert "calendar-mcp event tools" in google_section


def test_google_workspace_setup_records_google_calendar_provider() -> None:
    body = GOOGLE_SETUP.read_text(encoding="utf-8")
    assert "provider: google" in body
    assert "calendar.provider" in body
    assert "If `calendar.provider` is already `apple`, leave it" in body
    assert "If `calendar.provider` is missing and `work_calendar` is set, leave it" in body
    assert "Gmail-only connection must not change the calendar source" in body
    assert "System/user-profile.yaml" in body
    assert "not in `System/integrations/config.yaml`" in body


def test_doctor_skill_does_not_treat_calendar_as_eventkit_only() -> None:
    body = DOCTOR_SKILL.read_text(encoding="utf-8")
    assert "Calendar via the configured" in body
    assert "Google Calendar is still checked" in body
    assert "/google-workspace-setup" in body
    assert "Calendar via EventKit" not in body
