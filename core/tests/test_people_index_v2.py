from __future__ import annotations

import json
from datetime import datetime

from core.mcp import work_server
from core.utils.entity_pages import render_person_page


def _setup(tmp_path, monkeypatch):
    people_dir = tmp_path / "People"
    index_file = tmp_path / "System" / "People_Index.json"
    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "PEOPLE_INDEX_FILE", index_file)
    monkeypatch.setattr(work_server, "get_people_dir", lambda: people_dir)
    return people_dir, index_file


def _write_person(people_dir, folder, filename, name, emails=None, aliases=None, body=""):
    target = people_dir / folder / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    page = render_person_page(name, emails=emails, aliases=aliases)
    target.write_text(page + body)
    return target


def test_people_index_v2_contains_canonical_emails_aliases_and_first_name(tmp_path, monkeypatch):
    people_dir, _ = _setup(tmp_path, monkeypatch)
    _write_person(
        people_dir, "External", "Jessica_Jolly.md", "Jessica Jolly",
        emails=["jess@example.com", "jj@example.org"], aliases=["JJ"],
        body="\nGoes by Jess\n**Goes by:** Jolly\n",
    )

    index = work_server.build_people_index_data()

    assert index["version"] == 2
    assert index["people"][0]["emails"] == ["jess@example.com", "jj@example.org"]
    assert index["people"][0]["aliases"] == ["JJ", "Jess", "Jolly"]
    assert index["people"][0]["first_name"] == "jessica"


def test_lookup_ladder_and_ambiguity(tmp_path, monkeypatch):
    people_dir, _ = _setup(tmp_path, monkeypatch)
    _write_person(people_dir, "External", "Jessica_Jolly.md", "Jessica Jolly", ["jess@example.com"], ["JJ"])
    _write_person(people_dir, "Internal", "Alice_Smith.md", "Alice Smith", ["alice@anthropic.com"], ["Al"])
    _write_person(people_dir, "External", "Jessica_Jones.md", "Jessica Jones", ["jones@example.org"])
    work_server.build_people_index_data()

    assert work_server.lookup_person_data("ALICE@ANTHROPIC.COM")["matches"][0]["name"] == "Alice Smith"
    assert work_server.lookup_person_data("al")["matches"][0]["name"] == "Alice Smith"
    assert work_server.lookup_person_data("alice smith")["matches"][0]["_score"] == 1.0
    assert work_server.lookup_person_data("alice")["matches"][0]["name"] == "Alice Smith"
    duplicate_first = work_server.lookup_person_data("jessica")
    assert duplicate_first["ambiguous"] is True
    assert {match["name"] for match in duplicate_first["matches"]} == {"Jessica Jolly", "Jessica Jones"}

    near_tie = work_server.lookup_person_data("Jessica Jo")
    assert near_tie["ambiguous"] is True


def test_lookup_rebuilds_version_one_index(tmp_path, monkeypatch):
    people_dir, index_file = _setup(tmp_path, monkeypatch)
    _write_person(people_dir, "External", "Ava_Stone.md", "Ava Stone", ["ava@example.com"])
    index_file.parent.mkdir(parents=True)
    index_file.write_text(json.dumps({"version": 1, "built_at": datetime.now().isoformat(), "people": []}))

    result = work_server.lookup_person_data("ava@example.com")

    assert result["matches"][0]["name"] == "Ava Stone"
    assert json.loads(index_file.read_text())["version"] == 2


def test_lookup_finds_location_type_label_person_pages(tmp_path, monkeypatch):
    people_dir, _ = _setup(tmp_path, monkeypatch)
    target = people_dir / "Internal" / "Alice_Smith.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "---\ntype: internal\nname: Alice Smith\n---\n"
        "# Alice Smith\n\n## Notes\n\nKept as written.\n",
        encoding="utf-8",
    )

    result = work_server.lookup_person_data("Alice Smith")

    assert result["matches"][0]["name"] == "Alice Smith"
    assert "warning" not in result["matches"][0]


def test_lookup_finds_pre_frontmatter_person_pages(tmp_path, monkeypatch):
    people_dir, _ = _setup(tmp_path, monkeypatch)
    target = people_dir / "External" / "Alice_Smith.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "# Alice Smith\n\n"
        "## Relationship Context\n\n"
        "**Last interaction:** 2026-01-15 — intro call\n\n"
        "## Meeting History\n\n"
        "Kept as written.\n",
        encoding="utf-8",
    )

    result = work_server.lookup_person_data("Alice Smith")

    assert result["matches"][0]["name"] == "Alice Smith"
    assert result["matches"][0]["last_interaction"] == "2026-01-15"
    assert "warning" not in result["matches"][0]


def test_lookup_warns_when_a_person_page_is_unreadable(tmp_path, monkeypatch):
    people_dir, _ = _setup(tmp_path, monkeypatch)
    target = people_dir / "External" / "Alice_Smith.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "---\nname: [broken\n---\n# Alice Smith\n\n**Company:** Acme\n",
        encoding="utf-8",
    )

    result = work_server.lookup_person_data("Alice Smith")

    assert result["matches"][0]["status"] == "quarantined"
    assert "Alice Smith" in result["matches"][0]["warning"]
    assert "Alice_Smith.md" in result["matches"][0]["warning"]
    assert "unreadable" in result["matches"][0]["warning"]


def test_lookup_removes_deleted_person_from_sqlite_and_json_export(
    tmp_path,
    monkeypatch,
):
    people_dir, index_file = _setup(tmp_path, monkeypatch)
    person = _write_person(
        people_dir,
        "External",
        "Ghost_User.md",
        "Ghost User",
        ["placeholder@example.org"],
    )
    work_server.build_people_index_data()

    person.unlink()
    result = work_server.lookup_person_data("placeholder@example.org")

    assert result["matches"] == []
    exported = json.loads(index_file.read_text())
    assert exported["total"] == 0
    assert exported["people"] == []
