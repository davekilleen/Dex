"""Regression contracts for user-facing instruction honesty."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.integrations import post_update_check
from core.integrations.google import setup as google_setup
from core.integrations.notion import setup as notion_setup
from core.integrations.slack import setup as slack_setup
from core.mcp import analytics_helper
from core.utils import dex_logger

REPO_ROOT = Path(__file__).resolve().parents[2]

RETIRED_PI_ARTIFACTS = (
    ".claude/skills/ai-setup",
    ".claude/skills/ai-status",
    ".agents/skills/ai-setup",
    ".agents/skills/ai-status",
    "06-Resources/Dex_System/AI_Model_Options.md",
    "System/scripts/check-system-for-ai.sh",
    "System/scripts/configure-ai-models.sh",
    "System/scripts/test-ai-connections.sh",
)

PARKED_OR_DEV_ONLY_ARTIFACTS = (
    "docs/ritual-intelligence-beta-rollout.md",
    ".scripts/compare-api-vs-cache.py",
    ".scripts/test-granola-api.py",
    ".scripts/test-granola-api-historical.py",
    ".scripts/test-recent-wider.py",
    ".scripts/test-updated-mcp.py",
    ".scripts/test-updated-mcp-debug.py",
    ".scripts/lib/test-llm-client.cjs",
    ".scripts/dex-agent-health.sh",
)

LIVE_AI_GUIDANCE = (
    "CLAUDE.md",
    "README.md",
    ".claude/skills/README.md",
    ".scripts/meeting-intel/sync-from-granola.cjs",
    "core/utils/dex_logger.py",
)

LIVE_INTEGRATION_GUIDANCE = (
    ".claude/skills/README.md",
    ".claude/skills/integrations/README.md",
    ".claude/skills/integrations/integrate-notion.md",
    ".claude/skills/integrations/integrate-slack.md",
    ".claude/skills/integrations/integrate-google.md",
    "core/integrations/BUILD_TRACKER.md",
    "core/integrations/post_update_check.py",
    "core/integrations/notion/setup.py",
    "core/integrations/slack/setup.py",
    "core/integrations/google/setup.py",
)


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _integration_status(*, installed: bool, recommended: bool = False) -> dict:
    return {
        "installed": installed,
        "package": "custom-mcp" if installed else None,
        "version": None,
        "config_path": None,
        "is_dex_recommended": recommended,
        "recommendation": None,
    }


def test_retired_pi_model_setup_is_not_shipped_or_advertised() -> None:
    assert not [
        path for path in RETIRED_PI_ARTIFACTS if (REPO_ROOT / path).exists()
    ]

    retired_commands = ("/ai-" + "setup", "/ai-" + "status")
    offenders = {
        path: command
        for path in LIVE_AI_GUIDANCE
        for command in retired_commands
        if command in _read(path)
    }
    assert offenders == {}
    assert ".env" in _read("core/utils/dex_logger.py")
    assert r"LLM API key to \`.env\`" in _read(
        ".scripts/meeting-intel/sync-from-granola.cjs"
    )


def test_retired_pi_usage_metrics_are_removed() -> None:
    usage_log = _read("System/usage_log.md")
    analytics = _read("core/mcp/analytics_helper.py")

    assert "Pi used" not in usage_log
    assert "## AI Configuration" not in usage_log
    assert "Pi used" not in analytics
    assert "'ai_config'" not in analytics
    assert "## Integrations (5 features)" in usage_log
    assert "MCP added (`/dex-add-mcp`)" in usage_log
    assert "'MCP added'" in analytics


def test_live_usage_signals_preserve_the_55_point_journey_score(monkeypatch) -> None:
    usage_log = _read("System/usage_log.md")
    feature_names = {
        match.group(1)
        for match in re.finditer(r"- \[[ x]\] (.+)", usage_log)
    }
    monkeypatch.setattr(
        analytics_helper,
        "load_usage_log",
        lambda: {"features": {name: True for name in feature_names}, "metadata": {}},
    )

    metadata = analytics_helper.calculate_journey_metadata()

    assert metadata["feature_adoption_score"] == 55


def test_mcp_added_counts_as_integration_adoption(monkeypatch) -> None:
    monkeypatch.setattr(
        analytics_helper,
        "load_usage_log",
        lambda: {
            "features": {"MCP added (`/dex-add-mcp`)": True},
            "metadata": {},
        },
    )

    metadata = analytics_helper.calculate_journey_metadata()

    assert metadata["feature_adoption_score"] == 1
    assert metadata["most_active_area"] == "integrations"


def test_parked_rollout_and_dev_only_scripts_are_not_shipped() -> None:
    assert not [
        path
        for path in PARKED_OR_DEV_ONLY_ARTIFACTS
        if (REPO_ROOT / path).exists()
    ]
    assert "ritual" not in _read(".claude/skills/daily-plan/SKILL.md").lower()


def test_live_integration_guidance_only_names_the_shipped_entrypoint() -> None:
    dead_commands = tuple(
        "/integrate-" + service for service in ("notion", "slack", "google")
    )
    offenders = {
        path: command
        for path in LIVE_INTEGRATION_GUIDANCE
        for command in dead_commands
        if command in _read(path)
    }
    assert offenders == {}
    for path in LIVE_INTEGRATION_GUIDANCE:
        assert "/integrate-mcp" in _read(path), path
    assert "Building in Parallel" not in _read("core/integrations/BUILD_TRACKER.md")
    assert "onboarding (Step 8)" in _read(".claude/skills/integrations/README.md")


def test_post_update_missing_integrations_point_to_integrate_mcp(monkeypatch) -> None:
    missing = _integration_status(installed=False)
    monkeypatch.setattr(
        post_update_check,
        "detect_all_integrations",
        lambda: {"notion": missing, "slack": missing, "google": missing},
    )

    has_new, message = post_update_check.check_new_integrations_available()

    assert has_new is True
    assert "`/integrate-mcp`" in message
    assert "/integrate-notion" not in message
    assert "/integrate-slack" not in message
    assert "/integrate-google" not in message


def test_post_update_upgrade_points_to_integrate_mcp(monkeypatch) -> None:
    custom = _integration_status(installed=True)
    recommended = _integration_status(installed=True, recommended=True)
    monkeypatch.setattr(
        post_update_check,
        "detect_all_integrations",
        lambda: {
            "notion": custom,
            "slack": recommended,
            "google": recommended,
            "any_upgradeable": True,
        },
    )

    has_upgrade, message = post_update_check.check_upgradeable_integrations()

    assert has_upgrade is True
    assert "`/integrate-mcp`" in message
    assert "/integrate-notion" not in message


@pytest.mark.parametrize("setup_module", (notion_setup, slack_setup, google_setup))
def test_integration_connection_failures_point_to_integrate_mcp(
    monkeypatch, setup_module
) -> None:
    monkeypatch.setattr(setup_module, "is_installed", lambda: False)

    success, message = setup_module.test_connection()

    assert success is False
    assert "/integrate-mcp" in message


def test_missing_anthropic_key_points_to_env_file() -> None:
    assert dex_logger._generate_human_message(
        "Meeting sync", "ANTHROPIC_API_KEY is missing"
    ) == "API key missing — add it to your .env file"


def test_onboarding_skips_calendar_cleanly_on_non_macos() -> None:
    flow = _read(".claude/flows/onboarding.md")
    calendar_step = flow.split("## Calendar First (Before Step 1)", 1)[1].split(
        "## Step 1:", 1
    )[0]

    assert "uname -s" in calendar_step
    assert "non-macOS" in calendar_step
    assert "calendar sync is currently available only on macos" in calendar_step.lower()
    assert "save_calendar_selection(skipped=true)" in calendar_step
    assert "continue to Step 1" in calendar_step
    assert "Do not call `calendar_list_calendars`" in calendar_step
    assert "show macOS settings guidance" in calendar_step
    assert "block onboarding" in calendar_step
    assert calendar_step.index("uname -s") < calendar_step.index(
        "calendar_list_calendars"
    )
    assert flow.index("## Calendar First (Before Step 1)") < flow.index("## Step 1:")


def test_onboarding_confirms_calendar_identity_through_existing_validation() -> None:
    flow = _read(".claude/flows/onboarding.md")
    calendar_step = flow.split("## Calendar First (Before Step 1)", 1)[1].split(
        "## Step 1:", 1
    )[0]

    assert "Before I ask you anything" in calendar_step
    assert "your actual week, organised" in calendar_step
    assert "you can skip it" in calendar_step
    assert "derived_identity" in calendar_step
    assert "You're [name], at [domain] — right?" in calendar_step
    assert "Yes, that's right" in calendar_step
    assert "Let me correct that" in calendar_step
    assert (
        'validate_and_save_step(step_number=1, step_data={"name": "[confirmed name]"})'
        in calendar_step
    )
    assert (
        'validate_and_save_step(step_number=4, step_data={"email_domain": '
        '"[confirmed domain]"})' in calendar_step
    )
    assert "Do not bypass either validation call" in calendar_step


def test_onboarding_keeps_conservative_identity_fallbacks() -> None:
    flow = _read(".claude/flows/onboarding.md")
    calendar_step = flow.split("## Calendar First (Before Step 1)", 1)[1].split(
        "## Step 1:", 1
    )[0]
    name_step = flow.split("## Step 1:", 1)[1].split("## Step 2:", 1)[0]
    domain_step = flow.split("## Step 4:", 1)[1].split("## Step 5:", 1)[0]

    assert "If only `domain` is present" in calendar_step
    assert "ask for the name normally in Step 1" in calendar_step
    assert "If there is no `work_email`" in calendar_step
    assert "follow steps 1 and 4 exactly as written" in calendar_step.lower()
    assert "First, what's your name?" in name_step
    assert "What's your company email domain?" in domain_step


def test_onboarding_narrows_roles_by_area_before_saving_existing_role_number() -> None:
    flow = _read(".claude/flows/onboarding.md")
    role_step = flow.split("## Step 2:", 1)[1].split("## Step 3:", 1)[0]

    assert "First ask for their AREA" in role_step
    assert "Then ask for their ROLE" in role_step
    for area in (
        "Product",
        "Sales",
        "Marketing",
        "Engineering / Data / IT",
        "Design",
        "Customer Success",
        "Operations / Finance / People / Legal",
        "Leadership / Exec / Advisory",
        "Something else",
    ):
        assert area in role_step
    assert role_step.index("First ask for their AREA") < role_step.index(
        "Then ask for their ROLE"
    )
    assert (
        'validate_and_save_step(step_number=2, step_data={"role_number": '
        "[selected id as integer]})" in role_step
    )
    assert (
        'validate_and_save_step(step_number=2, step_data={"role": '
        '"[their description]", "role_group": "Custom"})' in role_step
    )


def test_onboarding_keeps_pillars_intentional_and_grounds_them_in_calendar_evidence() -> None:
    flow = _read(".claude/flows/onboarding.md")
    pillar_step = flow.split("## Step 5:", 1)[1].split("## Step 6:", 1)[0]
    unchanged_question = (
        'Ask: "What are the 2-3 long-term areas of focus for your role? '
        "Think broad themes, not specific goals."
    )

    assert "run_first_week_analysis()" in pillar_step
    assert pillar_step.index("run_first_week_analysis()") < pillar_step.index(
        unchanged_question
    )
    assert "`recurring_commitments`" in pillar_step
    assert "`internal_external_split`" in pillar_step
    assert "`observations`" in pillar_step
    assert (
        "That's where your time went. Pillars are what you want to be true in a "
        "year — and there's often something important that owns none of your "
        "calendar yet. That counts too."
    ) in pillar_step
    assert "Do not infer or guess pillars" in pillar_step
    assert "`available: false` or `meeting_count: 0`" in pillar_step
    assert "no evidence block and no apology" in pillar_step
    assert unchanged_question in pillar_step


def test_onboarding_gives_an_honest_time_estimate() -> None:
    opening = _read(".claude/flows/onboarding.md").splitlines()[2]

    assert "about 10 minutes" in opening
    assert "~5 minute" not in opening


def test_onboarding_collects_the_optional_company_name_it_saves() -> None:
    flow = _read(".claude/flows/onboarding.md")
    company_step = flow.split("## Step 3:", 1)[1].split("## Step 4:", 1)[0]

    assert "company name" in company_step.lower()
    assert "optional" in company_step.lower()


def test_onboarding_documents_the_explicit_no_company_domain_path() -> None:
    flow = _read(".claude/flows/onboarding.md")
    domain_step = flow.split("## Step 4:", 1)[1].split("## Step 5:", 1)[0]

    assert '"no_company_domain": true' in domain_step
    assert "Non-empty value" not in domain_step
    assert "This step CANNOT be skipped" not in domain_step


def test_onboarding_runs_the_first_week_reveal_before_tool_discovery() -> None:
    flow = _read(".claude/flows/onboarding.md")
    finale = flow.split("## Step 8:", 1)[1].split("## Step 9:", 1)[0]

    assert "run_first_week_analysis()" in finale
    assert "This call is automatic" in finale
    assert "`available: false`" in finale
    assert "`meeting_count: 0`" in finale
    assert "Never invent" in finale
    assert "draft_weekly_plan" in finale
    assert "prepare_entity_page_offer()" in finale
    assert "respond_to_entity_page_offer" in finale
    assert "yes / no / never" in finale
    assert "If `suggestions` is empty, say nothing about pages" in finale
    assert "Want me to just do this automatically from now on?" in finale
    assert "set_entity_creation_default(automatic=true)" in finale
    assert "set_entity_creation_default(automatic=false)" in finale
    assert "Ask me about any of them" in finale


def test_onboarding_step_nine_explains_connect_without_overpromising() -> None:
    flow = _read(".claude/flows/onboarding.md")
    connect_step = flow.split("## Step 9:", 1)[1].split("## Step 10:", 1)[0]
    lowered = connect_step.lower()

    assert "/connect" in connect_step
    assert "hundreds" in lowered
    assert "paste a key" in lowered
    assert "browser sign-in" in lowered
    assert "one-time setup" in lowered
    assert "register your own app for dex" in lowered
    assert "tool's own settings" in lowered
    assert "google and linear" in lowered
    assert "--allow-unvetted" in connect_step
    assert "explicit opt-in" in lowered
    assert connect_step.index("get explicit opt-in") < connect_step.index(
        "--allow-unvetted"
    )
    for forbidden_claim in ("secure", "safe", "malware"):
        assert forbidden_claim not in lowered


def test_onboarding_step_nine_preserves_the_curated_setup_skill_flow() -> None:
    flow = _read(".claude/flows/onboarding.md")
    connect_step = flow.split("## Step 9:", 1)[1].split("## Step 10:", 1)[0]

    assert "invoke the skill referenced in the integration's `setup` field" in connect_step
    assert "Wait for the setup skill to complete" in connect_step
    assert "Which existing skills just got smarter" in connect_step
    assert "What new capabilities are now available" in connect_step
    assert "Privacy and trust level summary" in connect_step
    assert "Move to the next selected integration" in connect_step


def test_getting_started_treats_the_reveal_as_already_presented() -> None:
    skill = _read(".claude/skills/getting-started/SKILL.md")

    assert "The first-week reveal already ran during onboarding" in skill
    assert "Do not repeat the first-week statistics" in skill
    assert "pre_analysis_deferred" not in skill
    assert "run_dramatic_reveal" not in skill
    assert "Analyze Granola data extent" in skill


def test_core_behavior_defines_feature_status_rendering() -> None:
    instructions = _read("CLAUDE.md")
    heading = "### When an MCP tool returns `feature_status`"
    section = instructions.split(heading, 1)[1].split("\n### ", 1)[0]

    for state in ("`ok`", "`off`", "`not_installed`", "`broken`", "`unknown`"):
        assert state in section
    assert "use the result normally" in section
    assert "healthy" in section
    assert "user_message" in section
    assert "one calm line" in section
    assert "no error tone" in section
    assert "never nag" in section
    assert "fix path" in section
    assert "could not be checked" in section
    assert "never invent" in section.lower()


@pytest.mark.parametrize(
    "skill_path",
    (
        ".claude/skills/daily-plan/SKILL.md",
        ".claude/skills/process-meetings/SKILL.md",
        ".claude/skills/meeting-prep/SKILL.md",
    ),
)
def test_high_traffic_skills_follow_feature_status_rendering(skill_path: str) -> None:
    assert "`feature_status` rendering convention" in _read(skill_path)
