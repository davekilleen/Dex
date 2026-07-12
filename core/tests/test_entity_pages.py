from __future__ import annotations

import json
from pathlib import Path

import yaml

from core import entity_maintenance
from core.utils.entity_pages import (
    parse_entity_page,
    render_company_page,
    render_person_page,
    replace_machine_region,
    replace_machine_region_in_file,
    upsert_frontmatter,
)

FIXTURES = Path(__file__).parent / "fixtures" / "entity_pages"


def test_parse_golden_fixtures() -> None:
    pages = sorted(FIXTURES.glob("[0-9][0-9]-*.md"))
    assert len(pages) >= 10
    for page in pages:
        expected = json.loads(page.with_suffix(".expected.json").read_text(encoding="utf-8"))
        assert parse_entity_page(page) == expected, page.name


def test_upsert_preserves_unknown_keys_and_is_idempotent(tmp_path: Path) -> None:
    page = tmp_path / "Person.md"
    page.write_text("---\ncustom: keep\nname: Old\n---\n\n# Human body\n", encoding="utf-8")
    page.chmod(0o640)

    assert upsert_frontmatter(
        page,
        {"type": "person", "name": "New", "emails": ["LOUD@EXAMPLE.COM"], "ignored": "no"},
    )
    first = page.read_bytes()
    assert not upsert_frontmatter(
        page,
        {"type": "person", "name": "New", "emails": ["LOUD@EXAMPLE.COM"]},
    )
    assert page.read_bytes() == first
    frontmatter = yaml.safe_load(page.read_text(encoding="utf-8").split("---", 2)[1])
    assert frontmatter["custom"] == "keep"
    assert frontmatter["emails"] == ["loud@example.com"]
    assert "ignored" not in frontmatter
    assert page.read_text(encoding="utf-8").endswith("---\n\n# Human body\n")
    assert page.stat().st_mode & 0o777 == 0o640


def test_upsert_dry_run_reports_change_without_writing(tmp_path: Path) -> None:
    page = tmp_path / "Person.md"
    page.write_text("# Person\n", encoding="utf-8")
    original = page.read_bytes()
    assert upsert_frontmatter(page, {"type": "person", "name": "Person"}, dry_run=True)
    assert page.read_bytes() == original


def test_existing_python_consumers_delegate_to_shared_contract(tmp_path: Path) -> None:
    from core.mcp.work_server import parse_person_page
    from core.utils.page_generators import generate_person_page

    legacy = tmp_path / "Legacy_Person.md"
    legacy.write_text(
        "# Legacy Person\n\n| **Company** | Acme |\n| **Role** | Lead |\n"
        "| **Email** | LEAD@EXAMPLE.COM |\n**Last interaction:** 2026-07-03\n",
        encoding="utf-8",
    )
    assert parse_person_page(legacy) == {
        "name": "Legacy Person",
        "filepath": str(legacy),
        "company": "Acme",
        "company_page": None,
        "role": "Lead",
        "email": "lead@example.com",
        "last_interaction": "2026-07-03",
    }
    assert generate_person_page(
        "Legacy_Person", role="Lead", company="Acme", email="LEAD@EXAMPLE.COM", notes="Known."
    ) == render_person_page(
        "Legacy Person", role="Lead", company="Acme", emails=["LEAD@EXAMPLE.COM"], notes="Known."
    )


def test_quarantined_page_refuses_upsert(tmp_path: Path) -> None:
    page = tmp_path / "Broken.md"
    original = "---\nname: [broken\n---\n# Broken\n**Company:** Legacy\n"
    page.write_text(original, encoding="utf-8")
    assert parse_entity_page(page)["quarantined"] is True
    assert upsert_frontmatter(page, {"type": "person"}) is False
    assert page.read_text(encoding="utf-8") == original


def test_render_golden_parity() -> None:
    person_input = json.loads((FIXTURES / "render-person.input.json").read_text(encoding="utf-8"))
    company_input = json.loads((FIXTURES / "render-company.input.json").read_text(encoding="utf-8"))
    assert render_person_page(**person_input) == (FIXTURES / "render-person.expected.md").read_text(
        encoding="utf-8"
    )
    assert render_company_page(**company_input) == (FIXTURES / "render-company.expected.md").read_text(
        encoding="utf-8"
    )


def test_replace_machine_region_and_atomic_file_write(tmp_path: Path) -> None:
    original = "Before\n<!-- dex:auto:items -->\nold\n<!-- /dex:auto -->\nAfter\n"
    expected = "Before\n<!-- dex:auto:items -->\nnew\nvalue\n<!-- /dex:auto -->\nAfter\n"
    assert replace_machine_region(original, "items", "new\nvalue\n") == expected

    page = tmp_path / "page.md"
    page.write_text(original, encoding="utf-8")
    assert replace_machine_region_in_file(page, "items", "new\nvalue")
    assert page.read_text(encoding="utf-8") == expected
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))


def test_upsert_atomic_write_leaves_no_temp_files(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text("# Page\n", encoding="utf-8")
    assert upsert_frontmatter(page, {"type": "person", "name": "Page", "emails": []})
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))


def test_normalize_walks_tmp_vault_and_reports_counts(tmp_path: Path, monkeypatch) -> None:
    people = tmp_path / "people"
    companies = tmp_path / "companies"
    people.mkdir()
    companies.mkdir()
    (people / "README.md").write_text("# Docs\n", encoding="utf-8")
    (people / "Legacy_Person.md").write_text(
        "# Legacy Person\n\n**Email:** PERSON@EXAMPLE.COM\n", encoding="utf-8"
    )
    (people / "Broken.md").write_text("---\nname: [broken\n---\n# Broken\n", encoding="utf-8")
    (companies / "Legacy_Co.md").write_text(
        "# Legacy Co\n\n**Website:** https://legacy.example\n", encoding="utf-8"
    )
    monkeypatch.setattr(entity_maintenance, "PEOPLE_DIR", people)
    monkeypatch.setattr(entity_maintenance, "COMPANIES_DIR", companies)

    dry_run = entity_maintenance.normalize(dry_run=True)
    assert dry_run == {"scanned": 3, "updated": 2, "unchanged": 0, "quarantined": 1, "skipped": 1}
    assert not (people / "Legacy_Person.md").read_text(encoding="utf-8").startswith("---")

    result = entity_maintenance.normalize()
    assert result == {"scanned": 3, "updated": 2, "unchanged": 0, "quarantined": 1, "skipped": 1}
    assert parse_entity_page(people / "Legacy_Person.md")["emails"] == ["person@example.com"]
    assert parse_entity_page(companies / "Legacy_Co.md")["type"] == "company"
    second = entity_maintenance.normalize()
    assert second["updated"] == 0
    assert second["unchanged"] == 2
