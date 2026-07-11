from __future__ import annotations

import unicodedata

from core.mcp import work_server


def _setup(tmp_path, monkeypatch, domains="dex.test, second.test"):
    people_dir = tmp_path / "People"
    profile = tmp_path / "System" / "user-profile.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_text(f'email_domain: "{domains}"\n')
    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "PEOPLE_INDEX_FILE", tmp_path / "System" / "People_Index.json")
    monkeypatch.setattr(work_server, "USER_PROFILE_FILE", profile)
    monkeypatch.setattr(work_server, "get_people_dir", lambda: people_dir)
    return people_dir


def test_create_person_routes_explicit_and_computed_locations(tmp_path, monkeypatch):
    people_dir = _setup(tmp_path, monkeypatch)

    internal = work_server.create_person_data("Ian Internal", emails=["ian@dex.test"])
    external = work_server.create_person_data("Eva External", emails=["eva@else.test"])
    unknown = work_server.create_person_data("Una Unknown")

    assert internal == {"success": True, "path": "People/Internal/Ian_Internal.md", "location": "internal", "created": True}
    assert external["location"] == "external"
    assert unknown["location"] == "unknown"
    assert (people_dir / "External" / "Una_Unknown.md").exists()


def test_create_person_rejects_duplicate_email_and_filename_unless_allowed(tmp_path, monkeypatch):
    people_dir = _setup(tmp_path, monkeypatch)
    assert work_server.create_person_data("Alex Doe", emails=["alex@example.com"])["success"]

    email_duplicate = work_server.create_person_data("Different Name", emails=["ALEX@EXAMPLE.COM"])
    filename_duplicate = work_server.create_person_data("alex doe", emails=["other@example.com"])
    allowed = work_server.create_person_data(
        "Alex Doe", emails=["new@sample.test"], allow_duplicate=True, location="external"
    )

    assert email_duplicate["success"] is False
    assert "People/External/Alex_Doe.md" in email_duplicate["error"]
    assert filename_duplicate["success"] is False
    assert allowed["collision"] is True
    assert allowed["path"].endswith("Alex_Doe_(sample.test).md")
    assert (people_dir / "External" / "Alex_Doe_(sample.test).md").exists()


def test_create_person_normalises_unicode_and_rejects_escape(tmp_path, monkeypatch):
    people_dir = _setup(tmp_path, monkeypatch)
    decomposed = "Jose\u0301 Alvarez"

    created = work_server.create_person_data(decomposed, location="external")
    escaped = work_server.create_person_data("../evil", location="external")

    expected = unicodedata.normalize("NFC", decomposed).replace(" ", "_") + ".md"
    assert created["success"] is True
    assert (people_dir / "External" / expected).exists()
    assert escaped["success"] is False
    assert not (tmp_path / "evil.md").exists()


def test_create_person_strips_non_traversal_path_separators_from_filename(tmp_path, monkeypatch):
    people_dir = _setup(tmp_path, monkeypatch)

    created = work_server.create_person_data("AC/DC Contact", location="external")

    assert created["success"] is True
    assert (people_dir / "External" / "ACDC_Contact.md").exists()


def test_create_person_exclusive_open_reports_preexisting_file(tmp_path, monkeypatch):
    people_dir = _setup(tmp_path, monkeypatch)
    target = people_dir / "External" / "Race_Person.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")

    result = work_server.create_person_data("Race Person", location="external", allow_duplicate=False)

    assert result["success"] is False
    assert target.read_text() == "original"
