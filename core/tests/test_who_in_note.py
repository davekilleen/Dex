"""Read-only who-is-named-in-a-note list for the unpublished connector box."""

from __future__ import annotations

from pathlib import Path

from core.context.person_context import (
    NONE_NOTE_PEOPLE_SENTENCE,
    NOTE_MISSING_SENTENCE,
    NOTE_REFUSED_SENTENCE,
    ask_who_is_named_in_note,
)


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


def _write_note(vault: Path, relative: str, body: str) -> Path:
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_list_names_each_person_in_note_order_with_recorded_fields(tmp_path: Path) -> None:
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
    _write_person(
        vault,
        filename="Grace_Hopper.md",
        name="Grace Hopper",
        role="Rear Admiral",
        company="Navy",
        last_interaction="2026-03-20",
        body="- [ ] Compile the compiler notes\n",
        subdir="External",
    )
    _write_person(
        vault,
        filename="Michael_Faraday.md",
        name="Michael Faraday",
        role="Scientist",
        company="Royal Institution",
        last_interaction="2026-02-01",
        body="- [ ] Unused person must not appear\n",
    )
    _write_person(
        vault,
        filename="Maya.md",
        name="Maya",
        role="Operator",
        company="Solo",
        last_interaction="2026-01-01",
        body="- [ ] Single-word prose must not match\n",
    )
    note = _write_note(
        vault,
        "00-Inbox/Meetings/2026-08-30 - Engine review.md",
        "# Engine review\n\n"
        "Walked [[Ada Lovelace]] through the memo.\n"
        "See also People/External/Charles_Babbage.md for the drawings.\n"
        "Grace Hopper will review the compiler notes.\n"
        "Maya asked a question in prose only.\n",
    )
    payload = ask_who_is_named_in_note(vault, note)
    assert payload["found"] is True
    assert payload["sentence"] == ""
    assert payload["matches"] == [
        {
            "person": "Ada Lovelace",
            "role": "Founder",
            "company": "Analytical Engines",
            "last_interaction": "2026-04-12",
            "open_items": ["Send the operating memo"],
            "page": "05-Areas/People/Internal/Ada_Lovelace.md",
        },
        {
            "person": "Charles Babbage",
            "role": "Engineer",
            "company": "Difference Co",
            "last_interaction": "2026-04-01",
            "open_items": ["Review the engine notes", "File the drawings"],
            "page": "05-Areas/People/External/Charles_Babbage.md",
        },
        {
            "person": "Grace Hopper",
            "role": "Rear Admiral",
            "company": "Navy",
            "last_interaction": "2026-03-20",
            "open_items": ["Compile the compiler notes"],
            "page": "05-Areas/People/External/Grace_Hopper.md",
        },
    ]
    named = [row["person"] for row in payload["matches"]]
    assert "Michael Faraday" not in named
    assert "Maya" not in named


def test_path_outside_vault_is_refused_and_never_read(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    _write_person(vault, filename="Ada_Lovelace.md", name="Ada Lovelace")
    secret = "OUTSIDE-NOTE-SECRET-SHOULD-NEVER-BE-READ"
    outside = tmp_path / "outside.md"
    outside.write_text(f"# Secret\n\n[[Ada Lovelace]] {secret}\n", encoding="utf-8")
    payload = ask_who_is_named_in_note(vault, outside)
    assert payload["found"] is False
    assert payload["matches"] == []
    assert payload["sentence"] == NOTE_REFUSED_SENTENCE
    assert secret not in str(payload)
    assert outside.read_text(encoding="utf-8").startswith("# Secret")


def test_person_tree_path_is_refused(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    page = _write_person(
        vault,
        filename="Ada_Lovelace.md",
        name="Ada Lovelace",
        body="- [ ] Send the operating memo\n",
    )
    payload = ask_who_is_named_in_note(vault, "05-Areas/People/Internal/Ada_Lovelace.md")
    assert payload["found"] is False
    assert payload["matches"] == []
    assert payload["sentence"] == NOTE_REFUSED_SENTENCE
    assert page.read_text(encoding="utf-8").startswith("---")


def test_missing_file_gets_no_note_sentence(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    _write_person(vault, filename="Ada_Lovelace.md", name="Ada Lovelace")
    payload = ask_who_is_named_in_note(
        vault, "00-Inbox/Meetings/2026-08-30 - Missing.md"
    )
    assert payload["found"] is False
    assert payload["matches"] == []
    assert payload["sentence"] == NOTE_MISSING_SENTENCE


def test_binary_extension_is_refused(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    _write_person(vault, filename="Ada_Lovelace.md", name="Ada Lovelace")
    binary = vault / "00-Inbox" / "Meetings" / "photo.png"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-note")
    payload = ask_who_is_named_in_note(vault, "00-Inbox/Meetings/photo.png")
    assert payload["found"] is False
    assert payload["matches"] == []
    assert payload["sentence"] == NOTE_REFUSED_SENTENCE


def test_stripped_names_get_nobody_named_sentence_exactly_once(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    _write_person(vault, filename="Ada_Lovelace.md", name="Ada Lovelace")
    note = _write_note(
        vault,
        "04-Projects/Engine.md",
        "# Engine\n\nPrep with [[Ada Lovelace]] before noon.\n",
    )
    named = ask_who_is_named_in_note(vault, note)
    assert named["found"] is True
    note.write_text("# Engine\n\nFocus on the operating memo.\n", encoding="utf-8")
    payload = ask_who_is_named_in_note(vault, note)
    assert payload["found"] is False
    assert payload["matches"] == []
    assert payload["sentence"] == NONE_NOTE_PEOPLE_SENTENCE
    assert payload["sentence"] == "That note does not name anyone from your person pages."
    assert str(payload).count(NONE_NOTE_PEOPLE_SENTENCE) == 1


def test_symlinked_note_is_refused_and_never_followed(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    _write_person(vault, filename="Ada_Lovelace.md", name="Ada Lovelace")
    secret = "SYMLINK-TARGET-SECRET-SHOULD-NEVER-BE-READ"
    target = tmp_path / "outside-note.md"
    target.write_text(f"# Linked\n\n[[Ada Lovelace]] {secret}\n", encoding="utf-8")
    meetings = vault / "00-Inbox" / "Meetings"
    meetings.mkdir(parents=True)
    link = meetings / "linked.md"
    link.symlink_to(target)
    payload = ask_who_is_named_in_note(vault, "00-Inbox/Meetings/linked.md")
    assert payload["found"] is False
    assert payload["matches"] == []
    assert payload["sentence"] == NOTE_REFUSED_SENTENCE
    assert secret not in str(payload)
    assert target.read_text(encoding="utf-8").startswith("# Linked")
    assert link.is_symlink()
