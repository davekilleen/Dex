"""Regression: shipped background AI must not use a deprecated Gemini model.

PR #11 originally upgraded ``google/gemini-2.0-flash-exp:free`` (deprecated)
to ``google/gemini-2.5-flash`` but also bundled a macOS-breaking sound change
and personal config, so it was reworked. These tests pin the model upgrade in
the remaining harness-independent background client.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The meeting-sync client is the remaining harness-independent model consumer.
CONFIG_FILES = [
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


def test_background_gemini_model_is_2_5_flash():
    text = (REPO / ".scripts/lib/llm-client.cjs").read_text(encoding="utf-8")
    assert "gemini-2.5-flash" in text
