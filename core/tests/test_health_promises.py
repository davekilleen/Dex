"""The promise register, its auditor, and the post-update canary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.health import promises
from core.health.post_update import RECEIPT_RELATIVE, run_canary
from core.tests.test_lifecycle_bridge import (
    _activation_fixture,
    _deliver_release,
    _write_bridge_release,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def test_every_promise_is_well_formed() -> None:
    seen = set()
    for promise in promises.PROMISES:
        assert promise.id.startswith("com.dex.")
        assert promise.id not in seen
        seen.add(promise.id)
        if promise.receipt_kind == "daemon":
            assert promise.cadence is None
        else:
            assert promise.cadence is not None and promise.cadence > timedelta(0)
        if promise.receipt_kind == "json-timestamp":
            assert promise.receipt_key
            assert not promise.activity_only


def test_json_timestamp_audit_distinguishes_never_broken_and_kept(tmp_path: Path) -> None:
    promise = promises.promise_by_id("com.dex.meeting-intel")
    assert promise is not None

    never = promises.audit_promise(tmp_path, promise, now=NOW)
    assert never.state == "never"
    assert "never recorded a completed run" in never.detail()

    receipt = tmp_path / promise.receipt_path
    receipt.parent.mkdir(parents=True)
    stale_at = NOW - timedelta(days=6)
    receipt.write_text(json.dumps({"lastSync": stale_at.isoformat()}), encoding="utf-8")
    broken = promises.audit_promise(tmp_path, promise, now=NOW)
    assert broken.state == "broken"
    assert "may still be running without succeeding" in broken.detail()

    receipt.write_text(
        json.dumps({"lastSync": (NOW - timedelta(hours=1)).isoformat()}), encoding="utf-8"
    )
    assert promises.audit_promise(tmp_path, promise, now=NOW).state == "kept"


def test_malformed_receipts_read_as_never_succeeded(tmp_path: Path) -> None:
    promise = promises.promise_by_id("com.dex.meeting-intel")
    assert promise is not None
    receipt = tmp_path / promise.receipt_path
    receipt.parent.mkdir(parents=True)

    for content in ("not json\n", "[]\n", json.dumps({"lastSync": 12345})):
        receipt.write_text(content, encoding="utf-8")
        assert promises.audit_promise(tmp_path, promise, now=NOW).state == "never"


def test_smoke_receipt_is_the_success_only_log_not_the_ledger() -> None:
    """The ledger (System/.smoke-last-run.json) is rewritten even by failing
    runs, so it can never be the smoke job's success receipt."""
    promise = promises.promise_by_id("com.dex.smoke-nightly")
    assert promise is not None
    assert promise.receipt_path == ".scripts/logs/smoke-nightly.log"
    assert promise.activity_only is False  # the log is appended only on success


def test_activity_only_promise_with_no_receipt_reads_as_never_run(tmp_path: Path) -> None:
    promise = promises.promise_by_id("com.dex.learning-review")
    assert promise is not None

    audit = promises.audit_promise(tmp_path, promise, now=NOW)

    assert audit.state == "never"
    assert "has never run" in audit.detail()
    assert "successfully" not in audit.detail()


def test_daemon_promises_refuse_cadence_audits() -> None:
    promise = promises.promise_by_id("com.dex.obsidian-sync")
    assert promise is not None
    with pytest.raises(ValueError, match="daemon"):
        promises.audit_promise(Path("/nonexistent"), promise, now=NOW)


def test_activity_only_audits_say_ran_not_succeeded(tmp_path: Path) -> None:
    promise = promises.promise_by_id("com.dex.changelog-checker")
    assert promise is not None
    log = tmp_path / promise.receipt_path
    log.parent.mkdir(parents=True)
    log.touch()
    stale_at = (NOW - timedelta(days=9)).timestamp()
    os.utime(log, (stale_at, stale_at))

    audit = promises.audit_promise(tmp_path, promise, now=NOW)

    assert audit.state == "broken"
    assert "last ran on" in audit.detail()
    assert "successfully" not in audit.detail()


def test_register_view_scanner_and_session_mirror_are_current() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "generate_health_promises", REPO_ROOT / "scripts" / "generate-health-promises.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.main(["--check"]) == 0


def test_post_update_canary_passes_and_writes_a_receipt(tmp_path: Path) -> None:
    vault = _activation_fixture(tmp_path)

    receipt = run_canary(vault)

    assert receipt["ok"] is True
    assert receipt["error"] is None
    stored = json.loads((vault / RECEIPT_RELATIVE).read_text(encoding="utf-8"))
    assert stored["ok"] is True
    assert stored["contract"] == "dex.health.post-update-canary/v1"


def test_post_update_canary_still_passes_after_a_delivered_release(tmp_path: Path) -> None:
    """The exact v1.84.0 incident shape: update applied, doors must still open."""
    vault = _activation_fixture(tmp_path)
    assert run_canary(vault)["ok"] is True

    _deliver_release(vault, "1.64.1")

    assert run_canary(vault)["ok"] is True


def test_post_update_canary_reports_a_torn_install_instead_of_raising(tmp_path: Path) -> None:
    vault = _activation_fixture(tmp_path)
    run_canary(vault)
    _write_bridge_release(vault, release_version="1.64.1")  # bridge moved, catalog did not

    receipt = run_canary(vault)

    assert receipt["ok"] is False
    assert isinstance(receipt["error"], str) and receipt["error"]
    stored = json.loads((vault / RECEIPT_RELATIVE).read_text(encoding="utf-8"))
    assert stored["ok"] is False


def test_canary_cli_reports_a_torn_install_plainly_without_a_traceback(tmp_path: Path) -> None:
    """The CLI contract: even a failed canary speaks one plain line and exits 1."""
    vault = _activation_fixture(tmp_path)
    run_canary(vault)
    _write_bridge_release(vault, release_version="1.64.1")

    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "core" / "health" / "post_update.py"), "--vault", str(vault)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert completed.returncode == 1
    assert "Post-update check FAILED" in completed.stdout
    assert "PlanRejected" in completed.stdout
    assert "Traceback" not in completed.stdout + completed.stderr
    stored = json.loads((vault / RECEIPT_RELATIVE).read_text(encoding="utf-8"))
    assert stored["ok"] is False
