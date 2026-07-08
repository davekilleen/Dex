"""Coverage for core.utils.qmd_query — the shared vault-search interface.

Four MCP servers (work, career, commitment, dex-improvements) route their
semantic search through this module; the grep fallback is what every user
without QMD installed actually runs. Previously 0% covered.
"""

from __future__ import annotations

import json

import pytest

from core.utils import qmd_query


@pytest.fixture(autouse=True)
def reset_qmd_cache():
    qmd_query.reset_cache()
    yield
    qmd_query.reset_cache()


def _make_vault(tmp_path):
    vault = tmp_path / "vault"
    (vault / "Projects").mkdir(parents=True)
    (vault / "Projects" / "Churn_Reduction.md").write_text(
        "# Churn Reduction\nCustomer retention program targeting at-risk accounts.\n"
    )
    (vault / "Projects" / "Unrelated.md").write_text("# Unrelated\nNothing relevant here.\n")
    return vault


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------


def test_parse_qmd_output_json_list():
    output = json.dumps(
        [
            {"path": "Projects/A.md", "score": 0.9, "snippet": "alpha"},
            {"file": "Projects/B.md", "relevance": 0.4, "content": "beta"},
        ]
    )
    results = qmd_query._parse_qmd_output(output)
    assert [r["path"] for r in results] == ["Projects/A.md", "Projects/B.md"]
    assert results[0]["score"] == 0.9
    assert results[1]["score"] == 0.4
    assert results[1]["snippet"] == "beta"
    assert all(r["source"] == "qmd" for r in results)


def test_parse_qmd_output_json_results_envelope():
    output = json.dumps({"results": [{"path": "Notes/x.md", "score": 0.7}]})
    results = qmd_query._parse_qmd_output(output)
    assert results[0]["path"] == "Notes/x.md"


def test_parse_qmd_output_text_blocks():
    output = "Projects/Churn_Reduction.md (score: 0.85)\nretention program details\n\nProjects/Other.md\nsecond snippet\n"
    results = qmd_query._parse_qmd_output(output)
    assert len(results) == 2
    assert results[0]["path"] == "Projects/Churn_Reduction.md"
    assert results[0]["score"] == 0.85
    assert "retention program" in results[0]["snippet"]
    assert results[1]["score"] == 0.5  # default when no score printed


def test_parse_qmd_output_empty():
    assert qmd_query._parse_qmd_output("") == []
    assert qmd_query._parse_qmd_output("   \n  ") == []


# ---------------------------------------------------------------------------
# Grep fallback
# ---------------------------------------------------------------------------


def test_grep_fallback_finds_matching_files(tmp_path):
    vault = _make_vault(tmp_path)
    results = qmd_query._grep_fallback("customer retention", str(vault))

    assert len(results) == 1
    assert results[0]["path"].endswith("Churn_Reduction.md")
    assert results[0]["source"] == "grep"
    assert "retention" in results[0]["snippet"].lower()


def test_grep_fallback_explicit_pattern(tmp_path):
    vault = _make_vault(tmp_path)
    results = qmd_query._grep_fallback("anything", str(vault), grep_pattern="churn|at-risk")
    assert len(results) == 1
    assert results[0]["path"].endswith("Churn_Reduction.md")


def test_grep_fallback_short_words_only_returns_empty(tmp_path):
    vault = _make_vault(tmp_path)
    # every query word <= 2 chars -> no usable pattern
    assert qmd_query._grep_fallback("a of to", str(vault)) == []


def test_extract_snippet_windows_around_match(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("padding " * 50 + "the RETENTION plan " + "padding " * 50)
    snippet = qmd_query._extract_snippet(str(f), "retention")
    assert "RETENTION" in snippet
    assert snippet.startswith("...")
    assert snippet.endswith("...")
    assert qmd_query._extract_snippet(str(tmp_path / "ghost.md"), "x") == ""


# ---------------------------------------------------------------------------
# vault_search routing
# ---------------------------------------------------------------------------


def test_vault_search_uses_grep_when_qmd_unavailable(tmp_path, monkeypatch):
    vault = _make_vault(tmp_path)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(qmd_query, "is_qmd_available", lambda: False)

    results = qmd_query.vault_search("customer retention")

    assert len(results) == 1
    assert results[0]["source"] == "grep"


def test_vault_search_prefers_qmd_and_applies_min_score(monkeypatch):
    fake = [
        {"path": "a.md", "score": 0.9, "snippet": "", "source": "qmd"},
        {"path": "b.md", "score": 0.2, "snippet": "", "source": "qmd"},
    ]
    monkeypatch.setattr(qmd_query, "is_qmd_available", lambda: True)
    monkeypatch.setattr(qmd_query, "_qmd_search", lambda *a, **k: list(fake))

    results = qmd_query.vault_search("anything", min_score=0.5)

    assert [r["path"] for r in results] == ["a.md"]


def test_vault_search_falls_back_when_qmd_returns_nothing(tmp_path, monkeypatch):
    vault = _make_vault(tmp_path)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(qmd_query, "is_qmd_available", lambda: True)
    monkeypatch.setattr(qmd_query, "_qmd_search", lambda *a, **k: [])

    results = qmd_query.vault_search("customer retention")

    assert results and results[0]["source"] == "grep"


def test_vault_search_multi_deduplicates_keeping_best_score(monkeypatch):
    responses = {
        "q1": [{"path": "a.md", "score": 0.3, "snippet": "", "source": "qmd"}],
        "q2": [
            {"path": "a.md", "score": 0.8, "snippet": "", "source": "qmd"},
            {"path": "b.md", "score": 0.5, "snippet": "", "source": "qmd"},
        ],
    }
    monkeypatch.setattr(qmd_query, "vault_search", lambda q, limit=5, **k: list(responses[q]))

    results = qmd_query.vault_search_multi(["q1", "q2"])

    assert [(r["path"], r["score"]) for r in results] == [("a.md", 0.8), ("b.md", 0.5)]


# ---------------------------------------------------------------------------
# Binary discovery / availability caching
# ---------------------------------------------------------------------------


def test_find_qmd_caches_negative_result(tmp_path, monkeypatch):
    monkeypatch.setattr(qmd_query.shutil, "which", lambda name: None)
    monkeypatch.setattr(qmd_query.Path, "home", staticmethod(lambda: tmp_path))

    assert qmd_query._find_qmd() is None
    assert qmd_query.is_qmd_available() is False
    # Cached: a qmd binary appearing later is not seen until reset_cache()
    monkeypatch.setattr(qmd_query.shutil, "which", lambda name: "/usr/bin/qmd")
    assert qmd_query._find_qmd() is None

    qmd_query.reset_cache()
    assert qmd_query._find_qmd() == "/usr/bin/qmd"


def test_resolve_vault_path_prefers_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    assert qmd_query._resolve_vault_path() == str(tmp_path)
