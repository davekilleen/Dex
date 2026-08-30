"""Read-only open-item list for the unpublished connector box."""

from __future__ import annotations

from pathlib import Path

from core.context.person_context import (
    NONE_OPEN_SENTENCE,
    ask_what_is_still_open_with_people,
)


def _write_person(
    vault: Path,
    *,
    filename: str,
    name: str,
    body: str,
    subdir: str = "Internal",
) -> Path:
    folder = vault / "05-Areas" / "People" / subdir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_text(
        f"---\nname: {name}\nrole: Partner\ncompany: Example\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def test_list_names_each_unchecked_to_do_the_person_and_the_page(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    _write_person(
        vault,
        filename="Ada_Lovelace.md",
        name="Ada Lovelace",
        body="- [ ] Send the operating memo\n- [x] Done already\n",
    )
    _write_person(
        vault,
        filename="Charles_Babbage.md",
        name="Charles Babbage",
        body="- [ ] Review the engine notes\n",
        subdir="External",
    )
    payload = ask_what_is_still_open_with_people(vault)
    assert payload["found"] is True
    assert payload["sentence"] == ""
    assert payload["matches"] == [
        {
            "item": "Send the operating memo",
            "person": "Ada Lovelace",
            "page": "05-Areas/People/Internal/Ada_Lovelace.md",
        },
        {
            "item": "Review the engine notes",
            "person": "Charles Babbage",
            "page": "05-Areas/People/External/Charles_Babbage.md",
        },
    ]


def test_list_honest_sentence_when_nothing_is_open(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    _write_person(
        vault,
        filename="Ada_Lovelace.md",
        name="Ada Lovelace",
        body="- [x] Already sent the memo\n",
    )
    payload = ask_what_is_still_open_with_people(vault)
    assert payload["found"] is False
    assert payload["matches"] == []
    assert payload["sentence"] == NONE_OPEN_SENTENCE
    assert "No unchecked to-dos on person pages." == payload["sentence"]


def test_list_does_not_use_meetings_or_the_task_list(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    meetings = vault / "00-Inbox" / "Meetings"
    meetings.mkdir(parents=True)
    (meetings / "2026-04-12 - Pricing.md").write_text(
        "- [ ] Follow up with Ada about pricing\n",
        encoding="utf-8",
    )
    tasks = vault / "03-Tasks"
    tasks.mkdir(parents=True)
    (tasks / "Tasks.md").write_text(
        "- [ ] File the launch checklist\n",
        encoding="utf-8",
    )
    payload = ask_what_is_still_open_with_people(vault)
    assert payload["found"] is False
    assert payload["matches"] == []
    assert payload["sentence"] == NONE_OPEN_SENTENCE


def test_list_skips_symlinks_and_does_not_write(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text(
        "---\nname: Secret Person\n---\n\n- [ ] Do not leak this\n",
        encoding="utf-8",
    )
    folder = vault / "05-Areas" / "People" / "Internal"
    folder.mkdir(parents=True)
    (folder / "Secret_Person.md").symlink_to(outside)
    page = _write_person(
        vault,
        filename="Ada_Lovelace.md",
        name="Ada Lovelace",
        body="- [ ] Send the operating memo\n",
    )
    before = page.read_text(encoding="utf-8")
    payload = ask_what_is_still_open_with_people(vault)
    assert payload["found"] is True
    assert [row["person"] for row in payload["matches"]] == ["Ada Lovelace"]
    assert ask_what_is_still_open_with_people(None)["found"] is False
    assert ask_what_is_still_open_with_people(None)["sentence"] == NONE_OPEN_SENTENCE
    assert page.read_text(encoding="utf-8") == before
    assert outside.read_text(encoding="utf-8").startswith("---\nname: Secret Person")


def test_open_item_lookup_stays_local() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "core" / "context" / "person_context.py"
    ).read_text(encoding="utf-8")
    for needle in ("urllib", "requests", "http.client", "socket"):
        assert needle not in source
