"""Tests for the standalone skill script .claude/skills/feedback/scripts/feedback_client.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / ".claude" / "skills" / "feedback" / "scripts" / "feedback_client.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("feedback_client", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _draft(**overrides):
    draft = {
        "dex_version": "1.81.19",
        "feature": "/process-meetings",
        "summary": "Sync stopped when a meeting had no attendees.",
        "review_mode": "always-review",
    }
    draft.update(overrides)
    return draft


def test_validate_draft_fills_schema_version_timestamp_and_fingerprint():
    client = _load_script()
    payload = client.validate_draft(_draft(error_trace="IndexError: line 42"))
    assert payload["schema_version"] == client.SCHEMA_VERSION
    assert isinstance(payload["captured_at"], int)
    assert len(payload["fingerprint"]) == 64
    assert set(payload["fingerprint"]) <= set("0123456789abcdef")


def test_validate_draft_rejects_fields_outside_the_allowed_list():
    client = _load_script()
    with pytest.raises(client.DraftProblem) as excinfo:
        client.validate_draft(_draft(meeting_notes="private content"))
    assert "allowed list" in excinfo.value.user_message


def test_validate_draft_rejects_missing_required_and_oversized_fields():
    client = _load_script()
    with pytest.raises(client.DraftProblem):
        client.validate_draft({"dex_version": "1.0.0", "feature": "/x"})
    with pytest.raises(client.DraftProblem):
        client.validate_draft(_draft(summary="x" * 2001))
    with pytest.raises(client.DraftProblem):
        client.validate_draft(_draft(review_mode="yolo"))


def test_fingerprint_is_stable_across_line_numbers_and_addresses():
    client = _load_script()
    first = client.compute_fingerprint("/sync", "IndexError at line 42 (0xdeadbeef)", "s")
    second = client.compute_fingerprint("/sync", "IndexError at line 97 (0xcafef00d)", "s")
    different = client.compute_fingerprint("/sync", "KeyError: person", "s")
    assert first == second
    assert first != different


def test_fingerprint_distinguishes_bugs_inside_realistic_tracebacks():
    client = _load_script()
    index_error = (
        "Traceback (most recent call last):\n"
        '  File "core/utils/doctor.py", line 42, in collect\n'
        "    attendee = meeting.attendees[0]\n"
        "IndexError: list index out of range"
    )
    key_error = (
        "Traceback (most recent call last):\n"
        '  File "core/utils/sync.py", line 97, in run\n'
        "    person = pages[email]\n"
        "KeyError: 'person@example.com'"
    )
    same_bug_other_line = index_error.replace("line 42", "line 58")

    first = client.compute_fingerprint("/process-meetings", index_error, "s")
    second = client.compute_fingerprint("/process-meetings", key_error, "s")
    assert first != second, "different exceptions must not share a fingerprint"
    assert first == client.compute_fingerprint("/process-meetings", same_bug_other_line, "s")


def test_auth_failure_still_appends_a_receipt(tmp_path, monkeypatch):
    client = _load_script()
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps(_draft()), encoding="utf-8")

    def no_auth(**kwargs):
        raise client.AuthError("not linked")

    monkeypatch.setattr(client, "load_auth", no_auth)
    args = client.build_parser().parse_args(
        ["report", "--file", str(draft_path), "--vault", str(tmp_path)]
    )
    with pytest.raises(client.AuthError):
        client.command_report(args)

    receipts = (tmp_path / "System" / ".dex" / "feedback-log.jsonl").read_text(encoding="utf-8")
    record = json.loads(receipts.strip())
    assert record["sent"] is False
    assert record["reason"] == "AuthError"


def test_unsaveable_ticket_file_does_not_crash_a_successful_send(tmp_path, monkeypatch, capsys):
    client = _load_script()
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps(_draft()), encoding="utf-8")
    monkeypatch.setattr(
        client, "load_auth", lambda **kwargs: {"sessionToken": "token", "timestamp": client.now_ms()}
    )
    monkeypatch.setattr(
        client,
        "_request_json",
        lambda *args, **kwargs: {"ticket": "DEX-142", "receivedAt": 1754640001000},
    )

    def broken_write(*args, **kwargs):
        raise OSError("read-only vault")

    monkeypatch.setattr(client, "write_ticket_file", broken_write)
    args = client.build_parser().parse_args(
        ["report", "--file", str(draft_path), "--vault", str(tmp_path)]
    )
    assert client.command_report(args) == 0
    out = capsys.readouterr().out
    assert "DEX-142" in out
    assert "could not be saved" in out


def test_receipt_is_written_even_when_send_fails(tmp_path, monkeypatch):
    client = _load_script()
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps(_draft()), encoding="utf-8")
    auth = {"sessionToken": "token", "timestamp": client.now_ms()}
    monkeypatch.setattr(client, "load_auth", lambda **kwargs: auth)

    def failing_request(*args, **kwargs):
        raise client.NetworkError("no network")

    monkeypatch.setattr(client, "_request_json", failing_request)
    args = client.build_parser().parse_args(
        ["report", "--file", str(draft_path), "--vault", str(tmp_path)]
    )
    with pytest.raises(client.NetworkError):
        client.command_report(args)

    receipts = (tmp_path / "System" / ".dex" / "feedback-log.jsonl").read_text(encoding="utf-8")
    record = json.loads(receipts.strip())
    assert record["sent"] is False
    assert record["reason"] == "NetworkError"
    assert record["payload"]["feature"] == "/process-meetings"


def test_successful_report_writes_ticket_file_and_receipt(tmp_path, monkeypatch, capsys):
    client = _load_script()
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps(_draft()), encoding="utf-8")
    auth = {"sessionToken": "token", "timestamp": client.now_ms()}
    monkeypatch.setattr(client, "load_auth", lambda **kwargs: auth)
    monkeypatch.setattr(
        client,
        "_request_json",
        lambda *args, **kwargs: {"ticket": "DEX-142", "receivedAt": 1754640001000},
    )

    args = client.build_parser().parse_args(
        ["report", "--file", str(draft_path), "--vault", str(tmp_path)]
    )
    assert client.command_report(args) == 0
    assert "DEX-142" in capsys.readouterr().out

    ticket_file = tmp_path / "System" / ".dex" / "feedback" / "DEX-142.json"
    record = json.loads(ticket_file.read_text(encoding="utf-8"))
    assert record["status"] == "received"
    assert record["report"]["summary"].startswith("Sync stopped")

    receipts = (tmp_path / "System" / ".dex" / "feedback-log.jsonl").read_text(encoding="utf-8")
    assert json.loads(receipts.strip())["sent"] is True


def test_answer_requires_a_plausible_ticket_and_nonempty_text(tmp_path):
    client = _load_script()
    args = client.build_parser().parse_args(
        ["answer", "--ticket", "nonsense", "--text", "hello", "--vault", str(tmp_path)]
    )
    with pytest.raises(client.DraftProblem):
        client.command_answer(args)

    args = client.build_parser().parse_args(
        ["answer", "--ticket", "DEX-1", "--text", "   ", "--vault", str(tmp_path)]
    )
    with pytest.raises(client.DraftProblem):
        client.command_answer(args)


def test_expired_auth_raises_connection_instructions(tmp_path, monkeypatch):
    client = _load_script()
    stale = tmp_path / "auth.json"
    stale.write_text(
        json.dumps({"sessionToken": "token", "timestamp": 0}), encoding="utf-8"
    )
    monkeypatch.setattr(client, "auth_file_path", lambda: stale)
    with pytest.raises(client.AuthError) as excinfo:
        client.load_auth()
    assert "expired" in excinfo.value.user_message
    assert "feedback_client.py link" in excinfo.value.user_message


def test_check_subcommand_exits_2_with_connection_needed_when_unlinked(tmp_path, monkeypatch, capsys):
    client = _load_script()
    monkeypatch.setattr(client, "auth_file_path", lambda: tmp_path / "missing-auth.json")

    code = client.main(["check", "--vault", str(tmp_path)])

    assert code == 2
    out = capsys.readouterr().out
    assert out.startswith("CONNECTION NEEDED: ")
    assert "feedback_client.py link" in out


def test_check_subcommand_exits_0_when_linked(tmp_path, monkeypatch, capsys):
    client = _load_script()
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps(
            {"sessionToken": "token", "timestamp": client.now_ms(), "email": "user@example.com"}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(client, "auth_file_path", lambda: auth)

    code = client.main(["check", "--vault", str(tmp_path)])

    assert code == 0
    assert "LINKED" in capsys.readouterr().out


def test_report_exit_code_through_main_is_2_when_unlinked_and_receipt_is_kept(
    tmp_path, monkeypatch, capsys
):
    client = _load_script()
    monkeypatch.setattr(client, "auth_file_path", lambda: tmp_path / "missing-auth.json")
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(_draft()), encoding="utf-8")

    code = client.main(["report", "--file", str(draft), "--vault", str(tmp_path)])

    assert code == 2
    assert capsys.readouterr().out.startswith("CONNECTION NEEDED: ")
    receipts = (tmp_path / "System" / ".dex" / "feedback-log.jsonl").read_text(encoding="utf-8")
    record = json.loads(receipts.strip())
    assert record["sent"] is False
    assert record["reason"] == "AuthError"


def test_link_with_blank_code_does_not_reuse_the_connection_needed_exit_code(capsys):
    client = _load_script()

    code = client.main(["link", "--code", "   "])

    assert code == client.FeedbackError.exit_code
    out = capsys.readouterr().out
    assert "sign-in code is required" in out
    assert "CONNECTION NEEDED" not in out
