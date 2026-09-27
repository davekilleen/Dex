"""Session-end lesson extraction is automatic, local, and fail-open.

These cover the mechanical half: spotting a correction or preference in a
recorded transcript, writing it in the pending format /daily-review already
uses, and refusing to hang, leak secrets, or duplicate a live capture.
"""
from __future__ import annotations

import json
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


def test_skips_secret_looking_messages_entirely() -> None:
    assert extract.classify("stop using sk-ant-fake-test-token-value") is None
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
