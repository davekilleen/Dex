"""Regression tests for the once-per-local-day SessionStart health fallback."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.utils import session_health

LOCAL = timezone(timedelta(hours=10))


def _report(when: datetime, *, broken: int = 0, unknown: int = 0) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": when.isoformat(),
        "journeys": [],
        "summary": {
            "ok": 1 if not broken and not unknown else 0,
            "off": 0,
            "broken": broken,
            "unknown": unknown,
        },
    }


def _write_latest(vault: Path, report: dict[str, object]) -> None:
    path = vault / "System" / ".smoke-last-run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report), encoding="utf-8")


def _write_success_marker(vault: Path, when: datetime) -> None:
    path = vault / "System" / ".dex" / "session-health-success.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "local_date": when.date().isoformat(),
                "completed_at": when.astimezone(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )


def test_successful_check_on_same_local_day_suppresses_session_start_run(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    now = datetime(2026, 7, 24, 8, 0, tzinfo=LOCAL)
    # Stored as 23 July UTC, but this is 24 July in the user's local timezone.
    _write_latest(vault, _report(datetime(2026, 7, 23, 23, 30, tzinfo=timezone.utc)))
    _write_success_marker(vault, now)

    assert session_health.needs_session_start_check(vault, now=now) is False


def test_missing_stale_or_malformed_report_requires_check(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    now = datetime(2026, 7, 24, 8, 0, tzinfo=LOCAL)

    assert session_health.needs_session_start_check(vault, now=now) is True

    _write_latest(vault, _report(now - timedelta(days=1)))
    assert session_health.needs_session_start_check(vault, now=now) is True

    report_path = vault / "System" / ".smoke-last-run.json"
    report_path.write_text("{not-json", encoding="utf-8")
    assert session_health.needs_session_start_check(vault, now=now) is True


def test_clean_report_without_completed_marker_retries_after_interruption(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    now = datetime(2026, 7, 24, 8, 0, tzinfo=LOCAL)
    _write_latest(vault, _report(now))

    assert session_health.needs_session_start_check(vault, now=now) is True


def test_broken_or_unknown_same_day_report_does_not_count_as_success(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    now = datetime(2026, 7, 24, 8, 0, tzinfo=LOCAL)

    _write_latest(vault, _report(now, broken=1))
    assert session_health.needs_session_start_check(vault, now=now) is True

    _write_latest(vault, _report(now, unknown=1))
    assert session_health.needs_session_start_check(vault, now=now) is True


def test_successful_check_persists_report_then_later_session_skips(
    monkeypatch, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    repo = tmp_path / "repo"
    now = datetime(2026, 7, 24, 8, 0, tzinfo=LOCAL)
    calls: list[Path] = []

    def fake_smoke(candidate_vault: Path, _repo: Path) -> int:
        calls.append(candidate_vault)
        _write_latest(candidate_vault, _report(now))
        return 0

    monkeypatch.setattr(session_health, "_run_bounded_smoke", fake_smoke)

    assert session_health.run_session_start_check(vault, repo, now=now) == 0
    assert calls == [vault]
    assert (
        vault / "System" / ".dex" / "session-health-success.json"
    ).is_file()
    assert session_health.run_session_start_check(vault, repo, now=now) == 0
    assert calls == [vault]


def test_failed_or_inconclusive_check_retries_on_later_session(
    monkeypatch, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    repo = tmp_path / "repo"
    now = datetime(2026, 7, 24, 8, 0, tzinfo=LOCAL)
    verdicts = iter(((1, 1, 0), (0, 0, 1), (0, 0, 0)))
    calls: list[int] = []

    def fake_smoke(candidate_vault: Path, _repo: Path) -> int:
        status, broken, unknown = next(verdicts)
        calls.append(status)
        _write_latest(candidate_vault, _report(now, broken=broken, unknown=unknown))
        return status

    monkeypatch.setattr(session_health, "_run_bounded_smoke", fake_smoke)

    assert session_health.run_session_start_check(vault, repo, now=now) == 1
    assert session_health.run_session_start_check(vault, repo, now=now) == 3
    assert session_health.run_session_start_check(vault, repo, now=now) == 0
    assert session_health.run_session_start_check(vault, repo, now=now) == 0
    assert calls == [1, 0, 0]


def test_runner_failure_without_fresh_report_retries(
    monkeypatch, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    repo = tmp_path / "repo"
    now = datetime(2026, 7, 24, 8, 0, tzinfo=LOCAL)
    calls: list[str] = []

    def failed_smoke(_vault: Path, _repo: Path) -> int:
        calls.append("failed")
        return 2

    monkeypatch.setattr(session_health, "_run_bounded_smoke", failed_smoke)

    assert session_health.run_session_start_check(vault, repo, now=now) == 2
    assert session_health.run_session_start_check(vault, repo, now=now) == 2
    assert calls == ["failed", "failed"]


def test_overlapping_session_starts_run_only_one_bounded_check(
    monkeypatch, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    repo = tmp_path / "repo"
    now = datetime(2026, 7, 24, 8, 0, tzinfo=LOCAL)
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def slow_smoke(candidate_vault: Path, _repo: Path) -> int:
        calls.append("run")
        started.set()
        assert release.wait(timeout=2)
        _write_latest(candidate_vault, _report(now))
        return 0

    monkeypatch.setattr(session_health, "_run_bounded_smoke", slow_smoke)
    first = threading.Thread(
        target=session_health.run_session_start_check,
        args=(vault, repo),
        kwargs={"now": now},
    )
    first.start()
    assert started.wait(timeout=2)

    assert session_health.run_session_start_check(vault, repo, now=now) == 0
    release.set()
    first.join(timeout=2)

    assert not first.is_alive()
    assert calls == ["run"]
