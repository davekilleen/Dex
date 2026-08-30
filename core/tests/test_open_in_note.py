"""Read-only still-open-in-a-note list for the unpublished connector box."""

from __future__ import annotations

from pathlib import Path

from core.context.person_context import (
    NONE_NOTE_OPEN_SENTENCE,
    NOTE_MISSING_SENTENCE,
    NOTE_REFUSED_SENTENCE,
    ask_what_is_still_open_in_note,
)


def _write_note(vault: Path, relative: str, body: str) -> Path:
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _fixture_body() -> str:
    return (
        "# Engine review\n\n"
        "- [ ] Send the **operating** memo\n"
        "- [x] Already filed the drawings\n"
        "- a prose bullet that is not a to-do\n"
        "- [ ] Book the follow-up\n"
    )


def test_list_returns_unchecked_lines_in_note_order_bold_stripped(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    note = _write_note(
        vault,
        "00-Inbox/Meetings/2026-08-30 - Engine review.md",
        _fixture_body(),
    )
    payload = ask_what_is_still_open_in_note(vault, note)
    assert payload["found"] is True
    assert payload["sentence"] == ""
    assert payload["items"] == [
        "Send the operating memo",
        "Book the follow-up",
    ]
    assert "Already filed the drawings" not in payload["items"]
    assert "a prose bullet that is not a to-do" not in payload["items"]


def test_checking_an_item_off_drops_it_and_restoring_returns_it(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    note = _write_note(
        vault,
        "04-Projects/Engine.md",
        _fixture_body(),
    )
    first = ask_what_is_still_open_in_note(vault, note)
    assert first["items"] == [
        "Send the operating memo",
        "Book the follow-up",
    ]
    note.write_text(
        "# Engine review\n\n"
        "- [x] Send the **operating** memo\n"
        "- [x] Already filed the drawings\n"
        "- a prose bullet that is not a to-do\n"
        "- [ ] Book the follow-up\n",
        encoding="utf-8",
    )
    checked = ask_what_is_still_open_in_note(vault, note)
    assert checked["found"] is True
    assert checked["items"] == ["Book the follow-up"]
    assert "Send the operating memo" not in checked["items"]
    note.write_text(_fixture_body(), encoding="utf-8")
    restored = ask_what_is_still_open_in_note(vault, note)
    assert restored["items"] == [
        "Send the operating memo",
        "Book the follow-up",
    ]


def test_stripped_unchecked_lines_get_none_sentence_exactly_once(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    note = _write_note(
        vault,
        "04-Projects/Engine.md",
        _fixture_body(),
    )
    named = ask_what_is_still_open_in_note(vault, note)
    assert named["found"] is True
    note.write_text(
        "# Engine\n\n"
        "- [x] Send the operating memo\n"
        "- [x] Already filed the drawings\n"
        "- a prose bullet that is not a to-do\n",
        encoding="utf-8",
    )
    payload = ask_what_is_still_open_in_note(vault, note)
    assert payload["found"] is False
    assert payload["items"] == []
    assert payload["sentence"] == NONE_NOTE_OPEN_SENTENCE
    assert payload["sentence"] == "That note has no unchecked to-dos."
    assert str(payload).count(NONE_NOTE_OPEN_SENTENCE) == 1


def test_path_outside_vault_is_refused_and_never_read(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    secret = "OUTSIDE-NOTE-SECRET-SHOULD-NEVER-BE-READ"
    outside = tmp_path / "outside.md"
    outside.write_text(f"# Secret\n\n- [ ] {secret}\n", encoding="utf-8")
    payload = ask_what_is_still_open_in_note(vault, outside)
    assert payload["found"] is False
    assert payload["items"] == []
    assert payload["sentence"] == NOTE_REFUSED_SENTENCE
    assert secret not in str(payload)
    assert outside.read_text(encoding="utf-8").startswith("# Secret")


def test_person_tree_path_is_refused(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    folder = vault / "05-Areas" / "People" / "Internal"
    folder.mkdir(parents=True)
    page = folder / "Ada_Lovelace.md"
    page.write_text(
        "---\nname: Ada Lovelace\n---\n\n- [ ] Send the operating memo\n",
        encoding="utf-8",
    )
    payload = ask_what_is_still_open_in_note(
        vault, "05-Areas/People/Internal/Ada_Lovelace.md"
    )
    assert payload["found"] is False
    assert payload["items"] == []
    assert payload["sentence"] == NOTE_REFUSED_SENTENCE
    assert page.read_text(encoding="utf-8").startswith("---")


def test_missing_file_gets_no_note_sentence(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    payload = ask_what_is_still_open_in_note(
        vault, "00-Inbox/Meetings/2026-08-30 - Missing.md"
    )
    assert payload["found"] is False
    assert payload["items"] == []
    assert payload["sentence"] == NOTE_MISSING_SENTENCE
    assert payload["sentence"] == "There is no note at that path in your Dex folder."


def test_binary_extension_is_refused(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    binary = vault / "00-Inbox" / "Meetings" / "photo.png"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-note")
    payload = ask_what_is_still_open_in_note(vault, "00-Inbox/Meetings/photo.png")
    assert payload["found"] is False
    assert payload["items"] == []
    assert payload["sentence"] == NOTE_REFUSED_SENTENCE


def test_symlinked_note_is_refused_and_never_followed(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    secret = "SYMLINK-TARGET-SECRET-SHOULD-NEVER-BE-READ"
    target = tmp_path / "outside-note.md"
    target.write_text(f"# Linked\n\n- [ ] {secret}\n", encoding="utf-8")
    meetings = vault / "00-Inbox" / "Meetings"
    meetings.mkdir(parents=True)
    link = meetings / "linked.md"
    link.symlink_to(target)
    payload = ask_what_is_still_open_in_note(vault, "00-Inbox/Meetings/linked.md")
    assert payload["found"] is False
    assert payload["items"] == []
    assert payload["sentence"] == NOTE_REFUSED_SENTENCE
    assert secret not in str(payload)
    assert target.read_text(encoding="utf-8").startswith("# Linked")
    assert link.is_symlink()
