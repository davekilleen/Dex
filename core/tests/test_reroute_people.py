from __future__ import annotations

import json

from core.mcp import work_server
from core.utils.entity_pages import render_person_page


def _setup(tmp_path, monkeypatch, domains="newco.test"):
    people_dir = tmp_path / "People"
    index_file = tmp_path / "System" / "People_Index.json"
    profile = tmp_path / "System" / "user-profile.yaml"
    profile.parent.mkdir(parents=True)
    if domains is not None:
        profile.write_text(f'email_domain: "{domains}"\n')
    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "PEOPLE_INDEX_FILE", index_file)
    monkeypatch.setattr(work_server, "USER_PROFILE_FILE", profile)
    monkeypatch.setattr(work_server, "get_people_dir", lambda: people_dir)
    return people_dir, index_file


def _write_person(people_dir, folder, filename, name, emails=None, location="unknown"):
    target = people_dir / folder / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_person_page(name, emails=emails, location=location))
    return target


def _tree_bytes(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _frontmatter(path):
    import yaml

    text = path.read_text()
    _, block, _ = text.split("---\n", 2)
    return yaml.safe_load(block)


def _fixture_vault(people_dir):
    """A vault mid job-change: profile already carries the new domain."""
    _write_person(people_dir, "Internal", "Olivia_Oldco.md", "Olivia Oldco",
                  emails=["olivia@oldco.test"], location="internal")
    _write_person(people_dir, "External", "Nina_Newco.md", "Nina Newco",
                  emails=["nina@newco.test"], location="external")
    _write_person(people_dir, "Internal", "Ian_Stay.md", "Ian Stay",
                  emails=["ian@newco.test"], location="internal")
    _write_person(people_dir, "Internal", "Una_Unknown.md", "Una Unknown")
    _write_person(people_dir, "Internal", "Colin_Collide.md", "Colin Collide",
                  emails=["colin@oldco.test"], location="internal")
    _write_person(people_dir, "External", "Colin_Collide.md", "Other Colin",
                  emails=["colin@vendor.test"], location="external")
    _write_person(people_dir, "External", "Rita_Relabel.md", "Rita Relabel",
                  emails=["rita@vendor.test"], location="unknown")
    _write_person(people_dir, "CPO_Network", "Cleo_Network.md", "Cleo Network",
                  emails=["cleo@oldco.test"], location="external")


def test_dry_run_returns_full_plan_and_mutates_nothing(tmp_path, monkeypatch):
    people_dir, index_file = _setup(tmp_path, monkeypatch)
    _fixture_vault(people_dir)
    before = _tree_bytes(tmp_path)

    result = work_server.reroute_people_data()

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["internal_domains"] == ["newco.test"]
    moves = {entry["path"]: entry for entry in result["moves"]}
    assert moves["People/Internal/Olivia_Oldco.md"]["target_path"] == "People/External/Olivia_Oldco.md"
    assert moves["People/Internal/Olivia_Oldco.md"]["recomputed_location"] == "external"
    assert moves["People/Internal/Olivia_Oldco.md"]["deciding_email"] == "olivia@oldco.test"
    assert moves["People/External/Nina_Newco.md"]["target_path"] == "People/Internal/Nina_Newco.md"
    assert moves["People/External/Nina_Newco.md"]["deciding_email"] == "nina@newco.test"
    assert len(moves) == 2
    # Ian Stay plus the External Colin page are already routed correctly.
    assert result["already_correct"] == 2
    assert [entry["path"] for entry in result["relabels"]] == ["People/External/Rita_Relabel.md"]
    assert [entry["path"] for entry in result["ambiguous"]] == ["People/Internal/Una_Unknown.md"]
    assert "no recorded emails" in result["ambiguous"][0]["reason"]
    assert [entry["path"] for entry in result["skipped"]] == ["People/Internal/Colin_Collide.md"]
    assert "already exists" in result["skipped"][0]["reason"]
    assert result["warnings"]
    # CPO_Network is a sibling folder the tool never evaluates.
    assert not any("Cleo" in entry.get("path", "") for entry in
                   result["moves"] + result["relabels"] + result["ambiguous"] + result["skipped"])
    # Dry run leaves every byte of the vault untouched, index included.
    assert _tree_bytes(tmp_path) == before
    assert not index_file.exists()


def test_apply_moves_pages_rewrites_frontmatter_and_rebuilds_index(tmp_path, monkeypatch):
    people_dir, index_file = _setup(tmp_path, monkeypatch)
    _fixture_vault(people_dir)

    result = work_server.reroute_people_data(dry_run=False)

    assert result["success"] is True
    assert result["dry_run"] is False
    assert result["applied"] == {"moved": 2, "relabeled": 1, "failed": 0}
    assert result["index_rebuilt"] is True

    # Ex-colleague moved Internal -> External; new-company contact the other way.
    assert not (people_dir / "Internal" / "Olivia_Oldco.md").exists()
    olivia = _frontmatter(people_dir / "External" / "Olivia_Oldco.md")
    assert olivia["location"] == "external"
    assert olivia["dex_last_written"]["location"] == "external"
    assert not (people_dir / "External" / "Nina_Newco.md").exists()
    nina = _frontmatter(people_dir / "Internal" / "Nina_Newco.md")
    assert nina["location"] == "internal"
    assert nina["dex_last_written"]["location"] == "internal"

    # Folder already right, stale frontmatter relabelled in place.
    rita = _frontmatter(people_dir / "External" / "Rita_Relabel.md")
    assert rita["location"] == "external"
    assert rita["dex_last_written"]["location"] == "external"

    # Collision skipped with a warning; neither Colin page overwritten.
    assert (people_dir / "Internal" / "Colin_Collide.md").exists()
    assert _frontmatter(people_dir / "External" / "Colin_Collide.md")["name"] == "Other Colin"

    # Ambiguous and sibling-folder pages untouched.
    assert (people_dir / "Internal" / "Una_Unknown.md").exists()
    assert (people_dir / "CPO_Network" / "Cleo_Network.md").exists()

    # The rebuilt index derives internal/external from the new folders.
    index = json.loads(index_file.read_text())
    types_by_name = {person["name"]: person["type"] for person in index["people"]}
    assert types_by_name["Olivia Oldco"] == "external"
    assert types_by_name["Nina Newco"] == "internal"
    assert types_by_name["Cleo Network"] == "cpo_network"


def test_refuses_without_configured_email_domain(tmp_path, monkeypatch):
    people_dir, _ = _setup(tmp_path, monkeypatch, domains=None)
    _write_person(people_dir, "Internal", "Olivia_Oldco.md", "Olivia Oldco",
                  emails=["olivia@oldco.test"], location="internal")

    result = work_server.reroute_people_data(dry_run=False)

    assert result["success"] is False
    assert "email_domain" in result["error"]
    assert (people_dir / "Internal" / "Olivia_Oldco.md").exists()


def test_explicit_domains_override_profile(tmp_path, monkeypatch):
    people_dir, _ = _setup(tmp_path, monkeypatch, domains="oldco.test")
    _write_person(people_dir, "Internal", "Olivia_Oldco.md", "Olivia Oldco",
                  emails=["olivia@oldco.test"], location="internal")

    profile_plan = work_server.reroute_people_data()
    override_plan = work_server.reroute_people_data(domains=["@newco.test"])
    empty_override = work_server.reroute_people_data(domains=["  "])

    assert profile_plan["moves"] == [] and profile_plan["already_correct"] == 1
    assert override_plan["internal_domains"] == ["newco.test"]
    assert [entry["path"] for entry in override_plan["moves"]] == ["People/Internal/Olivia_Oldco.md"]
    assert empty_override["success"] is False


def test_falls_back_to_last_written_mirror_emails(tmp_path, monkeypatch):
    people_dir, _ = _setup(tmp_path, monkeypatch)
    page = _write_person(people_dir, "Internal", "Mia_Mirror.md", "Mia Mirror",
                         emails=["mia@oldco.test"], location="internal")
    # User deleted the top-level emails line; the engine mirror still records it.
    page.write_text(page.read_text().replace('\nemails: ["mia@oldco.test"]\n', "\nemails: []\n", 1))

    plan = work_server.reroute_people_data()

    entry = plan["moves"][0]
    assert entry["path"] == "People/Internal/Mia_Mirror.md"
    assert entry["deciding_email"] == "mia@oldco.test"
    assert entry["email_source"] == "dex_last_written"


def test_unreadable_page_is_ambiguous_and_untouched(tmp_path, monkeypatch):
    people_dir, _ = _setup(tmp_path, monkeypatch)
    broken = people_dir / "External" / "Broken_Bytes.md"
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"\xff\xfe\x00 not a page")

    plan = work_server.reroute_people_data()

    assert plan["success"] is True
    assert [entry["path"] for entry in plan["ambiguous"]] == ["People/External/Broken_Bytes.md"]
    assert "could not be parsed" in plan["ambiguous"][0]["reason"]
    assert broken.read_bytes() == b"\xff\xfe\x00 not a page"


def test_user_owned_location_is_skipped_not_half_migrated(tmp_path, monkeypatch):
    people_dir, _ = _setup(tmp_path, monkeypatch)
    pinned = _write_person(people_dir, "Internal", "Pia_Pinned.md", "Pia Pinned",
                           emails=["pia@oldco.test"], location="internal")
    pinned.write_text(pinned.read_text().replace(
        "dex_pinned: {}", "dex_pinned:\n  location: user"
    ))
    drifted = _write_person(people_dir, "Internal", "Dana_Drift.md", "Dana Drift",
                            emails=["dana@oldco.test"], location="internal")
    drifted.write_text(drifted.read_text().replace(
        "\nlocation: internal\n", "\nlocation: unknown\n", 1
    ))
    before = _tree_bytes(tmp_path)

    result = work_server.reroute_people_data(dry_run=False)

    skipped = {entry["path"]: entry["reason"] for entry in result["skipped"]}
    assert "pinned" in skipped["People/Internal/Pia_Pinned.md"]
    assert "hand-edited" in skipped["People/Internal/Dana_Drift.md"]
    assert result["moves"] == []
    # Index rebuild aside, the pages themselves are untouched.
    assert (people_dir / "Internal" / "Pia_Pinned.md").read_bytes() == before["People/Internal/Pia_Pinned.md"]
    assert (people_dir / "Internal" / "Dana_Drift.md").read_bytes() == before["People/Internal/Dana_Drift.md"]


def test_obsidian_filename_links_survive_the_move(tmp_path, monkeypatch):
    people_dir, _ = _setup(tmp_path, monkeypatch)
    _write_person(people_dir, "Internal", "Olivia_Oldco.md", "Olivia Oldco",
                  emails=["olivia@oldco.test"], location="internal")
    note = tmp_path / "00-Inbox" / "Meetings" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text("Spoke with [[Olivia_Oldco]] about the handover.\n")

    result = work_server.reroute_people_data(dry_run=False)

    assert result["applied"]["moved"] == 1
    # Obsidian links resolve by filename: the note is untouched and a page
    # with the same filename still exists under People/.
    assert note.read_text() == "Spoke with [[Olivia_Oldco]] about the handover.\n"
    assert [path.name for path in people_dir.rglob("Olivia_Oldco.md")] == ["Olivia_Oldco.md"]
    assert (people_dir / "External" / "Olivia_Oldco.md").exists()
