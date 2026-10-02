"""Tests for shared soft-promise detection."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from core.soft_promise import (
    UNSUPPORTED_LOCALE_NOTE,
    detect_soft_promises,
    detect_soft_promises_report,
)

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


def test_detects_french_soft_promise_phrasings() -> None:
    examples = [
        "Je reviens vers toi sur le prix",
        "Je dois relancer Sam",
        "On devrait revenir sur la roadmap",
        "Je te dois un retour",
        "Je t'envoie le deck d'ici vendredi",
    ]

    results = [detect_soft_promises(example) for example in examples]

    assert all(len(result) == 1 for result in results)
    assert results[0][0]["person"] == "toi"
    assert results[1][0]["person"] == "Sam"
    assert results[4][0]["due"] == "vendredi"


def test_french_hypotheticals_are_rejected() -> None:
    examples = [
        "On devrait revenir sur ça ?",
        "Je vais peut-être relancer Sam",
    ]

    assert all(detect_soft_promises(example) == [] for example in examples)


def test_unsupported_locale_is_reported_instead_of_inventing_matches() -> None:
    spanish = "Voy a hacer un seguimiento con María mañana"
    german = "Ich werde dir das Deck bis Freitag schicken"

    for text in (spanish, german):
        report = detect_soft_promises_report(text)
        assert report["candidates"] == []
        assert report["count"] == 0
        assert report["unsupported_locale"] is True
        assert report["note"] == UNSUPPORTED_LOCALE_NOTE
        assert report["locale_support"] == ["en", "fr"]


def test_supported_locale_report_does_not_claim_unsupported() -> None:
    report = detect_soft_promises_report("I'll follow up with Priya tomorrow")

    assert report["count"] == 1
    assert report["unsupported_locale"] is False
    assert "note" not in report
