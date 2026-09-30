"""I-owe and waiting-on dates cannot share one overdue meaning."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from core.action_dates import (
    I_OWE_DATE_FIELD,
    WAITING_ON_DATE_FIELD,
    action_date_kind,
    classify_action_date,
    is_owed_overdue,
    is_waiting_stale,
    read_ambiguous_action_date,
)
from core.entity_engine.contract import PERSON_FIELDS, parse_entity_page

TODAY = date(2026, 9, 30)


def test_person_fields_keep_the_two_dates_separate() -> None:
    assert I_OWE_DATE_FIELD in PERSON_FIELDS
    assert WAITING_ON_DATE_FIELD in PERSON_FIELDS
    assert "next_action_date" not in PERSON_FIELDS


def test_next_action_date_is_never_owed_or_waiting() -> None:
    assert action_date_kind("next_action_date") == "ambiguous"
    assert action_date_kind("Next Action Date") == "ambiguous"
    assert classify_action_date("next_action_date", "2026-01-01", today=TODAY) == "ambiguous"


def test_only_i_owe_date_can_be_overdue() -> None:
    owed = {I_OWE_DATE_FIELD: "2026-09-01", WAITING_ON_DATE_FIELD: "2026-09-01"}
    assert is_owed_overdue(owed, today=TODAY) is True
    assert is_waiting_stale(owed, today=TODAY) is True
    assert classify_action_date(WAITING_ON_DATE_FIELD, "2026-09-01", today=TODAY) == "waiting_stale"
    assert classify_action_date(I_OWE_DATE_FIELD, "2026-10-05", today=TODAY) == "owed_due"


def test_a_lone_next_action_date_is_not_overdue() -> None:
    record = {"next_action_date": "2026-01-01"}
    assert is_owed_overdue(record, today=TODAY) is False
    assert is_waiting_stale(record, today=TODAY) is False
    assert classify_action_date("next_action_date", "2026-01-01", today=TODAY) == "ambiguous"


def test_parser_reads_the_split_dates_and_ignores_invalid_ones(tmp_path: Path) -> None:
    page = tmp_path / "Alex_Person.md"
    page.write_text(
        "---\n"
        "type: person\n"
        "name: Alex Person\n"
        "i_owe_date: 2026-10-02\n"
        "waiting_on_date: 2026-10-08\n"
        "next_action_date: 2026-01-01\n"
        "---\n"
        "# Alex Person\n",
        encoding="utf-8",
    )
    parsed = parse_entity_page(page)
    assert parsed["i_owe_date"] == "2026-10-02"
    assert parsed["waiting_on_date"] == "2026-10-08"
    assert "next_action_date" not in parsed or parsed.get("next_action_date") is None

    page.write_text(
        "# Alex Person\n\n"
        "**I owe this:** 2026-10-02\n"
        "**Waiting on them:** not-a-date\n",
        encoding="utf-8",
    )
    parsed = parse_entity_page(page)
    assert parsed["i_owe_date"] == "2026-10-02"
    assert parsed["waiting_on_date"] is None


def test_read_ambiguous_action_date_from_page_text() -> None:
    assert read_ambiguous_action_date("next_action_date: 2026-04-01\n") == "2026-04-01"
    assert read_ambiguous_action_date("i_owe_date: 2026-04-01\n") is None
