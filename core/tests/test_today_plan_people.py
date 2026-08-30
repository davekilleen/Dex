"""Read-only today's-plan people list for the unpublished connector box."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from core.context.person_context import (
    NONE_TODAY_PEOPLE_SENTENCE,
    ask_who_is_in_todays_plan,
)

TODAY = date(2026, 8, 30)


def _write_person(
    vault: Path,
    *,
    filename: str,
    name: str,
    body: str = "",
    role: str | None = "Partner",
    company: str | None = "Example",
    last_interaction: str | None = "2026-04-12",
    subdir: str = "Internal",
) -> Path:
    folder = vault / "05-Areas" / "People" / subdir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    lines = [f"name: {name}"]
    if role is not None:
        lines.append(f"role: {role}")
    if company is not None:
        lines.append(f"company: {company}")
    if last_interaction is not None:
        lines.append(f"last_interaction: {last_interaction}")
    front = "---\n" + "\n".join(lines) + "\n---\n"
    path.write_text(f"{front}\n{body}\n", encoding="utf-8")
    return path


def _write_plan(vault: Path, body: str, day: date = TODAY) -> Path:
    folder = vault / "00-Inbox" / "Daily_Plans"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day.strftime('%Y-%m-%d')}.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_list_names_each_person_in_plan_order_with_recorded_fields(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    _write_person(
        vault,
        filename="Ada_Lovelace.md",
        name="Ada Lovelace",
        role="Founder",
        company="Analytical Engines",
        last_interaction="2026-04-12",
        body="- [ ] Send the operating memo\n- [x] Done already\n",
    )
    _write_person(
        vault,
        filename="Charles_Babbage.md",
        name="Charles Babbage",
        role="Engineer",
        company="Difference Co",
        last_interaction="2026-04-01",
        body="- [ ] Review the engine notes\n- [ ] File the drawings\n",
        subdir="External",
    )
    _write_plan(
        vault,
        "# Daily Plan\n\n**Attendees:** Charles Babbage, Ada Lovelace\n",
    )
    payload = ask_who_is_in_todays_plan(vault, today=TODAY)
    assert payload["found"] is True
    assert payload["sentence"] == ""
    assert payload["matches"] == [
        {
            "person": "Charles Babbage",
            "role": "Engineer",
            "company": "Difference Co",
            "last_interaction": "2026-04-01",
            "open_items": ["Review the engine notes", "File the drawings"],
            "page": "05-Areas/People/External/Charles_Babbage.md",
        },
        {
            "person": "Ada Lovelace",
            "role": "Founder",
            "company": "Analytical Engines",
            "last_interaction": "2026-04-12",
            "open_items": ["Send the operating memo"],
            "page": "05-Areas/People/Internal/Ada_Lovelace.md",
        },
    ]


def test_missing_fields_stay_empty_and_are_never_guessed(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    _write_person(
        vault,
        filename="Ada_Lovelace.md",
        name="Ada Lovelace",
        role=None,
        company=None,
        last_interaction=None,
        body="- [x] Already sent the memo\n",
    )
    _write_plan(vault, "# Daily Plan\n\nPrep with [[Ada Lovelace]] before noon.\n")
    payload = ask_who_is_in_todays_plan(vault, today=TODAY)
    row = payload["matches"][0]
    assert payload["found"] is True
    assert row["person"] == "Ada Lovelace"
    assert row["role"] == ""
    assert row["company"] == ""
    assert row["last_interaction"] == ""
    assert row["open_items"] == []
    assert row["page"] == "05-Areas/People/Internal/Ada_Lovelace.md"
    blob = str(payload)
    assert "Unknown" not in blob
    assert "No role" not in blob


def test_honest_sentence_when_nobody_is_named(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    _write_person(
        vault,
        filename="Ada_Lovelace.md",
        name="Ada Lovelace",
        body="- [ ] Send the operating memo\n",
    )
    _write_plan(vault, "# Daily Plan\n\nFocus on the operating memo.\n")
    payload = ask_who_is_in_todays_plan(vault, today=TODAY)
    assert payload["found"] is False
    assert payload["matches"] == []
    assert payload["sentence"] == NONE_TODAY_PEOPLE_SENTENCE
    assert payload["sentence"] == "Nobody is named in today's plan."


def test_list_does_not_use_meetings_tasks_or_yesterday(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    _write_person(
        vault,
        filename="Ada_Lovelace.md",
        name="Ada Lovelace",
        body="- [ ] Send the operating memo\n",
    )
    meetings = vault / "00-Inbox" / "Meetings"
    meetings.mkdir(parents=True)
    (meetings / "2026-08-30 - Pricing.md").write_text(
        "**Attendees:** Ada Lovelace\n",
        encoding="utf-8",
    )
    tasks = vault / "03-Tasks"
    tasks.mkdir(parents=True)
    (tasks / "Tasks.md").write_text(
        "- [ ] Follow up with Ada Lovelace\n",
        encoding="utf-8",
    )
    _write_plan(
        vault,
        "# Daily Plan\n\n**Attendees:** Ada Lovelace\n",
        day=date(2026, 8, 29),
    )
    payload = ask_who_is_in_todays_plan(vault, today=TODAY)
    assert payload["found"] is False
    assert payload["matches"] == []
    assert payload["sentence"] == NONE_TODAY_PEOPLE_SENTENCE


def test_list_skips_symlinks_and_does_not_write(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    outside_person = tmp_path / "outside-person.md"
    outside_person.write_text(
        "---\nname: Secret Person\nrole: Hidden\n---\n",
        encoding="utf-8",
    )
    folder = vault / "05-Areas" / "People" / "Internal"
    folder.mkdir(parents=True)
    (folder / "Secret_Person.md").symlink_to(outside_person)
    page = _write_person(
        vault,
        filename="Ada_Lovelace.md",
        name="Ada Lovelace",
        body="- [ ] Send the operating memo\n",
    )
    outside_plan = tmp_path / "outside-plan.md"
    outside_plan.write_text("**Attendees:** Ada Lovelace\n", encoding="utf-8")
    plans = vault / "00-Inbox" / "Daily_Plans"
    plans.mkdir(parents=True)
    (plans / f"{TODAY.strftime('%Y-%m-%d')}.md").symlink_to(outside_plan)
    before = page.read_text(encoding="utf-8")
    payload = ask_who_is_in_todays_plan(vault, today=TODAY)
    assert payload["found"] is False
    assert payload["sentence"] == NONE_TODAY_PEOPLE_SENTENCE
    (plans / f"{TODAY.strftime('%Y-%m-%d')}.md").unlink()
    real_plan = _write_plan(vault, "**Attendees:** Ada Lovelace, Secret Person\n")
    payload = ask_who_is_in_todays_plan(vault, today=TODAY)
    assert payload["found"] is True
    assert [row["person"] for row in payload["matches"]] == ["Ada Lovelace"]
    assert ask_who_is_in_todays_plan(None)["found"] is False
    assert ask_who_is_in_todays_plan(None)["sentence"] == NONE_TODAY_PEOPLE_SENTENCE
    assert page.read_text(encoding="utf-8") == before
    assert real_plan.read_text(encoding="utf-8").startswith("**Attendees:**")
    assert outside_person.read_text(encoding="utf-8").startswith("---\nname: Secret Person")


def test_today_people_lookup_stays_local() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "core" / "context" / "person_context.py"
    ).read_text(encoding="utf-8")
    for needle in ("urllib", "requests", "http.client", "socket"):
        assert needle not in source
