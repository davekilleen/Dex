"""Routing contract for casual bug reports in the shipped Dex persona.

Dave's requirement (2026-08-11): users "just need to be in normal wording and
normal language and Dex will figure it out that this is a bug." Onboarding now
tells users exactly that, so `CLAUDE.md` has to carry a trigger block that makes
it real — in the same pattern as the Granola and task-app blocks.

What these tests can and cannot prove: routing is ultimately model judgement, and
this repository has no LLM eval harness, so nothing here executes a model. These
are instruction-contract tests, the same kind as `test_instruction_honesty.py`
and `test_health_telemetry_consent_ux.py`: they pin the phrasings the block must
recognise, the cases it must NOT claim (false positives cost more than misses
here — a wrongly filed report burns the user's trust and the team's triage), and
the fact that the block does not collide with the ideas backlog next to it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

TRIGGER_HEADING = "### Something in Dex Is Broken (Natural Language Triggers)"
IDEAS_HEADING = "### Proactive Improvement Capture (Innovation Concierge)"

# Casual phrasings a real user actually types. None of them contain the words
# "bug", "report", or "/feedback" — that is the whole point.
CASUAL_BUG_PHRASINGS = (
    "the meeting sync is doing something weird",
    "this keeps breaking",
    "X isn't working",
    "X stopped working",
    "it did that again",
    "that's not what I asked for",
    "something's off with",
    "did that used to work?",
)

# Things that must NOT become a bug report. A false positive here files a
# report about the user's own life, which is both useless and a trust breach.
NON_DEFECT_CASES = (
    "my calendar is a mess",
    "this project is a disaster",
    "that meeting was broken",
    "Granola is slow today",
)


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _flatten(text: str) -> str:
    """The persona is hard-wrapped prose; match on sentences, not line breaks."""
    return " ".join(text.split())


def _section(headings_text: str, heading: str) -> str:
    assert heading in headings_text, f"missing persona section: {heading}"
    return headings_text.split(heading, 1)[1].split("\n### ", 1)[0]


def _trigger_block() -> str:
    return _flatten(_section(_read("CLAUDE.md"), TRIGGER_HEADING))


@pytest.mark.parametrize("phrasing", CASUAL_BUG_PHRASINGS)
def test_casual_bug_phrasings_are_recognised_as_report_triggers(phrasing: str) -> None:
    assert phrasing in _trigger_block()


@pytest.mark.parametrize("phrasing", NON_DEFECT_CASES)
def test_ordinary_non_bug_talk_is_explicitly_excluded(phrasing: str) -> None:
    block = _trigger_block()
    exclusions = block.split("**Don't over-trigger:**", 1)
    assert len(exclusions) == 2, "the block must carry an explicit over-trigger guard"
    assert phrasing in exclusions[1]


def test_the_block_routes_defects_apart_from_setup_problems() -> None:
    """A missing API key is not a Dex bug, and must not be filed as one."""
    block = _trigger_block()

    assert "/feedback" in block
    assert "/dex-doctor" in block
    assert "Investigate here first" in block
    assert "Don't file a report for it." in block
    # Unclear cases still get filed — a miss is worse than a false alarm here,
    # matching the /feedback skill's own edge-case rule.
    assert "Genuinely unclear" in block
    assert "false alarm" in block


def test_sending_still_requires_approval_when_the_route_starts_here() -> None:
    block = _trigger_block()

    assert "Nothing is ever sent without approval" in block
    assert "show-before-send" in block
    assert "One offer per distinct failure per session" in block


def test_wishes_and_defects_do_not_collide() -> None:
    """The ideas backlog and the bug loop sit next to each other; keep them apart."""
    ideas_block = _flatten(_section(_read("CLAUDE.md"), IDEAS_HEADING))
    trigger_block = _trigger_block()

    # Each block points at the other, so neither silently swallows the other's traffic.
    assert "routes to `/feedback`" in ideas_block
    assert "capture_idea()" in trigger_block
    assert "A wish is not a defect." in trigger_block

    # The two trigger lists must stay disjoint. Compare the phrase lists only:
    # each block's cross-reference deliberately names the other's phrasing.
    ideas_phrases = ideas_block.split("**When detected:**", 1)[0]
    trigger_phrases = trigger_block.split("**Action:**", 1)[0]

    assert "I wish Dex could" in ideas_phrases
    for wish in ("I wish Dex could", "It would be nice if"):
        assert wish not in trigger_phrases
    for defect in ("this keeps breaking", "stopped working"):
        assert defect not in ideas_phrases


def test_the_feedback_skill_advertises_the_same_casual_route() -> None:
    """Persona and skill must agree, or the block routes to a skill that declines."""
    skill = _read(".claude/skills/feedback/SKILL.md")
    description = _flatten(skill.split("description:", 1)[1].split("\n---", 1)[0])

    assert "in their own words" in description
    assert "report this" in description
    # At least one casual phrasing the persona block promises must be advertised
    # by the skill itself, since that description is what selects the skill.
    assert any(phrase in description for phrase in CASUAL_BUG_PHRASINGS)
    # And the skill must keep declining the two things that are not Dex defects.
    assert "improvements backlog" in description
    assert "never a Dex defect" in description


def test_feedback_skill_invokes_client_with_vault_interpreter() -> None:
    """Bare python3 is fallback only; prefer the vault interpreter other Dex scripts use."""
    skill = _read(".claude/skills/feedback/SKILL.md")

    assert 'python3 .claude/skills/feedback/scripts/feedback_client.py' not in skill
    assert "|| python3" not in skill
    assert "${CLAUDE_DIR:-}/.venv/bin/python" in skill
    assert "${VAULT_PATH:-}/.venv/bin/python" in skill
    assert 'FEEDBACK_PYTHON="python3"' in skill
    for subcommand in ("check", "report", "status", "answer"):
        assert f'"$FEEDBACK_PYTHON" .claude/skills/feedback/scripts/feedback_client.py {subcommand}' in skill
    assert "do not switch to bare `python3` even if the printed example uses it" in skill
    assert 'run the `link` subcommand with `"$FEEDBACK_PYTHON"`' in skill
