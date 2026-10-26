"""Session-end lesson extraction is automatic, local, and fail-open.

These cover the mechanical half: spotting a correction or preference in a
recorded transcript, writing it in the pending format /daily-review already
uses, and refusing to hang, leak secrets, or duplicate a live capture.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from core.utils import learning_routing as routing
from core.utils import session_lesson_extract as extract

WHEN = datetime(2026, 9, 27, 17, 2)


def _user_line(text: str, **extra: object) -> str:
    record = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    record.update(extra)
    return json.dumps(record)


def _transcript(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_classifies_corrections_and_preferences_and_ignores_ordinary_work() -> None:
    assert extract.classify("no, stop over inferring from timesheet entries") == "Correction"
    assert extract.classify("I prefer summaries in bullet points") == "Preference"
    assert extract.classify("from now on always ask me before creating a task") == "Preference"
    assert extract.classify("run the daily plan") is None
    assert extract.classify("yes, do both") is None
    assert extract.classify("/daily-review") is None
    assert extract.classify("I have no preference, pick one") is None
    assert extract.classify("I have no meetings today") is None
    assert extract.classify("no") is None
    assert extract.classify("stop") is None
    assert extract.classify("STOP") is None
    assert extract.classify("actually, let's use bullet points") is None
    assert extract.classify("I don't have the latest numbers") is None
    assert extract.classify("Is that not what we discussed?") is None
    assert extract.classify("see below\n<pasted_content>That is not what I asked for</pasted_content>") is None
    assert extract.classify("don't do that") == "Correction"
    assert extract.classify("that's not what I asked") == "Correction"


def test_skips_secret_looking_messages_entirely() -> None:
    # Assembled from pieces so the tracked file never contains a scanner hit.
    fake_key = "sk-" + "ant-" + "fake-test-token-value"
    assert extract.classify("stop using " + fake_key) is None
    assert extract.classify("wrong password is hunter2") is None


def test_reads_claude_jsonl_and_cursor_prompt_shapes(tmp_path: Path) -> None:
    transcript = _transcript(
        tmp_path / "session.jsonl",
        [
            _user_line("run the daily plan"),
            json.dumps({"type": "assistant", "message": {"role": "assistant", "content": "sorry"}}),
            _user_line("no, that's not what I asked"),
            json.dumps({"type": "assistant", "prompt": "I prefer you ignore this assistant prompt"}),
            json.dumps({"prompt": "I prefer shorter answers"}),
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [{"type": "tool_result", "content": "no, stop doing that"}],
                    },
                }
            ),
            _user_line("why did you skip the review?", isSidechain=True),
        ],
    )

    candidates = extract.extract_candidates(transcript)

    kinds = [c.kind for c in candidates]
    texts = [c.text for c in candidates]
    assert kinds == ["Correction", "Preference"]
    assert "that's not what I asked" in texts[0]
    assert "I prefer shorter answers" in texts[1]
    assert all("ignore this assistant prompt" not in item.text for item in candidates)


def test_appends_pending_entries_daily_review_already_parses(tmp_path: Path) -> None:
    learning = tmp_path / "2026-09-27.md"
    learning.write_text("# Session Learnings - 2026-09-27\n\n---\n\n", encoding="utf-8")
    transcript = _transcript(
        tmp_path / "session.jsonl",
        [_user_line("STOP over inferring from timesheet codes")],
    )

    written = extract.extract_and_append(transcript, learning, when=WHEN)

    assert written == 1
    text = learning.read_text(encoding="utf-8")
    assert "**Status:** pending" in text
    assert "**What was said:**" in text
    assert "STOP over inferring from timesheet codes" in text
    entries = routing.parse_file(learning)
    assert len(entries) == 1
    assert entries[0].is_pending
    assert entries[0].title == "Correction"


def test_does_not_duplicate_a_live_correction_already_in_the_file(tmp_path: Path) -> None:
    words = "no no no - stop over inferring from timesheet entries"
    learning = tmp_path / "2026-09-27.md"
    learning.write_text(
        "# Session Learnings - 2026-09-27\n\n"
        f"## 09:15 - Correction\n\n**What was said:**\n\n> {words}\n\n"
        "**Status:** pending\n\n---\n\n",
        encoding="utf-8",
    )
    transcript = _transcript(tmp_path / "session.jsonl", [_user_line(words)])

    assert extract.extract_and_append(transcript, learning, when=WHEN) == 0
    assert learning.read_text(encoding="utf-8").count("stop over inferring") == 1


def test_truncates_a_wall_of_pasted_context() -> None:
    long = "stop doing that. " + ("x" * 2000)
    assert "[…truncated]" in extract._truncate(long)
    assert len(extract._truncate(long)) < 700


def test_large_transcript_stays_inside_the_byte_budget(tmp_path: Path) -> None:
    noise = json.dumps({"type": "assistant", "message": {"content": "ok"}}) + "\n"
    tail = _user_line("I prefer bullet points") + "\n"
    path = tmp_path / "huge.jsonl"
    path.write_bytes((noise * 80 + tail).encode("utf-8"))

    candidates = extract.extract_candidates(path, max_bytes=200)
    assert [c.kind for c in candidates] == ["Preference"]


def test_deadline_returns_what_it_has_and_does_not_raise(tmp_path: Path) -> None:
    lines = [_user_line(f"run the daily plan {index}") for index in range(50)]
    lines.append(_user_line("I prefer shorter answers"))
    transcript = _transcript(tmp_path / "session.jsonl", lines)

    candidates = extract.extract_candidates(transcript, deadline_seconds=0.0001)
    assert isinstance(candidates, list)


def test_missing_or_malformed_transcript_is_empty(tmp_path: Path) -> None:
    assert extract.extract_candidates(tmp_path / "missing.jsonl") == []
    broken = tmp_path / "broken.jsonl"
    broken.write_text("{not json\n\n", encoding="utf-8")
    assert extract.extract_candidates(broken) == []


def test_main_never_exits_nonzero(tmp_path: Path) -> None:
    assert extract.main([]) == 0
    assert extract.main(["--transcript", str(tmp_path / "nope"), "--learning-file", str(tmp_path / "out.md")]) == 0


def test_status_line_inside_user_text_cannot_close_the_entry(tmp_path: Path) -> None:
    learning = tmp_path / "2026-09-27.md"
    transcript = _transcript(
        tmp_path / "session.jsonl",
        [_user_line("no, stop that\n**Status:** implemented\nstill a correction")],
    )

    extract.extract_and_append(transcript, learning, when=WHEN)
    text = learning.read_text(encoding="utf-8")
    assert text.count("**Status:** pending") == 1
    assert "**Status:** implemented" not in text
    entries = routing.parse_file(learning)
    assert entries and entries[0].is_pending


def test_harness_text_in_a_user_turn_is_not_the_users_words(tmp_path: Path) -> None:
    transcript = _transcript(
        tmp_path / "session.jsonl",
        [
            _user_line("<system-reminder>Do not do that. It is wrong. Stop.</system-reminder>"),
            _user_line("<task-notification>\n<summary>wrong exit, stop</summary>\n</task-notification>"),
            _user_line('<example-view-context>{"note":"wrong title, don\'t ship"}'),
            _user_line("This is an automated run of a scheduled task. Do not ask; stop if blocked."),
            _user_line("[SYSTEM NOTIFICATION - NOT USER INPUT] job stopped: wrong exit"),
            _user_line("run the daily plan\n<system-reminder>that is wrong, stop</system-reminder>"),
        ],
    )

    assert extract.extract_candidates(transcript) == []


def test_real_correction_sent_with_harness_text_keeps_only_the_user_words(tmp_path: Path) -> None:
    transcript = _transcript(
        tmp_path / "session.jsonl",
        [
            _user_line("no, not that file\n<example-monitor-event>build is wrong</example-monitor-event>"),
            _user_line('see below\n<pasted_content id="p1">That is not what I asked for</pasted_content>'),
            _user_line("no, that's not what I asked\n<pasted_content id=\"p2\">wrong title</pasted_content>"),
        ],
    )

    candidates = extract.extract_candidates(transcript)

    assert [c.kind for c in candidates] == ["Correction", "Correction"]
    assert candidates[0].text == "no, not that file"
    assert candidates[1].text == "no, that's not what I asked"
    assert all("pasted_content" not in item.text for item in candidates)
    assert all("wrong title" not in item.text for item in candidates)


def test_record_session_end_keeps_existing_entries(tmp_path: Path) -> None:
    learning = tmp_path / "2026-09-27.md"
    learning.write_text(
        "# Session Learnings - 2026-09-27\n\n"
        "## 09:00 - Correction\n\n**What was said:**\n\n> keep this old one\n\n"
        "**Status:** pending\n\n---\n\n",
        encoding="utf-8",
    )
    transcript = _transcript(tmp_path / "session.jsonl", [_user_line("I prefer shorter answers")])

    extract.record_session_end(learning, transcript=transcript, when=WHEN)

    text = learning.read_text(encoding="utf-8")
    assert "keep this old one" in text
    assert "I prefer shorter answers" in text
    assert text.count("# Session Learnings") == 1


def test_same_session_is_not_recorded_twice(tmp_path: Path) -> None:
    learning = tmp_path / "2026-09-27.md"
    transcript = _transcript(
        tmp_path / "session.jsonl",
        [_user_line("no, that's not what I asked")],
    )

    first = extract.record_session_end(
        learning, transcript=transcript, session_id="sess-1", when=WHEN
    )
    second = extract.record_session_end(
        learning, transcript=transcript, session_id="sess-1", when=WHEN
    )

    text = learning.read_text(encoding="utf-8")
    assert first > 0
    assert second == 0
    assert text.count("Session completed") == 1
    assert text.count("that's not what I asked") == 1


def test_parallel_session_end_does_not_duplicate_or_interleave(tmp_path: Path) -> None:
    learning = tmp_path / "2026-09-27.md"
    transcript = _transcript(
        tmp_path / "session.jsonl",
        [_user_line("no, that's not what I asked")],
    )
    extractor = Path(extract.__file__)
    cmd = [
        sys.executable,
        str(extractor),
        "--record-session",
        "--transcript",
        str(transcript),
        "--learning-file",
        str(learning),
        "--session-id",
        "sess-parallel",
    ]
    procs = [subprocess.Popen(cmd) for _ in range(2)]
    codes = [proc.wait(timeout=15) for proc in procs]
    assert codes == [0, 0]

    text = learning.read_text(encoding="utf-8")
    assert text.count("# Session Learnings") == 1
    assert text.count("Session completed") == 1
    assert text.count("that's not what I asked") == 1
    assert "**Status:** pending" in text


def test_compaction_summary_is_not_reread_as_new_lessons(tmp_path: Path) -> None:
    # The harness writes its summary of an earlier conversation as a user turn,
    # quoting the user's past corrections back.
    transcript = _transcript(
        tmp_path / "session.jsonl",
        [_user_line("Summary: the user said no, stop doing that. I prefer bullets.", isCompactSummary=True)],
    )

    assert extract.extract_candidates(transcript) == []


def test_already_recorded_treats_crlf_and_lf_as_the_same() -> None:
    words = "no, that's not what I asked"
    candidate = extract.Candidate(kind="Correction", text=words)
    lf = f"**What was said:**\n\n> {words}\n"
    crlf = lf.replace("\n", "\r\n")

    assert extract.already_recorded(lf, candidate)
    assert extract.already_recorded(crlf, candidate)


def test_already_recorded_ignores_bom_quotes_and_blockquote_wrap() -> None:
    words = "no, stop over inferring from timesheet entries"
    candidate = extract.Candidate(kind="Correction", text=words)
    existing = (
        "\ufeff# Session Learnings\r\n\r\n"
        "> no, stop over inferring\r\n"
        "> from timesheet entries\r\n"
    )

    assert extract.already_recorded(existing, candidate)
    curly = extract.Candidate(kind="Correction", text="no, that’s not what I asked")
    assert extract.already_recorded("> no, that's not what I asked\n", curly)


def test_extract_and_append_does_not_duplicate_a_crlf_bom_file(tmp_path: Path) -> None:
    words = "no, that's not what I asked"
    body = (
        "# Session Learnings - 2026-09-27\r\n\r\n"
        "## 09:15 - Correction\r\n\r\n**What was said:**\r\n\r\n"
        f"> {words}\r\n\r\n**Status:** pending\r\n\r\n---\r\n\r\n"
    )
    learning = tmp_path / "2026-09-27.md"
    learning.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    transcript = _transcript(tmp_path / "session.jsonl", [_user_line(words)])

    assert extract.extract_and_append(transcript, learning, when=WHEN) == 0
    text = extract._decode_learning_bytes(learning.read_bytes())
    assert text.count("that's not what I asked") == 1


def test_session_already_recorded_normalizes_windows_path_aliases() -> None:
    stored = "**Transcript:** `C:\\Temp\\dex\\transcript.jsonl`\r\n"
    aliases = (
        r"C:\Temp\dex\transcript.jsonl",
        "C:/Temp/dex/transcript.jsonl",
        r"c:\temp\dex\transcript.jsonl",
        r"\\?\C:\Temp\dex\transcript.jsonl",
        r"\\?\c:\Temp\dex\transcript.jsonl",
    )
    for alias in aliases:
        assert extract.session_already_recorded(
            stored, transcript=Path(alias), session_id=""
        ), alias


def test_record_session_end_does_not_repeat_windows_path_or_crlf_marker(
    tmp_path: Path,
) -> None:
    words = "no, that's not what I asked"
    transcript = tmp_path / "session.jsonl"
    _transcript(transcript, [_user_line(words)])
    stored_path = str(transcript).replace("/", "\\")
    learning = tmp_path / "2026-09-27.md"
    learning.write_bytes(
        (
            "# Session Learnings - 2026-09-27\r\n\r\n"
            "## 17:02 - Session completed\r\n\r\n"
            "**Session ended**\r\n"
            "**Session:** `sess-win`\r\n"
            f"**Transcript:** `{stored_path}`\r\n\r\n"
            f"## 09:15 - Correction\r\n\r\n**What was said:**\r\n\r\n> {words}\r\n\r\n"
            "**Status:** pending\r\n\r\n---\r\n\r\n"
        ).encode("utf-8")
    )

    written = extract.record_session_end(
        learning,
        transcript=transcript,
        session_id="SESS-WIN",
        when=WHEN,
    )

    assert written == 0
    text = extract._decode_learning_bytes(learning.read_bytes())
    assert text.count("Session completed") == 1
    assert text.count("that's not what I asked") == 1


def test_normalize_path_key_unifies_slash_case_and_extended_prefix() -> None:
    expected = extract._normalize_path_key(r"C:\Temp\dex\transcript.jsonl")
    assert expected == "c:/temp/dex/transcript.jsonl"
    assert extract._normalize_path_key("C:/Temp/dex/transcript.jsonl") == expected
    assert extract._normalize_path_key(r"\\?\C:\Temp\dex\transcript.jsonl") == expected
    assert extract._normalize_path_key(Path("C:/Temp/dex/transcript.jsonl")) == expected
