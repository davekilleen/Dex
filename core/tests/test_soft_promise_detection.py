"""Tests for shared soft-promise detection."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from core.soft_promise import detect_soft_promises

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_detects_supported_soft_promise_phrasings() -> None:
    examples = [
        "I'll follow up with Priya tomorrow",
        "let me get back to you on the pricing",
        "we should revisit the roadmap",
        "I need to reach out to Sam",
        "I'll send you the deck by Friday",
    ]

    results = [detect_soft_promises(example) for example in examples]

    assert all(len(result) == 1 for result in results)
    assert results[0][0]["person"] == "Priya"
    assert results[4][0]["due"] == "Friday"


def test_rejects_questions_hypotheticals_past_tense_and_plain_statements() -> None:
    examples = [
        "should we follow up?",
        "I might look into it",
        "maybe I'll circle back",
        "I followed up yesterday",
        "The roadmap is ready for review.",
    ]

    assert all(detect_soft_promises(example) == [] for example in examples)


def test_empty_input_returns_no_candidates() -> None:
    assert detect_soft_promises("") == []
    assert detect_soft_promises(None) == []


def test_deduplicates_identical_commitments() -> None:
    text = "I'll follow up with Priya. I'll follow up with Priya."

    assert len(detect_soft_promises(text)) == 1


def test_mcp_tool_is_statically_declared() -> None:
    checker_path = REPO_ROOT / "scripts" / "check-instructed-tools.py"
    spec = importlib.util.spec_from_file_location(
        "check_instructed_tools_soft_promise",
        checker_path,
    )
    assert spec is not None
    checker = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(checker)

    source = (REPO_ROOT / "core" / "mcp" / "work_server.py").read_text(
        encoding="utf-8"
    )

    assert "detect_soft_commitments" in checker.extract_defined_tool_names(source)
