"""Practice-folder starter and /setup-lab welcome contract."""

from pathlib import Path
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "lab-onboarding.sh"
SKILL = REPO_ROOT / ".claude" / "skills" / "setup-lab" / "SKILL.md"
HOUR = REPO_ROOT / ".claude" / "skills" / "setup-lab" / "references" / "hour.md"

BANNED_IN_HER_EARS = (
    "MCP",
    "Python environment",
    "wiring",
    "connector",
    "tools are on",
)


def test_lab_starter_finishes_helpers_before_anyone_opens_chat() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert SCRIPT.stat().st_mode & 0o111
    assert "--install-config-only" in text
    assert "core/mcp/requirements.txt" in text
    assert ".mcp.json" in text
    assert "onboarding-mcp" in text
    assert "install.sh" not in text
    assert "onboarding.md" not in text or "Do not follow" in text
    assert "/setup-lab" in text
    assert "hello" in text.lower()


def test_lab_starter_is_valid_bash() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_setup_lab_leads_with_a_welcome() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    hour = HOUR.read_text(encoding="utf-8")
    assert "First thing she hears" in skill
    assert "Hey [first name] — welcome to Dex" in hour
    assert "taking the leap" in hour
    assert "fifteen minutes" in hour
    assert "Do not narrate" in skill
    assert "I won’t try to fix the folder from here" in skill
    for banned in BANNED_IN_HER_EARS:
        assert banned not in hour.split("Banned")[0]
        # The hour may name banned words only in the ban list.
        spoken = hour.split("## 1. Welcome", 1)[1]
        assert banned not in spoken
