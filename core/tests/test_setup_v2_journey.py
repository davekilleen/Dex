"""Contract tests for the /setup-v2 journey — not a second provisioner."""

from __future__ import annotations

from pathlib import Path

from core.utils.validators import validate_skill_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / ".claude/skills/setup-v2/SKILL.md"
HOUR = REPO_ROOT / ".claude/skills/setup-v2/references/hour.md"
EVALS = REPO_ROOT / ".claude/skills/setup-v2/evals/trigger-cases.yaml"
SETUP = REPO_ROOT / ".claude/skills/setup/SKILL.md"
FLOW = REPO_ROOT / "core/onboarding/FLOW.md"
FLOW_COPY = REPO_ROOT / ".claude/flows/onboarding.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_setup_v2_frontmatter_is_valid() -> None:
    assert validate_skill_frontmatter(SKILL) == []


def test_setup_v2_package_exists_without_a_practice_starter() -> None:
    assert SKILL.is_file()
    assert HOUR.is_file()
    assert EVALS.is_file()
    text = _read(SKILL) + _read(HOUR)
    assert "fresh" in text.lower()
    assert "rsync" not in text.lower()
    assert "practice starter" not in text.lower() or "no practice starter" in text.lower()
    assert "lab-onboarding" not in text


def test_shipped_setup_and_flow_stay_the_questionnaire() -> None:
    setup = _read(SETUP)
    flow = _read(FLOW)
    assert "start_onboarding_session()" in setup
    assert "core/onboarding/FLOW.md" in setup
    assert "v2=true" not in setup
    assert flow == _read(FLOW_COPY)
    assert "setup-v2" not in flow
    assert "Chief of Staff" not in flow


def test_progressive_tiers_and_clean_stop() -> None:
    hour = _read(HOUR)
    assert "~2 min" in hour
    assert "5–10" in hour or "5-10" in hour
    assert "15–30" in hour or "15-30" in hour
    assert "Clean stop" in hour or "clean stop" in hour
    assert "Happy path ends at the 5–10 minute stop" in hour or "shortest setup" in hour.lower()


def test_source_doc_invite_has_a_not_now_path() -> None:
    hour = _read(HOUR)
    assert "review" in hour.lower()
    assert "job spec" in hour.lower() or "career ladder" in hour.lower()
    assert "not now" in hour.lower()
    assert "I don’t have one" in hour or "don't have one" in hour.lower()
    assert 'save_source_doc_note(status="skipped")' in hour
    assert "never silently copy" in hour.lower() or "never silently" in hour.lower()


def test_six_required_branches_are_named() -> None:
    hour = _read(HOUR)
    for branch in (
        "Calendar unavailable",
        "No meeting notes",
        "No source doc",
        "Shortest setup",
        "Longer enrichment",
        "Returning / resume",
    ):
        assert branch in hour


def test_notes_are_not_a_gate() -> None:
    hour = _read(HOUR) + _read(SKILL)
    assert "never a gate" in hour.lower()
    assert 'save_meeting_source(primary="none")' in hour


def test_entity_offer_is_explicit_and_v2_windowed() -> None:
    hour = _read(HOUR) + _read(SKILL)
    assert "Shall I create these?" in hour
    assert "v2_window=true" in hour
    assert "Never silent" in hour or "never silent" in hour.lower()


def _spoken_lines(text: str) -> list[str]:
    spoken = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("**Dex:**"):
            spoken.append(line)
    return spoken


def test_no_filler_regression() -> None:
    spoken = "\n".join(_spoken_lines(_read(HOUR))).lower()
    for banned in ("one moment", "nearly there", "still reading"):
        assert banned not in spoken


def test_no_invented_doors_or_vendor_names() -> None:
    spoken = "\n".join(_spoken_lines(_read(HOUR)))
    assert "/connect" not in spoken
    lowered = spoken.lower()
    for banned in ("openai", "anthropic", "claude", "gpt-", "gemini"):
        assert banned not in lowered


def test_google_persist_stays_honest() -> None:
    hour = _read(HOUR) + _read(SKILL)
    assert "never persist google" in hour.lower() or "never a silent google" in hour.lower()
    assert "/google-workspace-setup" in hour
    assert "evidence in this sitting" in hour.lower() or "not stored" in hour.lower()


def test_harness_is_quiet_before_finalize() -> None:
    skill = _read(SKILL)
    assert "inspect_harnesses" in skill
    assert "save_harness_selection" in skill
    assert "Required before finalize" in skill or "required before finalize" in skill.lower()
    assert "No extra spoken beat" in skill or "no extra spoken beat" in skill.lower()


def test_shelf_first_and_no_auto_skill() -> None:
    text = _read(SKILL) + _read(HOUR)
    assert "Do not create a skill" in text or "do not create a skill" in text.lower()
    assert "/daily-plan" in text
    assert "/getting-started" in text


def test_reset_and_change_job_are_not_stolen() -> None:
    skill = _read(SKILL)
    assert "reset" in skill.lower()
    assert "finished vault" in skill.lower() or "do not wipe" in skill.lower()
    change_job = (REPO_ROOT / ".claude/skills/change-job/SKILL.md").read_text(encoding="utf-8")
    reset = (REPO_ROOT / ".claude/skills/reset/SKILL.md").read_text(encoding="utf-8")
    assert "start_onboarding_session(force_new=True)" in change_job
    assert "onboarding.md" in reset
    assert "v2=true" not in change_job
    assert "v2=true" not in reset


def test_completion_marker_stays_finalize() -> None:
    skill = _read(SKILL)
    assert "finalize_onboarding" in skill
    assert "System/.onboarding-complete" not in skill or "do not wipe" in skill.lower()


def test_mac_first_run_and_portable_harness_paths() -> None:
    hour = _read(HOUR)
    assert "macOS" in hour or "Darwin" in hour
    assert "other host" in hour.lower() or "non-mac" in hour.lower() or "any other host" in hour.lower()
    assert "inspect" in hour.lower()
    assert "confirm" in hour.lower()


def test_background_enrichment_is_after_the_stop() -> None:
    hour = _read(HOUR)
    stop_at = hour.lower().index("clean stop")
    enrich_at = hour.lower().index("longer enrichment")
    assert stop_at < enrich_at


def test_inferred_identity_must_be_confirmed() -> None:
    hour = _read(HOUR)
    assert "Nothing inferred is saved until this yes" in hour
    assert "If wrong, they correct" in hour or "they correct" in hour.lower()


def test_zero_tools_on_the_first_turn() -> None:
    skill = _read(SKILL)
    hour = _read(HOUR)
    assert "Zero tools" in skill or "zero tools" in skill.lower()
    assert "first turn, zero tools" in hour.lower() or "Zero tools" in hour
