"""Contract tests for the /review -> /daily-review retirement.

`/review` is retired in favour of `/daily-review`, but kept as a one-release
deprecation alias so existing `/review` invocations still route to daily-review
(break nobody). References across CLAUDE.md, onboarding, career skills, and the
usage-log token are repointed to /daily-review consistently.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / ".claude/skills/review/SKILL.md"
DAILY_REVIEW = ROOT / ".claude/skills/daily-review/SKILL.md"
CLAUDE_MD = ROOT / "CLAUDE.md"
ONBOARDING = ROOT / ".claude/flows/onboarding.md"
USAGE_LOG = ROOT / "System/usage_log.md"
CAREER_SETUP = ROOT / ".claude/skills/_available/capabilities/career/skills/career-setup/SKILL.md"
CAREER_COACH = ROOT / ".claude/skills/_available/capabilities/career/skills/career-coach/SKILL.md"


def test_review_is_a_deprecation_alias_not_a_full_skill() -> None:
    text = REVIEW.read_text(encoding="utf-8")
    lower = text.lower()
    assert "deprecation alias" in lower
    assert "daily-review" in text
    # The old standalone end-of-day-review body is gone (it now redirects).
    assert "Step 0: File Discovery" not in text
    assert "Tone Calibration" not in text


def test_daily_review_still_exists_as_canonical() -> None:
    assert DAILY_REVIEW.is_file()
    assert "daily-review" in DAILY_REVIEW.read_text(encoding="utf-8")


def test_alias_description_names_daily_review_as_the_target() -> None:
    fm = REVIEW.read_text(encoding="utf-8").split("---\n", 2)[1]
    desc = next(l for l in fm.splitlines() if l.startswith("description:")).lower()
    assert "daily-review" in desc
    # Has a when-trigger (users typing /review) so it is not a discoverability-risk.
    assert "when the user" in desc


def test_no_live_dex_review_command_references_remain() -> None:
    # These files should point at /daily-review, never the retired /review command.
    for path in (CLAUDE_MD, ONBOARDING, CAREER_SETUP, CAREER_COACH):
        text = path.read_text(encoding="utf-8")
        # The literal Dex slash-command "/review" (word-boundary) must be gone;
        # "/daily-review", "/week-review", "planning/review" etc. are fine.
        import re
        bare = [m.start() for m in re.finditer(r"(?<![-\w/])/review\b", text)]
        assert not bare, f"stale /review command reference in {path.name}"


def test_usage_log_token_repointed_to_daily_review() -> None:
    text = USAGE_LOG.read_text(encoding="utf-8")
    assert "Daily review (`/daily-review`)" in text
    assert "(`/review`" not in text
