"""The onboarding conversation has one portable source and one Claude bridge."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_portable_flow_and_claude_bridge_are_byte_identical() -> None:
    portable = REPO_ROOT / "core/onboarding/FLOW.md"
    claude_bridge = REPO_ROOT / ".claude/flows/onboarding.md"

    assert portable.read_bytes() == claude_bridge.read_bytes()


def test_setup_skill_points_at_portable_flow() -> None:
    setup = (REPO_ROOT / ".claude/skills/setup/SKILL.md").read_text(encoding="utf-8")
    portable = (REPO_ROOT / "core/onboarding/FLOW.md").read_text(encoding="utf-8")

    assert "core/onboarding/FLOW.md" in setup
    assert "Read `.claude/flows/onboarding.md`" not in setup
    assert ".claude/hooks/" not in portable
    assert ".claude/settings.json" not in portable
    assert "claude mcp" not in portable.lower()
