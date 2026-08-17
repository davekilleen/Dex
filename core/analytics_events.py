"""The finite, non-user-controlled names Dex may use for analytics attempts."""

from __future__ import annotations

# These names describe Dex features, never a person, their work, or an input
# supplied through an MCP call. Keep this list deliberately closed: a new
# feature must make its event name an explicit code-review decision.
SAFE_ANALYTICS_EVENT_NAMES = frozenset(
    {
        "backlog_reviewed",
        "career_coach_session",
        "career_coverage_analyzed",
        "career_evidence_scanned",
        "career_setup_completed",
        "commitments_reviewed",
        "custom_skill_created",
        "daily_plan_completed",
        "daily_review_completed",
        "dex_analytics_test",
        "getting_started_completed",
        "idea_captured",
        "idea_implemented",
        "improvement_workshopped",
        "initiative_kicked_off",
        "insight_saved",
        "integration_google_completed",
        "integration_notion_completed",
        "integration_slack_completed",
        "journal_entry_created",
        "level_up_viewed",
        "mcp_added",
        "mcp_created",
        "mcp_integrated",
        "meeting_closed_out",
        "meeting_prep_completed",
        "meeting_processed",
        "obsidian_enabled",
        "onboarding_completed",
        "person_page_created",
        "promotion_readiness_checked",
        "product_brief_created",
        "project_health_checked",
        "prompt_improved",
        "quarter_plan_completed",
        "quarter_review_completed",
        "relationship_radar_run",
        "resume_compiled",
        "resume_builder_used",
        "session_started",
        "skill_rated",
        "task_completed",
        "task_created",
        "triage_completed",
        "user_identified",
        "vault_reset",
        "week_plan_completed",
        "week_review_completed",
        "whats_new_viewed",
        "xray_used",
    }
)

# An invalid caller-supplied name is represented locally by this fixed marker,
# never by the original value.
REDACTED_ANALYTICS_EVENT_NAME = "invalid_event"
RECEIPT_ANALYTICS_EVENT_NAMES = SAFE_ANALYTICS_EVENT_NAMES | {
    REDACTED_ANALYTICS_EVENT_NAME,
}


def is_safe_analytics_event_name(value: object) -> bool:
    """True only for an explicitly reviewed, non-user-controlled event name."""
    return isinstance(value, str) and value in SAFE_ANALYTICS_EVENT_NAMES


__all__ = [
    "RECEIPT_ANALYTICS_EVENT_NAMES",
    "REDACTED_ANALYTICS_EVENT_NAME",
    "SAFE_ANALYTICS_EVENT_NAMES",
    "is_safe_analytics_event_name",
]
