from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
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
ROOT = Path(__file__).parents[2]


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
    assert "dex_pinned" not in frontmatter
    assert "dex_last_written" not in frontmatter
    assert page.read_text(encoding="utf-8").endswith("---\n\n# Human body\n")
    assert page.stat().st_mode & 0o777 == 0o640


def test_upsert_list_fields_are_byte_identical_across_twins(tmp_path: Path) -> None:
    original = "---\ncustom: keep\n---\n# Entity\n"
    fields = {
        "emails": ["A@EXAMPLE.COM"],
        "aliases": ["Alias"],
        "domains": ["EXAMPLE.COM"],
    }
    python_page = tmp_path / "python.md"
    javascript_page = tmp_path / "javascript.md"
    python_page.write_text(original, encoding="utf-8")
    javascript_page.write_text(original, encoding="utf-8")

    assert upsert_frontmatter(python_page, fields)
    subprocess.run(
        [
            "node",
            "-e",
            (
                "const { upsertFrontmatter } = require(process.argv[1]);"
                "upsertFrontmatter(process.argv[2], JSON.parse(process.argv[3]));"
            ),
            str(ROOT / ".scripts" / "lib" / "entity-pages.cjs"),
            str(javascript_page),
            json.dumps(fields),
        ],
        cwd=ROOT,
        check=True,
    )

    assert javascript_page.read_bytes() == python_page.read_bytes()


def test_upsert_pins_diverged_field_and_keeps_other_fields_live(tmp_path: Path) -> None:
    page = tmp_path / "Person.md"
    page.write_text(
        "---\n"
        "type: person\n"
        "name: Jane Doe\n"
        "role: User-authored role\n"
        "company: Old Co\n"
        "dex_last_written:\n"
        "  type: person\n"
        "  name: Jane Doe\n"
        "  role: Dex role\n"
        "  company: Old Co\n"
        "---\n"
        "# Jane Doe\n",
        encoding="utf-8",
    )

    fields = {
        "role": "New Dex role",
        "company": "New Co",
        "last_touched": "2026-07-22T12:00:00Z",
        "touches": [{"ts": "2026-07-22T12:00:00Z", "type": "meeting"}],
    }
    assert upsert_frontmatter(page, fields)
    first = page.read_bytes()
    frontmatter = yaml.safe_load(page.read_text(encoding="utf-8").split("---", 2)[1])
    assert frontmatter["role"] == "User-authored role"
    assert frontmatter["dex_pinned"] == {"role": "user"}
    assert frontmatter["dex_last_written"]["role"] == "Dex role"
    assert frontmatter["company"] == "New Co"
    assert frontmatter["dex_last_written"]["company"] == "New Co"
    assert frontmatter["last_touched"] == "2026-07-22T12:00:00Z"
    assert frontmatter["touches"] == [{"ts": "2026-07-22T12:00:00Z", "type": "meeting"}]

    assert not upsert_frontmatter(page, fields)
    assert page.read_bytes() == first


def test_upsert_never_overwrites_explicitly_pinned_field(tmp_path: Path) -> None:
    page = tmp_path / "Person.md"
    page.write_text(
        "---\nrole: Founder\ncompany: Old Co\ndex_pinned: {role: user}\n---\n# Person\n",
        encoding="utf-8",
    )
    assert upsert_frontmatter(page, {"role": "CEO", "company": "New Co"})
    frontmatter = yaml.safe_load(page.read_text(encoding="utf-8").split("---", 2)[1])
    assert frontmatter["role"] == "Founder"
    assert frontmatter["company"] == "New Co"


def test_upsert_preserves_malformed_v2_metadata_without_enabling_ownership(tmp_path: Path) -> None:
    page = tmp_path / "Person.md"
    page.write_text(
        "---\ncompany: Old Co\ndex_pinned: [role]\n---\n# Person\n", encoding="utf-8"
    )
    assert upsert_frontmatter(page, {"company": "New Co"})
    frontmatter = yaml.safe_load(page.read_text(encoding="utf-8").split("---", 2)[1])
    assert frontmatter["company"] == "New Co"
    assert frontmatter["dex_pinned"] == ["role"]
    assert "dex_last_written" not in frontmatter


def test_first_v2_write_conservatively_pins_legacy_facts(tmp_path: Path) -> None:
    page = tmp_path / "Legacy.md"
    page.write_text(
        "# User Name\n\n**Role:** User-authored role\n**Company:** Old Co\n", encoding="utf-8"
    )
    fields = {
        "type": "person",
        "name": "Incoming Name",
        "role": "Incoming role",
        "company": "New Co",
        "last_touched": "2026-07-22T12:00:00Z",
    }
    assert upsert_frontmatter(page, fields)
    frontmatter = yaml.safe_load(page.read_text(encoding="utf-8").split("---", 2)[1])
    assert frontmatter["dex_pinned"] == {
        "role": "user",
        "company": "user",
    }
    assert parse_entity_page(page)["name"] == "Incoming Name"
    assert parse_entity_page(page)["type"] == "person"
    assert parse_entity_page(page)["role"] == "User-authored role"
    assert parse_entity_page(page)["company"] == "Old Co"
    assert frontmatter["last_touched"] == "2026-07-22T12:00:00Z"
    first = page.read_bytes()
    assert not upsert_frontmatter(page, fields)
    assert page.read_bytes() == first


def test_first_v2_write_pins_nonempty_raw_values_before_canonical_validation(
    tmp_path: Path,
) -> None:
    cases = (
        (
            "location",
            "---\nlocation: London\n---\n# Person\n",
            {"location": "external", "last_touched": "2026-07-22T12:00:00Z"},
            "London",
        ),
        (
            "last_interaction",
            "# Person\n\n**Last interaction:** last summer\n",
            {"last_interaction": "2026-07-22", "last_touched": "2026-07-22T12:00:00Z"},
            "**Last interaction:** last summer",
        ),
        (
            "type",
            "# Person\n\n| **type** | colleague |\n",
            {"type": "person", "last_touched": "2026-07-22T12:00:00Z"},
            "| **type** | colleague |",
        ),
    )

    for field, original, fields, raw_value in cases:
        page = tmp_path / f"Legacy-{field}.md"
        page.write_text(original, encoding="utf-8")

        assert upsert_frontmatter(page, fields)
        updated = page.read_text(encoding="utf-8")
        frontmatter = yaml.safe_load(updated.split("---", 2)[1])

        assert frontmatter["dex_pinned"][field] == "user"
        if field == "location":
            assert frontmatter[field] == raw_value
        else:
            assert field not in frontmatter
            assert raw_value in updated


def test_upsert_dry_run_reports_change_without_writing(tmp_path: Path) -> None:
    page = tmp_path / "Person.md"
    page.write_text("# Person\n", encoding="utf-8")
    original = page.read_bytes()
    assert upsert_frontmatter(page, {"type": "person", "name": "Person"}, dry_run=True)
    assert page.read_bytes() == original


def test_upsert_legacy_empty_and_bom_pages_are_safe_and_idempotent(tmp_path: Path) -> None:
    legacy = tmp_path / "Legacy.md"
    legacy_body = "# Legacy\n\n**Role:** Human-authored role\n"
    legacy.write_text(legacy_body, encoding="utf-8")
    assert upsert_frontmatter(legacy, {"type": "person", "name": "Legacy"})
    assert legacy.read_text(encoding="utf-8").endswith(legacy_body)
    legacy_first = legacy.read_bytes()
    assert not upsert_frontmatter(legacy, {"type": "person", "name": "Legacy"})
    assert legacy.read_bytes() == legacy_first

    empty = tmp_path / "Empty.md"
    empty.write_bytes(b"")
    assert upsert_frontmatter(empty, {"type": "person", "name": "Empty"})
    empty_first = empty.read_bytes()
    assert not upsert_frontmatter(empty, {"type": "person", "name": "Empty"})
    assert empty.read_bytes() == empty_first

    bom = tmp_path / "Bom.md"
    bom.write_bytes(b"\xef\xbb\xbf---\nname: Old\n---\n# Old\n")
    assert upsert_frontmatter(bom, {"type": "person", "name": "New"})
    assert bom.read_bytes().startswith(b"\xef\xbb\xbf")
    bom_first = bom.read_bytes()
    assert not upsert_frontmatter(bom, {"type": "person", "name": "New"})
    assert bom.read_bytes() == bom_first


def test_existing_python_consumers_delegate_to_shared_contract(tmp_path: Path) -> None:
    import core.entity_engine as entity_engine
    import core.utils.entity_pages as entity_pages_shim
    from core.mcp.work_server import parse_person_page
    from core.utils.page_generators import generate_person_page

    assert entity_pages_shim.mutate_page is entity_engine.mutate_page
    assert entity_pages_shim.render_person_page is entity_engine.render_person_page

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
    person = render_person_page(**person_input)
    company = render_company_page(**company_input)
    assert person.index("## Relationships") < person.index("## Update Log")
    assert company.index("## Relationships") < company.index("## Update Log")


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


def test_compatibility_writers_raise_when_page_is_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing.md"

    with pytest.raises(FileNotFoundError):
        upsert_frontmatter(missing, {"type": "person"})
    with pytest.raises(FileNotFoundError):
        replace_machine_region_in_file(missing, "items", "new")


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
