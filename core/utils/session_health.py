"""Once-per-local-day SessionStart fallback for Dex's smoke health check.

The nightly Launch Agent remains the preferred trigger. This module closes the
sleep/off gap: when a Dex session starts and no clean smoke report exists for
the current local calendar day, it runs the same bounded smoke harness.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

LOCK_RELATIVE_PATH = Path("System/.dex/session-health.lock")
REPORT_RELATIVE_PATH = Path("System/.smoke-last-run.json")
SUCCESS_RELATIVE_PATH = Path("System/.dex/session-health-success.json")
SMOKE_TIMEOUT_SECONDS = 300


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _aware_now(now: datetime) -> datetime:
    return now if now.tzinfo is not None else now.astimezone()


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _read_report(vault_root: Path) -> dict[str, Any] | None:
    try:
        value = json.loads((vault_root / REPORT_RELATIVE_PATH).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _success_marker_is_today(vault_root: Path, *, now: datetime) -> bool:
    current = _aware_now(now)
    try:
        marker = json.loads(
            (vault_root / SUCCESS_RELATIVE_PATH).read_text(encoding="utf-8")
        )
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
        return False
    return (
        isinstance(marker, dict)
        and marker.get("schema_version") == 1
        and marker.get("local_date") == current.date().isoformat()
    )


def _write_success_marker(vault_root: Path, *, now: datetime) -> None:
    current = _aware_now(now)
    marker_path = vault_root / SUCCESS_RELATIVE_PATH
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = marker_path.with_name(
        f".session-health-success.{os.getpid()}.json"
    )
    payload = {
        "schema_version": 1,
        "local_date": current.date().isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, marker_path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _report_is_clean_today(
    report: dict[str, Any] | None,
    *,
    now: datetime,
) -> bool:
    current = _aware_now(now)
    if report is None:
        return False
    generated_at = _parse_timestamp(report.get("generated_at"))
    summary = report.get("summary")
    if generated_at is None or not isinstance(summary, dict):
        return False
    broken = summary.get("broken")
    unknown = summary.get("unknown")
    if not isinstance(broken, int) or isinstance(broken, bool):
        return False
    if not isinstance(unknown, int) or isinstance(unknown, bool):
        return False
    local_timezone = current.tzinfo
    if local_timezone is None:
        return False
    return (
        generated_at.astimezone(local_timezone).date() == current.date()
        and broken == 0
        and unknown == 0
    )


def needs_session_start_check(
    vault_root: Path,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether today's local calendar day lacks a clean smoke report."""
    vault = vault_root.resolve()
    current = now or _local_now()
    return not (
        _success_marker_is_today(vault, now=current)
        and _report_is_clean_today(_read_report(vault), now=current)
    )


def _run_bounded_smoke(vault_root: Path, repo_root: Path) -> int:
    smoke_path = repo_root / "core" / "utils" / "smoke.py"
    if not smoke_path.is_file():
        return 2
    env = os.environ.copy()
    env.update(
        {
            "VAULT_PATH": str(vault_root),
            "VAULT_ROOT": str(vault_root),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    try:
        result = subprocess.run(
            [sys.executable, str(smoke_path), "--json", "--ledger"],
            cwd=vault_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=SMOKE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 2
    return result.returncode


def run_session_start_check(
    vault_root: Path,
    repo_root: Path,
    *,
    now: datetime | None = None,
) -> int:
    """Run today's fallback check at most once concurrently.

    Return codes:
      0: a clean report already exists, another process owns the check, or the
         new check completed cleanly.
      1: the check completed with one or more broken journeys.
      2: the check could not complete or its report was missing/malformed.
      3: the check completed but remained inconclusive.
    """
    vault = vault_root.resolve()
    repository = repo_root.resolve()
    current = now or _local_now()
    if not needs_session_start_check(vault, now=current):
        return 0

    lock_path = vault / LOCK_RELATIVE_PATH
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = lock_path.open("a+", encoding="utf-8")
    except OSError:
        return 2

    with lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        except OSError:
            return 2

        # The nightly job or another session may have finished between the
        # optimistic read above and acquisition of the process-safe lock.
        if not needs_session_start_check(vault, now=current):
            return 0

        smoke_status = _run_bounded_smoke(vault, repository)
        report = _read_report(vault)
        if smoke_status == 0 and _report_is_clean_today(report, now=current):
            try:
                _write_success_marker(vault, now=current)
            except OSError:
                return 2
            return 0

        generated_at = _parse_timestamp(report.get("generated_at")) if report else None
        summary = report.get("summary") if report else None
        local_timezone = current.tzinfo
        report_is_today = (
            generated_at is not None
            and local_timezone is not None
            and generated_at.astimezone(local_timezone).date() == current.date()
        )
        if report_is_today and isinstance(summary, dict):
            broken = summary.get("broken")
            unknown = summary.get("unknown")
            if isinstance(broken, int) and not isinstance(broken, bool) and broken > 0:
                return 1
            if isinstance(unknown, int) and not isinstance(unknown, bool) and unknown > 0:
                return 3
        return smoke_status if smoke_status in {1, 2} else 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Dex's smoke health check once per successful local day."
    )
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args(argv)
    return run_session_start_check(args.vault, args.repo)


if __name__ == "__main__":
    raise SystemExit(main())
