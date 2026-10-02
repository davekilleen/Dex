"""UTF-8 I/O must not use the locale codec or truncate on a failed write."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.utils import text_io


ORIGINAL = "# Tasks\n\n## 📝 Notes\nKeep this.\n"
EMOJI = "📝"


def test_read_text_decodes_utf8_under_windows_locale(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "notes.md"
    path.write_bytes(ORIGINAL.encode("utf-8"))
    monkeypatch.setattr("locale.getpreferredencoding", lambda _do_setlocale=True: "cp1252")

    assert EMOJI in text_io.read_text(path)


def test_read_text_keeps_existing_path_when_os_name_is_windows(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "notes.md"
    path.write_text("hello\n", encoding="utf-8")
    monkeypatch.setattr(text_io.os, "name", "nt")

    assert text_io.read_text(path) == "hello\n"


def test_read_text_strips_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_bytes(b"\xef\xbb\xbf# Hello\n")

    assert text_io.read_text(path) == "# Hello\n"


def test_write_text_encodes_utf8_under_windows_locale(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "notes.md"
    monkeypatch.setattr("locale.getpreferredencoding", lambda _do_setlocale=True: "cp1252")

    text_io.write_text(path, ORIGINAL)

    assert path.read_bytes() == ORIGINAL.encode("utf-8")


def test_failed_encode_does_not_truncate_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "Tasks.md"
    path.write_text(ORIGINAL, encoding="utf-8")

    with pytest.raises(UnicodeEncodeError):
        text_io.write_text(path, ORIGINAL, encoding="ascii")

    assert path.read_text(encoding="utf-8") == ORIGINAL


def test_failed_replace_does_not_truncate_existing_file(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "Tasks.md"
    path.write_text(ORIGINAL, encoding="utf-8")

    def boom(_source, _dest):
        raise OSError("disk full")

    monkeypatch.setattr(text_io.os, "replace", boom)

    with pytest.raises(OSError, match="disk full"):
        text_io.write_text(path, "# emptied\n")

    assert path.read_text(encoding="utf-8") == ORIGINAL
    leftovers = list(tmp_path.glob(".Tasks.md.*.tmp"))
    assert leftovers == []


def test_write_text_preserves_existing_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "Tasks.md"
    crlf = "# Tasks\r\n\r\n- [ ] Keep CRLF\r\n"

    text_io.write_text(path, crlf)

    assert path.read_bytes() == crlf.encode("utf-8")
