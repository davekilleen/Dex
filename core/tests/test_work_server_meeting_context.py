"""Meeting-context behavior at the public Work MCP boundary."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.mcp import work_server
from core.utils.entity_pages import render_company_page


def _call_meeting_context(attendee: str) -> dict:
    result = asyncio.run(
        work_server.handle_call_tool(
            "get_meeting_context",
            {
                "meeting_title": "Reliability review",
                "attendees": [attendee],
            },
        )
    )
    return json.loads(result[0].text)


@pytest.fixture
def meeting_context_vault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Path]:
    people_dir = tmp_path / "05-Areas" / "People"
    companies_dir = tmp_path / "05-Areas" / "Companies"
    tasks_file = tmp_path / "03-Tasks" / "Tasks.md"
    cache_file = tmp_path / "System" / "Memory" / "meeting-cache.json"

    people_dir.mkdir(parents=True)
    companies_dir.mkdir(parents=True)
    tasks_file.parent.mkdir(parents=True)
    tasks_file.write_text("# Tasks\n", encoding="utf-8")

    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "get_people_dir", lambda: people_dir)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks_file)
    monkeypatch.setattr(work_server, "COMPANIES_DIR", companies_dir)
    monkeypatch.setattr(work_server, "MEETING_CACHE_FILE", cache_file)
    monkeypatch.setattr(work_server, "HAS_QMD", False)

    return {
        "people": people_dir,
        "tasks": tasks_file,
        "companies": companies_dir,
    }


def test_meeting_context_surfaces_open_items_from_the_attendee_page(
    meeting_context_vault: dict[str, Path],
) -> None:
    person = meeting_context_vault["people"] / "External" / "Ada_Lovelace.md"
    person.parent.mkdir(parents=True)
    person.write_text(
        "# Ada Lovelace\n\n"
        "## Action Items Involving Them\n\n"
        "- [ ] Send Ada the reliability brief ^task-20260827-001\n"
        "- [ ] {{Action item}}\n",
        encoding="utf-8",
    )

    result = _call_meeting_context("Ada Lovelace")

    assert result["outstanding_tasks"] == [
        {
            "title": "Send Ada the reliability brief",
            "related_to": "Ada Lovelace",
        }
    ]


def test_meeting_context_matches_underscored_person_links_in_the_task_list(
    meeting_context_vault: dict[str, Path],
) -> None:
    person = meeting_context_vault["people"] / "Internal" / "Ada_Lovelace.md"
    person.parent.mkdir(parents=True)
    person.write_text("# Ada Lovelace\n", encoding="utf-8")
    meeting_context_vault["tasks"].write_text(
        "# Tasks\n\n"
        "- [ ] Share the review with [[Ada_Lovelace]] ^task-20260827-002\n",
        encoding="utf-8",
    )

    result = _call_meeting_context("Ada Lovelace")

    assert result["outstanding_tasks"] == [
        {
            "title": "Share the review with [[Ada_Lovelace]]",
            "related_to": "Ada Lovelace",
        }
    ]


def test_meeting_context_ignores_non_open_task_lines_that_mention_an_attendee(
    meeting_context_vault: dict[str, Path],
) -> None:
    person = meeting_context_vault["people"] / "External" / "Ada_Lovelace.md"
    person.parent.mkdir(parents=True)
    person.write_text("# Ada Lovelace\n", encoding="utf-8")
    meeting_context_vault["tasks"].write_text(
        "# Tasks\n\n"
        "- [x] Closed item for [[Ada_Lovelace]] that mentions - [ ] a template\n"
        "Meeting notes for [[Ada_Lovelace]] mention - [ ] a possible follow-up\n",
        encoding="utf-8",
    )

    result = _call_meeting_context("Ada Lovelace")

    assert result["outstanding_tasks"] == []


def test_meeting_context_does_not_match_a_longer_underscored_person_name(
    meeting_context_vault: dict[str, Path],
) -> None:
    person = meeting_context_vault["people"] / "Internal" / "Chris_Kim.md"
    person.parent.mkdir(parents=True)
    person.write_text("# Chris Kim\n", encoding="utf-8")
    meeting_context_vault["tasks"].write_text(
        "# Tasks\n\n"
        "- [ ] Send the review to [[Chris_Kimball]] ^task-20260827-003\n",
        encoding="utf-8",
    )

    result = _call_meeting_context("Chris Kim")

    assert result["outstanding_tasks"] == []


def test_meeting_context_does_not_resolve_a_longer_person_page_name(
    meeting_context_vault: dict[str, Path],
) -> None:
    person = meeting_context_vault["people"] / "External" / "Chris_Kimball.md"
    person.parent.mkdir(parents=True)
    person.write_text(
        "# Chris Kimball\n\n- [ ] Send Chris Kimball the review\n",
        encoding="utf-8",
    )

    result = _call_meeting_context("Chris Kim")

    assert result["attendee_details"] == []
    assert result["outstanding_tasks"] == []


def test_get_company_domains_reads_frontmatter_not_notes(
    meeting_context_vault: dict[str, Path],
) -> None:
    company = meeting_context_vault["companies"] / "Northwind.md"
    company.write_text(
        render_company_page("Northwind", ["acme.com"]),
        encoding="utf-8",
    )
    company.write_text(
        company.read_text(encoding="utf-8")
        + "\nNotes mention partner.example.org and jane@acme.com.\n",
        encoding="utf-8",
    )

    assert work_server.get_company_domains(company) == ["acme.com"]


def test_get_company_domains_prefers_frontmatter_over_a_conflicting_table(
    meeting_context_vault: dict[str, Path],
) -> None:
    company = meeting_context_vault["companies"] / "Northwind.md"
    company.write_text(
        "---\n"
        "type: company\n"
        "name: Northwind\n"
        "domains: [\"acme.com\"]\n"
        "---\n"
        "# Northwind\n\n"
        "| Field | Value |\n"
        "|-------|-------|\n"
        "| **Domains** | partner.example.org |\n",
        encoding="utf-8",
    )

    assert work_server.get_company_domains(company) == ["acme.com"]


def test_get_company_domains_still_reads_a_legacy_domains_table(
    meeting_context_vault: dict[str, Path],
) -> None:
    company = meeting_context_vault["companies"] / "Legacy_Co.md"
    company.write_text(
        "# Legacy Co\n\n"
        "| Field | Value |\n"
        "|-------|-------|\n"
        "| **Domains** | acme.com, acme.org |\n",
        encoding="utf-8",
    )

    assert work_server.get_company_domains(company) == ["acme.com", "acme.org"]


def test_get_company_domains_reads_inline_bold_domains(
    meeting_context_vault: dict[str, Path],
) -> None:
    company = meeting_context_vault["companies"] / "Inline_Co.md"
    company.write_text(
        "# Inline Co\n\n**Domains:** acme.com\n",
        encoding="utf-8",
    )

    assert work_server.get_company_domains(company) == ["acme.com"]


def test_meeting_context_does_not_pin_a_company_from_a_body_mention(
    meeting_context_vault: dict[str, Path],
) -> None:
    distractor = meeting_context_vault["companies"] / "Aaa_Distractor.md"
    distractor.write_text(
        "# Distractor\n\n"
        "Notes from a call with jane@acme.com about a shared vendor.\n",
        encoding="utf-8",
    )

    result = _call_meeting_context("jane@acme.com")

    assert result["related_company"] is None


def test_meeting_context_pins_the_company_whose_frontmatter_domain_matches(
    meeting_context_vault: dict[str, Path],
) -> None:
    distractor = meeting_context_vault["companies"] / "Aaa_Distractor.md"
    distractor.write_text(
        render_company_page("Distractor", ["partner.example.org"]),
        encoding="utf-8",
    )
    distractor.write_text(
        distractor.read_text(encoding="utf-8")
        + "\nNotes mention jane@acme.com.\n",
        encoding="utf-8",
    )
    company = meeting_context_vault["companies"] / "Northwind.md"
    company.write_text(
        render_company_page("Northwind", ["acme.com"]),
        encoding="utf-8",
    )

    result = _call_meeting_context("Jane Doe <jane@acme.com>")

    assert result["related_company"]["name"] == "Northwind"
    assert result["related_company"]["domains"] == ["acme.com"]


def test_find_company_for_attendees_matches_a_registrable_subdomain(
    meeting_context_vault: dict[str, Path],
) -> None:
    company = meeting_context_vault["companies"] / "Northwind.md"
    company.write_text(
        render_company_page("Northwind", ["acme.co.uk"]),
        encoding="utf-8",
    )

    match = work_server.find_company_for_attendees(
        [],
        domains=["mail.acme.co.uk"],
    )

    assert match["name"] == "Northwind"
    assert match["domains"] == ["acme.co.uk"]


def test_find_company_for_attendees_does_not_pin_from_a_name_substring(
    meeting_context_vault: dict[str, Path],
) -> None:
    company = meeting_context_vault["companies"] / "Samsung.md"
    company.write_text(
        render_company_page("Samsung", ["samsung.example.org"]),
        encoding="utf-8",
    )

    assert work_server.find_company_for_attendees(["Sam"]) is None


def test_find_company_for_attendees_can_pin_an_exact_structured_name(
    meeting_context_vault: dict[str, Path],
) -> None:
    company = meeting_context_vault["companies"] / "Northwind.md"
    company.write_text(
        render_company_page("Northwind", ["northwind.example.org"]),
        encoding="utf-8",
    )

    match = work_server.find_company_for_attendees(["Northwind"])

    assert match["name"] == "Northwind"
    assert match["domains"] == ["northwind.example.org"]


def test_find_company_for_attendees_skips_an_empty_email_host(
    meeting_context_vault: dict[str, Path],
) -> None:
    company = meeting_context_vault["companies"] / "Northwind.md"
    company.write_text(
        render_company_page("Northwind", ["acme.com"]),
        encoding="utf-8",
    )

    assert work_server.find_company_for_attendees(["broken@"]) is None
    assert work_server.find_company_for_attendees(["Jane <jane@>"]) is None
    result = _call_meeting_context("broken@")
    assert result["related_company"] is None


def test_find_company_for_attendees_skips_consumer_mail_domains(
    meeting_context_vault: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    company = meeting_context_vault["companies"] / "Acme.md"
    company.write_text(
        render_company_page("Acme", ["acme.com"]),
        encoding="utf-8",
    )
    monkeypatch.setattr(work_server, "is_freemail", lambda _domain: True)

    assert work_server.find_company_for_attendees(["jane@acme.com"]) is None


def test_find_company_for_attendees_prefers_a_domain_hit_over_an_earlier_name(
    meeting_context_vault: dict[str, Path],
) -> None:
    named = meeting_context_vault["companies"] / "Aaa_Acme.md"
    named.write_text(
        render_company_page("Acme", ["partner.example.org"]),
        encoding="utf-8",
    )
    domain_hit = meeting_context_vault["companies"] / "Northwind.md"
    domain_hit.write_text(
        render_company_page("Northwind", ["acme.com"]),
        encoding="utf-8",
    )

    match = work_server.find_company_for_attendees(["jane@acme.com"])

    assert match["name"] == "Northwind"
