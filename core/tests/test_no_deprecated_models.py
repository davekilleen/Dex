"""Regression: the budget AI model must not point at a deprecated Gemini model.

PR #11 originally upgraded ``google/gemini-2.0-flash-exp:free`` (deprecated)
to ``google/gemini-2.5-flash`` but also bundled a macOS-breaking sound change
and personal config, so it was reworked. These tests pin the model upgrade so
the deprecated id can't creep back into the config the budget path reads.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Files that configure the budget / cloud model.
CONFIG_FILES = [
    ".claude/skills/ai-setup/SKILL.md",
    "System/scripts/configure-ai-models.sh",
    "06-Resources/Dex_System/AI_Model_Options.md",
    ".scripts/lib/llm-client.cjs",
]


def test_no_deprecated_gemini_2_0_flash_in_config():
    """No config file may reference any deprecated gemini-2.0-flash model."""
    offenders = [
        rel
        for rel in CONFIG_FILES
        if "gemini-2.0-flash" in (REPO / rel).read_text(encoding="utf-8")
    ]
    assert not offenders, f"Deprecated gemini-2.0-flash model still referenced in: {offenders}"


def test_budget_model_is_gemini_2_5_flash():
    """The ai-setup budget model is the current google/gemini-2.5-flash."""
    text = (REPO / ".claude/skills/ai-setup/SKILL.md").read_text(encoding="utf-8")
    assert "google/gemini-2.5-flash" in text
