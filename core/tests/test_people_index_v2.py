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
        emails=["jess@example.com", "jj@other.test"], aliases=["JJ"],
        body="\nGoes by Jess\n**Goes by:** Jolly\n",
    )

    index = work_server.build_people_index_data()

    assert index["version"] == 2
    assert index["people"][0]["emails"] == ["jess@example.com", "jj@other.test"]
    assert index["people"][0]["aliases"] == ["JJ", "Jess", "Jolly"]
    assert index["people"][0]["first_name"] == "jessica"


def test_lookup_ladder_and_ambiguity(tmp_path, monkeypatch):
    people_dir, _ = _setup(tmp_path, monkeypatch)
    _write_person(people_dir, "External", "Jessica_Jolly.md", "Jessica Jolly", ["jess@a.test"], ["JJ"])
    _write_person(people_dir, "Internal", "Alice_Smith.md", "Alice Smith", ["alice@dex.test"], ["Al"])
    _write_person(people_dir, "External", "Jessica_Jones.md", "Jessica Jones", ["jones@b.test"])
    work_server.build_people_index_data()

    assert work_server.lookup_person_data("ALICE@DEX.TEST")["matches"][0]["name"] == "Alice Smith"
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
    _write_person(people_dir, "External", "Ava_Stone.md", "Ava Stone", ["ava@test.dev"])
    index_file.parent.mkdir(parents=True)
    index_file.write_text(json.dumps({"version": 1, "built_at": datetime.now().isoformat(), "people": []}))

    result = work_server.lookup_person_data("ava@test.dev")

    assert result["matches"][0]["name"] == "Ava Stone"
    assert json.loads(index_file.read_text())["version"] == 2
