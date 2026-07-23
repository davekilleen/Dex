from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core.entity_engine import Result
from core.mcp import work_server
from core.ritual_intelligence import contact_promote


def test_ritual_contact_creation_uses_engine_create_primitive(
    tmp_path: Path, monkeypatch
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE contacts (
            id TEXT PRIMARY KEY,
            name TEXT,
            email TEXT,
            domain TEXT,
            page_path TEXT,
            updated_at TEXT
        );
        CREATE TABLE contact_suggestions (
            contact_id TEXT,
            status TEXT,
            updated_at TEXT
        );
        INSERT INTO contacts
        VALUES ('contact-1', 'Pat Customer', 'pat@example.org', 'example.org', NULL, NULL);
        INSERT INTO contact_suggestions VALUES ('contact-1', 'suggested', NULL);
        """
    )
    people_dir = tmp_path / "People"
    calls = []

    def create(path, content, *, allowed_root=None):
        calls.append((Path(path), content, Path(allowed_root)))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding="utf-8")
        return Result("created", True, "fingerprint")

    monkeypatch.setattr(contact_promote, "PEOPLE_DIR", people_dir)
    monkeypatch.setattr(contact_promote, "get_internal_domains", lambda: set())
    monkeypatch.setattr(contact_promote, "create_page_if_absent", create, raising=False)

    result = contact_promote.create_contact_page(conn, "contact-1")

    assert result["status"] == "created"
    assert len(calls) == 1
    assert calls[0][0] == people_dir / "External" / "Pat_Customer.md"
    assert calls[0][2] == people_dir


def test_work_person_creation_uses_engine_create_primitive(
    tmp_path: Path, monkeypatch
) -> None:
    people_dir = tmp_path / "People"
    profile = tmp_path / "System" / "user-profile.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_text('email_domain: "example.com"\n', encoding="utf-8")
    calls = []

    def create(path, content, *, allowed_root=None):
        calls.append((Path(path), content, Path(allowed_root)))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding="utf-8")
        return Result("created", True, "fingerprint")

    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        work_server,
        "PEOPLE_INDEX_FILE",
        tmp_path / "System" / "People_Index.json",
    )
    monkeypatch.setattr(work_server, "USER_PROFILE_FILE", profile)
    monkeypatch.setattr(work_server, "get_people_dir", lambda: people_dir)
    monkeypatch.setattr(work_server, "create_page_if_absent", create, raising=False)

    result = work_server.create_person_data(
        "Engine Person",
        emails=["engine@example.com"],
    )

    assert result["success"] is True
    assert len(calls) == 1
    assert calls[0][0] == people_dir / "Internal" / "Engine_Person.md"
    assert calls[0][2] == people_dir


def test_work_company_creation_uses_engine_create_primitive(
    tmp_path: Path, monkeypatch
) -> None:
    companies_dir = tmp_path / "Companies"
    calls = []

    def create(path, content, *, allowed_root=None):
        calls.append((Path(path), content, Path(allowed_root)))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding="utf-8")
        return Result("created", True, "fingerprint")

    monkeypatch.setattr(work_server, "COMPANIES_DIR", companies_dir)
    monkeypatch.setattr(
        work_server.capability_rooms,
        "enabled",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(work_server, "create_page_if_absent", create, raising=False)

    result = work_server.create_company_page(
        "Engine Company",
        website="https://engine.example",
    )

    assert result["success"] is True
    assert len(calls) == 1
    assert calls[0][0] == companies_dir / "Engine_Company.md"
    assert calls[0][2] == companies_dir


def test_work_company_refresh_only_replaces_existing_sections_and_keeps_raw_footer(
    tmp_path: Path, monkeypatch
) -> None:
    companies_dir = tmp_path / "Companies"
    companies_dir.mkdir()
    page = companies_dir / "Acme.md"
    page.write_text(
        "# Acme\n\n"
        "## Key Contacts\n\nOld contacts\n\n"
        "## Notes\n\nUser note.\n\n"
        "*Created: 2026-01-01*\n"
        "*Updated: 2026-01-01*\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "COMPANIES_DIR", companies_dir)
    monkeypatch.setattr(work_server, "get_company_domains", lambda _path: ["acme.com"])
    monkeypatch.setattr(
        work_server,
        "find_people_at_company",
        lambda _name: [
            {
                "name": "Pat",
                "filepath": "People/Pat.md",
                "role": "Lead",
                "last_interaction": "2026-07-22",
            }
        ],
    )
    monkeypatch.setattr(
        work_server,
        "find_meetings_for_company",
        lambda _name, _domains: [
            {
                "date": "2026-07-22",
                "title": "Roadmap",
                "filepath": "Meetings/Roadmap.md",
            }
        ],
    )
    monkeypatch.setattr(
        work_server,
        "find_tasks_for_page",
        lambda _path: [
            {"completed": False, "title": "Follow up", "priority": "P1"}
        ],
    )
    monkeypatch.setattr(
        work_server,
        "_tz_now",
        lambda: datetime(2026, 7, 23, 14, 30, tzinfo=timezone.utc),
    )

    result = work_server.refresh_company_page("Acme.md")

    assert result["success"] is True
    text = page.read_text(encoding="utf-8")
    assert "User note." in text
    assert "| [Pat](People/Pat.md) | Lead | 2026-07-22 |" in text
    assert "## Meeting History" not in text
    assert "## Related Tasks" not in text
    assert "<!-- dex:auto:" not in text
    assert "*Created: 2026-01-01*" in text
    assert "*Updated: 2026-07-23 14:30*" in text
    assert "*Updated: 2026-01-01*" not in text
    assert text.count("*Created:") == 1
    assert text.count("*Updated:") == 2  # contacts timestamp plus page footer


def test_related_tasks_raw_writer_updates_quarantined_page_without_managed_markers(
    tmp_path: Path, monkeypatch
) -> None:
    page = tmp_path / "05-Areas" / "People" / "External" / "Pat.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\nname: [broken\n---\n# Pat\n\n## Notes\n\nUser note.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        work_server,
        "_tz_now",
        lambda: datetime(2026, 7, 23, 14, 30, tzinfo=timezone.utc),
    )

    changed = work_server.update_related_tasks_section(
        "05-Areas/People/External/Pat.md",
        [{"completed": False, "title": "Follow up", "priority": "P1"}],
    )

    assert changed is True
    text = page.read_text(encoding="utf-8")
    assert "User note." in text
    assert "| ⏳ | Follow up | P1 |" in text
    assert text.index("## Related Tasks") < text.index("## Notes")
    assert "<!-- dex:auto:" not in text


def test_related_tasks_raw_writer_follows_symlinked_project_ancestor(
    tmp_path: Path, monkeypatch
) -> None:
    projects = tmp_path / "04-Projects"
    actual = tmp_path / "project-pages"
    actual.mkdir()
    projects.symlink_to(actual, target_is_directory=True)
    page = projects / "Launch.md"
    page.write_text("# Launch\n\n## Notes\n\nUser note.\n", encoding="utf-8")

    monkeypatch.setattr(work_server, "_source_page_path", lambda _source: page)
    monkeypatch.setattr(
        work_server,
        "_tz_now",
        lambda: datetime(2026, 7, 23, 14, 30, tzinfo=timezone.utc),
    )

    changed = work_server.update_related_tasks_section(
        "04-Projects/Launch.md",
        [{"completed": False, "title": "Ship it", "priority": "P0"}],
    )

    assert changed is True
    assert "| ⏳ | Ship it | P0 |" in page.read_text(encoding="utf-8")
