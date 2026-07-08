"""Safety-net coverage for the destructive vault-wide wikilink migration.

migrate_to_wikilinks rewrites every markdown file in the vault in place;
before this suite it shipped with zero tests. The conversion function and the
dry-run guarantee (no writes) are the load-bearing behaviors.
"""

from __future__ import annotations

from pathlib import Path

from core.obsidian import migrate_to_wikilinks as mig


def _indices():
    person_idx = {"John_Doe": "05-Areas/People/External/John_Doe.md"}
    project_idx = {"Acme_Rollout": "04-Projects/Acme_Rollout.md"}
    company_idx = {"Acme_Corp": "05-Areas/Companies/Acme_Corp.md"}
    return person_idx, project_idx, company_idx


def test_converts_person_reference_to_wikilink():
    content, changes = mig.convert_references_in_file(
        "Met with John_Doe about pricing.", *_indices()
    )
    assert content == "Met with [[John_Doe]] about pricing."
    assert changes == 1


def test_existing_wikilinks_are_not_double_wrapped():
    content, changes = mig.convert_references_in_file(
        "Met with [[John_Doe]] again.", *_indices()
    )
    assert content == "Met with [[John_Doe]] again."
    assert changes == 0


def test_code_blocks_are_left_untouched():
    original = "Notes\n```\nJohn_Doe = load()\n```\nJohn_Doe attended."
    content, changes = mig.convert_references_in_file(original, *_indices())
    assert "```\nJohn_Doe = load()\n```" in content
    assert "[[John_Doe]] attended." in content
    assert changes == 1


def test_task_anchor_becomes_block_reference():
    content, changes = mig.convert_references_in_file(
        "- [ ] Send quote ^task-20260601-001", *_indices()
    )
    assert "[[^task-20260601-001]]" in content
    assert changes == 1


def test_company_and_project_references_convert():
    content, changes = mig.convert_references_in_file(
        "Acme_Corp kickoff, see 04-Projects/Acme_Rollout.md notes.", *_indices()
    )
    assert "[[Acme_Corp]]" in content
    assert "[[04-Projects/Acme_Rollout.md]]" in content
    assert changes == 2


def test_unknown_names_are_untouched():
    content, changes = mig.convert_references_in_file(
        "Talked to Jane_Smith at Globex.", *_indices()
    )
    assert content == "Talked to Jane_Smith at Globex."
    assert changes == 0


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "05-Areas/People/External").mkdir(parents=True)
    (vault / "04-Projects").mkdir(parents=True)
    (vault / "05-Areas/Companies").mkdir(parents=True)
    (vault / "00-Inbox/Meetings").mkdir(parents=True)
    (vault / "05-Areas/People/External/John_Doe.md").write_text("# John Doe\n")
    (vault / "04-Projects/Acme_Rollout.md").write_text("# Acme Rollout\n")
    (vault / "05-Areas/Companies/Acme_Corp.md").write_text("# Acme Corp\n")
    (vault / "00-Inbox/Meetings/2026-06-01 - Sync.md").write_text(
        "Met John_Doe re Acme_Corp.\n"
    )
    return vault


def test_index_builders_map_stems_to_relative_paths(tmp_path, monkeypatch):
    vault = _make_vault(tmp_path)
    monkeypatch.setattr(mig, "BASE_DIR", vault)

    assert mig.build_person_index() == {"John_Doe": "05-Areas/People/External/John_Doe.md"}
    assert mig.build_project_index() == {"Acme_Rollout": "04-Projects/Acme_Rollout.md"}
    assert mig.build_company_index() == {"Acme_Corp": "05-Areas/Companies/Acme_Corp.md"}


def test_dry_run_never_writes(tmp_path, monkeypatch, capsys):
    vault = _make_vault(tmp_path)
    monkeypatch.setattr(mig, "BASE_DIR", vault)
    monkeypatch.setattr("builtins.input", lambda *a: "")

    before = {p: p.read_text() for p in vault.rglob("*.md")}
    mig.migrate_vault(dry_run=True)

    after = {p: p.read_text() for p in vault.rglob("*.md")}
    assert after == before
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "Files modified: 1" in out  # would-be changes are still counted


def test_estimate_migration_formats_seconds_and_minutes():
    assert "second" in mig.estimate_migration([Path("a.md")] * 30)
    assert "minute" in mig.estimate_migration([Path("a.md")] * 3600)
