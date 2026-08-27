"""Privacy and delivery proofs for the local analytics-attempt receipt."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import portable_contract
from core.lifecycle import service as lifecycle_service
from core.mcp import analytics_helper, analytics_server
from core.transaction.engine import PlanRejected

RECEIPT_RELATIVE = Path("System/.dex/analytics-attempts.jsonl")
RECEIPT_FIELDS = {"timestamp", "event", "outcome", "reason"}
REPO_ROOT = Path(__file__).resolve().parents[2]


class _FixedReceiptDatetime(datetime):
    """Make timestamp-content tests deterministic rather than clock-dependent."""

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 8, 13, 13, 50, 30, 503000, tzinfo=tz or timezone.utc)


def _read_receipts(vault: Path) -> list[dict[str, object]]:
    receipt_path = vault / RECEIPT_RELATIVE
    return [json.loads(line) for line in receipt_path.read_text(encoding="utf-8").splitlines()]


def _safe_receipt_line(
    index: int,
    *,
    event: str = "task_created",
    outcome: str = "not_sent",
    reason: str = "analytics_disabled",
) -> bytes:
    return (
        json.dumps(
            {
                "timestamp": f"2026-08-13T12:00:00.{index:06d}+00:00",
                "event": event,
                "outcome": outcome,
                "reason": reason,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _receipt_lines_just_over_retention_cap(
    first_line: bytes | None = None,
) -> list[bytes]:
    lines = [] if first_line is None else [first_line]
    size = sum(len(line) for line in lines)
    index = 0
    while size <= portable_contract.ANALYTICS_ATTEMPT_RECEIPT_MAX_EXISTING_BYTES:
        line = _safe_receipt_line(index)
        assert len(line) <= portable_contract.ANALYTICS_ATTEMPT_RECEIPT_MAX_RECORD_BYTES
        lines.append(line)
        size += len(line)
        index += 1
    assert size <= portable_contract.ANALYTICS_ATTEMPT_RECEIPT_TRANSACTION_MAX_BYTES
    return lines


def _newest_receipt_lines_within_cap(lines: list[bytes]) -> list[bytes]:
    retained = list(lines)
    while sum(len(line) for line in retained) > portable_contract.ANALYTICS_ATTEMPT_RECEIPT_MAX_EXISTING_BYTES:
        retained.pop(0)
    return retained


def _configure_enabled_delivery(monkeypatch, post) -> None:
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: True)
    monkeypatch.setattr(analytics_helper, "HAS_REQUESTS", True)
    monkeypatch.setattr(
        analytics_helper,
        "get_analytics_transport",
        lambda: {
            "configured": True,
            "mode": "proxy",
            "endpoint": "https://private.example.test/track",
            "headers": {"Authorization": "Bearer never-store-this"},
        },
    )
    monkeypatch.setattr(
        analytics_helper,
        "get_visitor_info",
        lambda: {"visitor_id": "visitor-123", "account_id": "account-123"},
    )
    monkeypatch.setattr(
        analytics_helper,
        "calculate_journey_metadata",
        lambda: {
            "journey_stage": "new",
            "days_since_setup": 1,
            "feature_adoption_score": 1,
            "most_active_area": "tasks",
        },
    )
    monkeypatch.setattr(analytics_helper, "load_user_profile", lambda: {"role_group": "test"})
    monkeypatch.setattr(analytics_helper, "requests", SimpleNamespace(post=post), raising=False)


def test_analytics_receipt_operation_authorizes_only_the_one_safe_file() -> None:
    allowed = portable_contract.update_write_verdict(
        RECEIPT_RELATIVE.as_posix(),
        exists=False,
        operation="analytics-receipt",
    )
    neighboring_file = portable_contract.update_write_verdict(
        "System/.dex/analytics-attempts.jsonl.bak",
        exists=False,
        operation="analytics-receipt",
    )
    legacy_file = portable_contract.update_write_verdict(
        "System/analytics_log.jsonl",
        exists=False,
        operation="analytics-receipt",
    )

    assert allowed.allowed is True
    assert allowed.action == "write-analytics-receipt"
    assert neighboring_file.allowed is False
    assert neighboring_file.action == "outside-analytics-receipt"
    assert legacy_file.allowed is False
    assert legacy_file.action == "outside-analytics-receipt"


def test_analytics_receipt_keeps_historical_lifecycle_helper_signatures() -> None:
    """A receipt must not widen seams pinned by historic update bridges."""
    expected_parameters = {
        "_transaction_preview_document": (
            "vault_root",
            "plan",
            "purpose",
            "operation",
        ),
        "_preview_transaction": (
            "vault_root",
            "plan",
            "purpose",
            "operation",
        ),
        "_execute_approved_transaction": (
            "vault_root",
            "plan",
            "purpose",
            "approved_token",
            "operation",
            "before_commit",
            "bind_intent",
        ),
    }

    assert {
        name: tuple(inspect.signature(getattr(lifecycle_service, name)).parameters)
        for name in expected_parameters
    } == expected_parameters


def test_disabled_event_leaves_one_safe_receipt_and_never_uses_the_legacy_log(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: False)

    result = analytics_helper.fire_event(
        "task_created",
        {
            "person": "Ada Lovelace",
            "meeting_notes": "Project Blackbird is confidential",
            "endpoint": "https://private.example.test/track",
            "authorization": "Bearer never-store-this",
        },
    )

    assert result["fired"] is False
    assert result["reason"] == "analytics_disabled"
    records = _read_receipts(vault)
    assert len(records) == 1
    receipt = records[0]
    assert set(receipt) == RECEIPT_FIELDS
    assert receipt["event"] == "task_created"
    assert receipt["outcome"] == "not_sent"
    assert receipt["reason"] == "analytics_disabled"
    serialized = json.dumps(receipt, sort_keys=True)
    for unsafe_value in (
        "Ada Lovelace",
        "Project Blackbird",
        "https://private.example.test/track",
        "never-store-this",
        "visitor_id",
        "properties",
    ):
        assert unsafe_value not in serialized
    assert not (vault / "System/analytics_log.jsonl").exists()


def test_consent_check_failure_records_a_safe_not_sent_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(
        analytics_helper,
        "is_analytics_enabled",
        lambda: (_ for _ in ()).throw(RuntimeError("Ada's private file is unreadable")),
    )

    result = analytics_helper.fire_event("task_created")

    assert result == {
        "fired": False,
        "reason": "request_failed",
        "receipt_written": True,
    }
    receipts = _read_receipts(vault)
    assert receipts == [
        {
            "timestamp": receipts[0]["timestamp"],
            "event": "task_created",
            "outcome": "not_sent",
            "reason": "request_failed",
        }
    ]
    assert "Ada" not in json.dumps({"result": result, "receipt": receipts}, sort_keys=True)


def test_analytics_helper_cli_outputs_a_safe_receipt_result(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "core/mcp/analytics_helper.py"),
            "--event",
            "session_started",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "VAULT_PATH": str(vault)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert json.loads(completed.stdout) == {
        "fired": False,
        "reason": "analytics_disabled",
        "receipt_written": True,
    }
    assert _read_receipts(vault)[0]["event"] == "session_started"


def test_fire_event_uses_a_short_helper_request_bound_and_still_writes_a_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    request_timeouts: list[float] = []

    class Response:
        status_code = 200

    def post(*_args, **kwargs):
        request_timeouts.append(kwargs["timeout"])
        return Response()

    _configure_enabled_delivery(monkeypatch, post)

    result = analytics_helper.fire_event(
        "session_started",
        _request_timeout_seconds=2.0,
    )

    assert result == {
        "fired": True,
        "event": "session_started",
        "mode": "proxy",
        "receipt_written": True,
    }
    assert request_timeouts == [2.0]
    assert _read_receipts(vault)[0]["event"] == "session_started"


def test_receipt_write_failure_is_visible_without_leaking_the_underlying_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: False)

    def fail_receipt_write(*_args, **_kwargs):
        raise OSError("private relay token must never reach the caller")

    monkeypatch.setattr(
        analytics_helper.lifecycle_service,
        "_append_analytics_attempt_receipt",
        fail_receipt_write,
    )
    result = analytics_helper.fire_event("task_created")

    assert result["fired"] is False
    assert result["reason"] == "analytics_disabled"
    assert result["receipt_written"] is False
    assert result["receipt_reason"] == "receipt_write_failed"
    assert "private relay token" not in json.dumps(result, sort_keys=True)


def test_missing_collection_address_leaves_a_safe_not_sent_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: True)
    monkeypatch.setattr(analytics_helper, "HAS_REQUESTS", True)
    monkeypatch.setattr(
        analytics_helper,
        "get_analytics_transport",
        lambda: {
            "configured": False,
            "mode": "proxy",
            "endpoint": "",
            "headers": {},
            "reason": "no_analytics_endpoint",
        },
    )

    result = analytics_helper.fire_event("task_created")

    assert result == {
        "fired": False,
        "reason": "no_analytics_endpoint",
        "receipt_written": True,
    }
    receipt = _read_receipts(vault)
    assert len(receipt) == 1
    assert receipt[0]["outcome"] == "not_sent"
    assert receipt[0]["reason"] == "no_analytics_endpoint"


def test_http_rejection_receipt_hides_status_and_transport_details(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    posts = 0

    def post(*_args, **_kwargs):
        nonlocal posts
        posts += 1
        return SimpleNamespace(status_code=503)

    _configure_enabled_delivery(monkeypatch, post)
    # A valid timestamp can naturally contain the same digits as an HTTP code.
    # Pin one such value so the privacy assertion must inspect structured fields.
    monkeypatch.setattr(lifecycle_service, "datetime", _FixedReceiptDatetime)

    result = analytics_helper.fire_event("task_created")

    assert result == {
        "fired": False,
        "mode": "proxy",
        "reason": "http_error",
        "receipt_written": True,
    }
    assert posts == 1
    receipt = _read_receipts(vault)
    assert receipt == [
        {
            "timestamp": "2026-08-13T13:50:30.503000+00:00",
            "event": "task_created",
            "outcome": "not_sent",
            "reason": "http_error",
        }
    ]


def test_successful_delivery_receipt_records_only_the_final_safe_outcome(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    posts: list[dict[str, object]] = []

    def post(url, **kwargs):
        posts.append({"url": url, **kwargs})
        return SimpleNamespace(status_code=200)

    _configure_enabled_delivery(monkeypatch, post)

    result = analytics_helper.fire_event(
        "task_created",
        {"meeting_notes": "Project Blackbird is confidential"},
    )

    assert result["fired"] is True
    assert result["receipt_written"] is True
    assert len(posts) == 1
    records = _read_receipts(vault)
    assert len(records) == 1
    receipt = records[0]
    assert set(receipt) == RECEIPT_FIELDS
    assert receipt["event"] == "task_created"
    assert receipt["outcome"] == "sent"
    assert receipt["reason"] == "sent"
    serialized = json.dumps(receipt, sort_keys=True)
    for unsafe_value in (
        "visitor-123",
        "account-123",
        "Project Blackbird",
        "https://private.example.test/track",
        "never-store-this",
    ):
        assert unsafe_value not in serialized


def test_failed_delivery_receipt_normalizes_the_error_without_resending(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    posts = 0

    def post(*_args, **_kwargs):
        nonlocal posts
        posts += 1
        raise OSError("relay https://private.example.test failed with token never-store-this")

    _configure_enabled_delivery(monkeypatch, post)

    result = analytics_helper.fire_event("task_created")

    assert result == {
        "fired": False,
        "reason": "request_failed",
        "receipt_written": True,
    }
    assert posts == 1
    receipt = _read_receipts(vault)
    assert len(receipt) == 1
    assert receipt[0]["outcome"] == "not_sent"
    assert receipt[0]["reason"] == "request_failed"
    assert "private.example.test" not in json.dumps(receipt[0], sort_keys=True)
    assert "never-store-this" not in json.dumps(receipt[0], sort_keys=True)


def test_unsafe_existing_receipt_is_not_extended_or_silently_accepted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    receipt_path = vault / RECEIPT_RELATIVE
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(
            {
                "timestamp": "2026-08-12T15:00:00+00:00",
                "event": "task_created",
                "outcome": "not_sent",
                "reason": "analytics_disabled",
                "visitor_id": "do-not-keep",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    original = receipt_path.read_text(encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: False)

    result = analytics_helper.fire_event("task_created")

    assert result == {
        "fired": False,
        "reason": "analytics_disabled",
        "receipt_written": False,
        "receipt_reason": "receipt_write_failed",
    }
    assert receipt_path.read_text(encoding="utf-8") == original


def test_duplicate_json_keys_cannot_hide_unsafe_existing_receipt_data(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    receipt_path = vault / RECEIPT_RELATIVE
    receipt_path.parent.mkdir(parents=True)
    original = (
        '{"timestamp":"2026-08-12T15:00:00+00:00",'
        '"event":"Ada Lovelace",'
        '"event":"task_created",'
        '"outcome":"not_sent",'
        '"reason":"analytics_disabled"}\n'
    )
    receipt_path.write_text(original, encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: False)

    result = analytics_helper.fire_event("task_created")

    assert result == {
        "fired": False,
        "reason": "analytics_disabled",
        "receipt_written": False,
        "receipt_reason": "receipt_write_failed",
    }
    assert receipt_path.read_text(encoding="utf-8") == original


def test_mcp_track_event_delegates_to_fire_event_without_a_second_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: False)
    monkeypatch.setattr(analytics_server, "fire_event", analytics_helper.fire_event)

    response = asyncio.run(
        analytics_server._call_tool_inner(
            "track_event",
            {"event_name": "task_created", "properties": {"person": "Ada Lovelace"}},
        )
    )
    result = json.loads(response[0].text)

    assert result == {
        "fired": False,
        "reason": "analytics_disabled",
        "receipt_written": True,
    }
    receipts = _read_receipts(vault)
    assert len(receipts) == 1
    assert receipts[0]["event"] == "task_created"
    assert not (vault / "System/analytics_log.jsonl").exists()


def test_mcp_track_event_missing_name_uses_the_redacted_receipt_route(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: False)
    monkeypatch.setattr(analytics_server, "fire_event", analytics_helper.fire_event)

    response = asyncio.run(analytics_server._call_tool_inner("track_event", {}))
    result = json.loads(response[0].text)

    assert result == {
        "error": "event_name required",
        "receipt_written": True,
    }
    receipts = _read_receipts(vault)
    assert receipts == [
        {
            "timestamp": receipts[0]["timestamp"],
            "event": "invalid_event",
            "outcome": "not_sent",
            "reason": "invalid_event_name",
        }
    ]


def test_disabled_mcp_identify_user_records_one_safe_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: False)
    monkeypatch.setattr(analytics_server, "is_analytics_enabled", lambda: False)
    monkeypatch.setattr(analytics_server, "fire_event", analytics_helper.fire_event)

    response = asyncio.run(
        analytics_server._call_tool_inner(
            "identify_user",
            {"metadata": {"person": "Ada Lovelace"}},
        )
    )
    result = json.loads(response[0].text)

    assert result == {
        "identified": False,
        "reason": "analytics_disabled",
        "receipt_written": True,
    }
    receipts = _read_receipts(vault)
    assert receipts == [
        {
            "timestamp": receipts[0]["timestamp"],
            "event": "user_identified",
            "outcome": "not_sent",
            "reason": "analytics_disabled",
        }
    ]
    assert "Ada Lovelace" not in json.dumps(receipts, sort_keys=True)


def test_enabled_mcp_identify_profile_failure_records_one_safe_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    posts = 0

    def post(*_args, **_kwargs):
        nonlocal posts
        posts += 1
        return SimpleNamespace(status_code=200)

    _configure_enabled_delivery(monkeypatch, post)
    monkeypatch.setattr(analytics_server, "is_analytics_enabled", lambda: True)
    monkeypatch.setattr(analytics_server, "fire_event", analytics_helper.fire_event)
    monkeypatch.setattr(
        analytics_server,
        "load_user_profile",
        lambda: (_ for _ in ()).throw(RuntimeError("Ada profile must not leak")),
    )
    monkeypatch.setattr(
        analytics_helper,
        "load_user_profile",
        lambda: (_ for _ in ()).throw(RuntimeError("Ada profile must not leak")),
    )

    response = asyncio.run(analytics_server._call_tool_inner("identify_user", {}))
    result = json.loads(response[0].text)

    assert result == {
        "identified": False,
        "reason": "request_failed",
        "receipt_written": True,
    }
    assert posts == 0
    receipts = _read_receipts(vault)
    assert receipts == [
        {
            "timestamp": receipts[0]["timestamp"],
            "event": "user_identified",
            "outcome": "not_sent",
            "reason": "request_failed",
        }
    ]


def test_receipt_failure_preserves_the_true_delivery_result_without_a_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    posts = 0

    def post(*_args, **_kwargs):
        nonlocal posts
        posts += 1
        return SimpleNamespace(status_code=200)

    _configure_enabled_delivery(monkeypatch, post)

    def fail_receipt_write(*_args, **_kwargs):
        raise OSError("private relay token must never reach the caller")

    monkeypatch.setattr(
        analytics_helper.lifecycle_service,
        "_append_analytics_attempt_receipt",
        fail_receipt_write,
    )

    result = analytics_helper.fire_event("task_created")

    assert result == {
        "fired": True,
        "event": "task_created",
        "mode": "proxy",
        "receipt_written": False,
        "receipt_reason": "receipt_write_failed",
    }
    assert posts == 1
    assert not (vault / RECEIPT_RELATIVE).exists()
    assert "private relay token" not in json.dumps(result, sort_keys=True)


def test_event_preparation_failure_records_one_normalized_safe_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    posts = 0

    def post(*_args, **_kwargs):
        nonlocal posts
        posts += 1
        return SimpleNamespace(status_code=200)

    _configure_enabled_delivery(monkeypatch, post)
    monkeypatch.setattr(
        analytics_helper,
        "calculate_journey_metadata",
        lambda: (_ for _ in ()).throw(RuntimeError("profile for Ada must not leak")),
    )

    result = analytics_helper.fire_event("task_created")

    assert result == {
        "fired": False,
        "reason": "request_failed",
        "receipt_written": True,
    }
    assert posts == 0
    receipts = _read_receipts(vault)
    assert receipts == [
        {
            "timestamp": receipts[0]["timestamp"],
            "event": "task_created",
            "outcome": "not_sent",
            "reason": "request_failed",
        }
    ]
    assert "Ada" not in json.dumps({"result": result, "receipt": receipts}, sort_keys=True)


def test_stale_receipt_plan_retries_only_the_local_write_without_resending(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    posts = 0

    def post(*_args, **_kwargs):
        nonlocal posts
        posts += 1
        return SimpleNamespace(status_code=200)

    _configure_enabled_delivery(monkeypatch, post)
    original_execute = analytics_helper.lifecycle_service._execute_approved_transaction
    receipt_attempts = 0

    def stale_once(*args, **kwargs):
        nonlocal receipt_attempts
        receipt_attempts += 1
        if receipt_attempts == 1:
            receipt_path = vault / RECEIPT_RELATIVE
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-08-12T15:00:00+00:00",
                        "event": "session_started",
                        "outcome": "not_sent",
                        "reason": "analytics_disabled",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            # A real concurrent append changes the service's preview token
            # before the transaction begins. This is the exact stale-plan
            # signal that the narrow retry recognizes.
            raise PlanRejected("transaction approval token does not match the current preview")
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(
        analytics_helper.lifecycle_service,
        "_execute_approved_transaction",
        stale_once,
    )

    result = analytics_helper.fire_event("task_created")

    assert result["fired"] is True
    assert result["receipt_written"] is True
    assert posts == 1
    assert receipt_attempts == 2
    receipts = _read_receipts(vault)
    assert [receipt["event"] for receipt in receipts] == [
        "session_started",
        "task_created",
    ]


def test_untrusted_event_name_is_redacted_before_delivery_or_local_storage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    posts = 0

    def post(*_args, **_kwargs):
        nonlocal posts
        posts += 1
        return SimpleNamespace(status_code=200)

    _configure_enabled_delivery(monkeypatch, post)
    unsafe_name = "Ada Lovelace — Project Blackbird"

    result = analytics_helper.fire_event(unsafe_name, {"notes": unsafe_name})

    assert result == {
        "fired": False,
        "reason": "invalid_event_name",
        "receipt_written": True,
    }
    assert posts == 0
    receipts = _read_receipts(vault)
    assert receipts == [
        {
            "timestamp": receipts[0]["timestamp"],
            "event": "invalid_event",
            "outcome": "not_sent",
            "reason": "invalid_event_name",
        }
    ]
    assert unsafe_name not in json.dumps(receipts, sort_keys=True)


def test_symlinked_receipt_parent_is_rejected_before_any_direct_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "analytics-attempts.jsonl").write_text(
        "private data that must not be read\n",
        encoding="utf-8",
    )
    (vault / "System" / ".dex").symlink_to(outside, target_is_directory=True)
    target = vault / RECEIPT_RELATIVE
    direct_reads: list[Path] = []
    original_read_bytes = Path.read_bytes

    def record_direct_read(path: Path) -> bytes:
        if path == target:
            direct_reads.append(path)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", record_direct_read)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: False)

    result = analytics_helper.fire_event("task_created")

    assert result == {
        "fired": False,
        "reason": "analytics_disabled",
        "receipt_written": False,
        "receipt_reason": "receipt_write_failed",
    }
    assert direct_reads == []
    assert (outside / "analytics-attempts.jsonl").read_text(encoding="utf-8") == (
        "private data that must not be read\n"
    )


def test_saturated_valid_receipt_keeps_whole_newest_records_under_the_cap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    receipt_path = vault / RECEIPT_RELATIVE
    receipt_path.parent.mkdir(parents=True)
    existing_lines = _receipt_lines_just_over_retention_cap()
    receipt_path.write_bytes(b"".join(existing_lines))
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: False)
    monkeypatch.setattr(lifecycle_service, "datetime", _FixedReceiptDatetime)

    result = analytics_helper.fire_event("task_created")

    assert result == {
        "fired": False,
        "reason": "analytics_disabled",
        "receipt_written": True,
    }
    actual = receipt_path.read_bytes()
    expected_new_line = (
        json.dumps(
            {
                "timestamp": "2026-08-13T13:50:30.503000+00:00",
                "event": "task_created",
                "outcome": "not_sent",
                "reason": "analytics_disabled",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    expected_lines = _newest_receipt_lines_within_cap(existing_lines + [expected_new_line])

    assert len(actual) <= portable_contract.ANALYTICS_ATTEMPT_RECEIPT_MAX_EXISTING_BYTES
    assert actual == b"".join(expected_lines)
    assert actual.endswith(b"\n")
    assert len(expected_lines) < len(existing_lines) + 1
    assert _read_receipts(vault)[-1] == json.loads(expected_new_line)


def test_saturation_validates_an_oldest_record_before_it_can_be_trimmed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    receipt_path = vault / RECEIPT_RELATIVE
    receipt_path.parent.mkdir(parents=True)
    unsafe_oldest_line = (
        json.dumps(
            {
                "timestamp": "2026-08-13T12:00:00.999999+00:00",
                "event": "task_created",
                "outcome": "not_sent",
                "reason": "analytics_disabled",
                "visitor_id": "must-not-survive",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    existing = b"".join(_receipt_lines_just_over_retention_cap(unsafe_oldest_line))
    receipt_path.write_bytes(existing)
    validated: list[bytes] = []
    original_validate = lifecycle_service._validated_analytics_receipt_prefix

    def record_validation(raw: bytes) -> bytes:
        validated.append(raw)
        return original_validate(raw)

    monkeypatch.setattr(
        lifecycle_service,
        "_validated_analytics_receipt_prefix",
        record_validation,
    )
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: False)

    result = analytics_helper.fire_event("task_created")

    assert result == {
        "fired": False,
        "reason": "analytics_disabled",
        "receipt_written": False,
        "receipt_reason": "receipt_write_failed",
    }
    assert validated == [existing]
    assert receipt_path.read_bytes() == existing


def test_receipt_above_the_recovery_bound_is_rejected_by_the_bounded_reader(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    receipt_path = vault / RECEIPT_RELATIVE
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(
        b"x" * (portable_contract.ANALYTICS_ATTEMPT_RECEIPT_TRANSACTION_MAX_BYTES + 1)
    )
    bounded_reads: list[tuple[Path, str, int]] = []
    direct_reads: list[Path] = []
    original_bounded_read = lifecycle_service.bounded_read
    original_read_bytes = Path.read_bytes

    def record_bounded_read(root: Path, relative: str, *, max_bytes: int) -> bytes:
        bounded_reads.append((root, relative, max_bytes))
        return original_bounded_read(root, relative, max_bytes=max_bytes)

    def record_direct_read(path: Path) -> bytes:
        if path == receipt_path:
            direct_reads.append(path)
        return original_read_bytes(path)

    monkeypatch.setattr(lifecycle_service, "bounded_read", record_bounded_read)
    monkeypatch.setattr(Path, "read_bytes", record_direct_read)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: False)

    result = analytics_helper.fire_event("task_created")

    assert result == {
        "fired": False,
        "reason": "analytics_disabled",
        "receipt_written": False,
        "receipt_reason": "receipt_write_failed",
    }
    assert bounded_reads
    assert all(
        read
        == (
            vault,
            RECEIPT_RELATIVE.as_posix(),
            portable_contract.ANALYTICS_ATTEMPT_RECEIPT_TRANSACTION_MAX_BYTES,
        )
        for read in bounded_reads
    )
    assert direct_reads == []


def test_existing_receipt_directory_is_rejected_before_the_bounded_reader(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    receipt_path = vault / RECEIPT_RELATIVE
    receipt_path.mkdir(parents=True)
    bounded_reads: list[tuple[Path, str, int]] = []

    def fail_bounded_read(root: Path, relative: str, *, max_bytes: int) -> bytes:
        bounded_reads.append((root, relative, max_bytes))
        raise AssertionError("a non-regular receipt target must not be opened")

    monkeypatch.setattr(
        analytics_helper.lifecycle_service,
        "bounded_read",
        fail_bounded_read,
    )
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: False)

    result = analytics_helper.fire_event("task_created")

    assert result == {
        "fired": False,
        "reason": "analytics_disabled",
        "receipt_written": False,
        "receipt_reason": "receipt_write_failed",
    }
    assert bounded_reads == []


def test_existing_receipt_fifo_is_rejected_before_the_bounded_reader(
    tmp_path: Path,
    monkeypatch,
) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("this platform does not support FIFO creation")

    vault = tmp_path / "vault"
    receipt_path = vault / RECEIPT_RELATIVE
    receipt_path.parent.mkdir(parents=True)
    try:
        os.mkfifo(receipt_path)
    except OSError as error:
        pytest.skip(f"FIFO creation is unavailable: {error.__class__.__name__}")
    bounded_reads: list[tuple[Path, str, int]] = []

    def fail_bounded_read(root: Path, relative: str, *, max_bytes: int) -> bytes:
        bounded_reads.append((root, relative, max_bytes))
        raise AssertionError("a FIFO receipt target must not be opened")

    monkeypatch.setattr(
        analytics_helper.lifecycle_service,
        "bounded_read",
        fail_bounded_read,
    )
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: False)

    result = analytics_helper.fire_event("task_created")

    assert result == {
        "fired": False,
        "reason": "analytics_disabled",
        "receipt_written": False,
        "receipt_reason": "receipt_write_failed",
    }
    assert bounded_reads == []


def test_mcp_test_connection_uses_the_same_single_receipt_route(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_helper, "is_analytics_enabled", lambda: False)
    calls: list[tuple[str, object, dict[str, object]]] = []
    original_fire_event = analytics_helper.fire_event

    def record_fire_event(event_name: str, properties=None, **kwargs):
        calls.append((event_name, properties, kwargs))
        return original_fire_event(event_name, properties, **kwargs)

    monkeypatch.setattr(analytics_server, "fire_event", record_fire_event)

    response = asyncio.run(analytics_server._call_tool_inner("test_connection", {}))
    result = json.loads(response[0].text)

    assert result == {
        "feature": "Usage analytics",
        "feature_status": "off",
        "user_message": "Usage analytics is not ready to send a connection check.",
        "success": False,
        "reason": "analytics_disabled",
        "receipt_written": True,
    }
    assert calls == [("dex_analytics_test", None, {"_connection_test": True})]
    receipts = _read_receipts(vault)
    assert len(receipts) == 1
    assert receipts[0]["event"] == "dex_analytics_test"


def test_connection_test_uses_no_real_identity_or_profile_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(analytics_server, "fire_event", analytics_helper.fire_event)
    delivered: list[dict[str, object]] = []

    def post(_url, *, json, **_kwargs):
        delivered.append(json)
        return SimpleNamespace(status_code=200)

    _configure_enabled_delivery(monkeypatch, post)
    monkeypatch.setattr(
        analytics_helper,
        "get_visitor_info",
        lambda: {"visitor_id": "real-visitor-123", "account_id": "real-account-456"},
    )
    monkeypatch.setattr(
        analytics_helper,
        "calculate_journey_metadata",
        lambda: (_ for _ in ()).throw(AssertionError("journey metadata must not be read")),
    )
    monkeypatch.setattr(
        analytics_helper,
        "load_user_profile",
        lambda: (_ for _ in ()).throw(AssertionError("profile must not be read")),
    )

    response = asyncio.run(analytics_server._call_tool_inner("test_connection", {}))
    result = json.loads(response[0].text)

    assert result["feature_status"] == "ok"
    assert result["receipt_written"] is True
    assert delivered == [
        {
            "type": "track",
            "event": "dex_analytics_test",
            "visitorId": "dex-analytics-test",
            "accountId": "dex-analytics-test",
            "timestamp": delivered[0]["timestamp"],
            "properties": {"connection_test": True},
        }
    ]
    serialized = json.dumps(delivered, sort_keys=True)
    for unsafe_value in ("real-visitor-123", "real-account-456", "journey_stage", "role"):
        assert unsafe_value not in serialized
