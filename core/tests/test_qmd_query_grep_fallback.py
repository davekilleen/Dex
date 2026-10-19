"""Regression coverage for vault search when QMD is unavailable."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.utils import qmd_query


@pytest.fixture
def fallback_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(qmd_query, "is_qmd_available", lambda: False)
    return tmp_path


def _write(vault: Path, relative_path: str, content: str) -> Path:
    path = vault / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_grep_fallback_returns_matching_file_with_usable_snippet(
    fallback_vault: Path,
):
    matching = _write(
        fallback_vault,
        "06-Resources/Accounts/Acme.md",
        "# Acme\n\n"
        "Renewal context before the key sentence.\n"
        "The customer retention plan needs an executive owner this week.\n"
        "Follow-up context after the key sentence.\n",
    )
    _write(
        fallback_vault,
        "06-Resources/Accounts/Other.md",
        "# Other\n\nA procurement timeline with no related content.\n",
    )

    results = qmd_query.vault_search("retention", limit=10)

    assert len(results) == 1
    assert results[0]["path"] == str(matching)
    assert results[0]["source"] == "grep"
    assert results[0]["score"] > 0
    assert "customer retention plan" in results[0]["snippet"]
    assert len(results[0]["snippet"]) <= 264


def test_grep_fallback_returns_empty_list_for_no_match(fallback_vault: Path):
    _write(
        fallback_vault,
        "Projects/Roadmap.md",
        "# Roadmap\n\nShip the onboarding improvements.\n",
    )

    assert qmd_query.vault_search("nonexistent-zebra-phrase") == []


def test_grep_fallback_is_case_insensitive_and_uses_any_meaningful_query_term(
    fallback_vault: Path,
):
    customer_file = _write(
        fallback_vault,
        "Notes/CUSTOMER.md",
        "A CUSTOMER interview is scheduled tomorrow.\n",
    )
    retention_file = _write(
        fallback_vault,
        "Notes/retention.md",
        "Retention metrics improved this month.\n",
    )
    _write(
        fallback_vault,
        "Notes/unrelated.md",
        "Engineering deployment notes.\n",
    )

    results = qmd_query.vault_search("customer retention")

    assert {result["path"] for result in results} == {
        str(customer_file),
        str(retention_file),
    }
    assert all(result["source"] == "grep" for result in results)


def test_as_glob_list_accepts_one_or_many_patterns() -> None:
    assert qmd_query._as_glob_list("notes/**/*.md") == ["notes/**/*.md"]
    assert qmd_query._as_glob_list(["a/**/*.md", "b/**/*.md"]) == [
        "a/**/*.md",
        "b/**/*.md",
    ]
    assert qmd_query._as_glob_list([]) == ["**/*.md"]


def test_grep_fallback_still_accepts_a_single_file_glob(fallback_vault: Path) -> None:
    matching = _write(fallback_vault, "System/Dex_Backlog.md", "retention idea for Dex\n")
    _write(fallback_vault, "00-Inbox/Meetings/2026-09-02.md", "retention plan in a meeting\n")

    results = qmd_query.vault_search("retention", fallback_glob="System/Dex_Backlog.md")

    assert [result["path"] for result in results] == [str(matching)]


def test_grep_fallback_handles_unicode_and_odd_markdown_filenames(
    fallback_vault: Path,
):
    matching = _write(
        fallback_vault,
        "06-Résources/Café notes (Q3) ✨.md",
        "# Résumé\n\nThe café launch includes a résumé review.\n",
    )
    _write(
        fallback_vault,
        "06-Résources/会議 notes [draft].md",
        "# 会議\n\nUnrelated international meeting notes.\n",
    )

    results = qmd_query.vault_search("RÉSUMÉ")

    assert [result["path"] for result in results] == [str(matching)]
    assert "résumé review" in results[0]["snippet"].lower()
