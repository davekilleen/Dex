"""The health promise register: every recurring job declares its receipt.

The v1.84.0 field incident proved that activity is not health: meeting sync
failed silently for six days while its log kept growing and every check that
asked "is it running?" stayed green.  This register makes the opposite
question authoritative.  Each entry is a promise — "this job succeeds at
least every ``cadence``, and a completed run writes this receipt" — and the
auditor (Doctor's background-job freshness check, which Proactive Health
snapshots) walks the register looking for broken promises.

Two rules keep the register honest:

* **Declared, not inferred.** The register is the truth.  A build-time
  scanner (``scripts/generate-health-promises.py --check``) infers background
  jobs from the shipped launchd templates and shell installers and fails the
  build when a job exists with no registered promise, so the register cannot
  silently fall behind the code.  (The scan covers ``.plist``/``.sh``
  sources; an installer written in another language must add its label here
  deliberately.)
* **Activity-only receipts say so.** A log file that grows on every attempt
  proves the job ran, not that it worked.  Entries whose only receipt is
  activity carry ``activity_only=True`` and every surface that reports them
  must say "running" rather than "succeeding".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.utils.timezone import parse_timestamp

RECEIPT_KINDS = frozenset({"json-timestamp", "file-activity", "daemon"})


@dataclass(frozen=True)
class HealthPromise:
    """One recurring job's declared success contract."""

    id: str
    label: str
    cadence: timedelta | None
    receipt_kind: str
    receipt_path: str
    receipt_key: str | None = None
    activity_only: bool = False

    def __post_init__(self) -> None:
        if self.receipt_kind not in RECEIPT_KINDS:
            raise ValueError(f"unknown receipt kind {self.receipt_kind!r}")
        if self.receipt_kind == "json-timestamp" and not self.receipt_key:
            raise ValueError("json-timestamp promises must name their receipt key")
        if self.receipt_kind == "daemon":
            if self.cadence is not None:
                raise ValueError("daemon promises have no cadence; liveness is launchd's job")
        elif self.cadence is None:
            raise ValueError("periodic promises must declare a cadence")


# Every launchd label Dex ships must appear here (the scanner gate enforces
# it).  Cadence is the promise, not the schedule: it includes slack for
# machines that sleep.
PROMISES: tuple[HealthPromise, ...] = (
    HealthPromise(
        id="com.dex.meeting-intel",
        label="Meeting sync",
        cadence=timedelta(hours=48),
        receipt_kind="json-timestamp",
        receipt_path=".scripts/meeting-intel/processed-meetings.json",
        receipt_key="lastSync",
    ),
    HealthPromise(
        id="com.dex.smoke-nightly",
        label="Nightly smoke",
        cadence=timedelta(hours=26),
        # .scripts/nightly-smoke.sh appends this log only after a zero exit,
        # so its age is a genuine success receipt.  System/.smoke-last-run.json
        # is deliberately NOT the receipt: smoke rewrites it on every run,
        # including total harness failures, so it proves activity only.
        receipt_kind="file-activity",
        receipt_path=".scripts/logs/smoke-nightly.log",
    ),
    HealthPromise(
        id="com.dex.changelog-checker",
        label="Claude update watcher",
        cadence=timedelta(days=7),
        receipt_kind="file-activity",
        receipt_path=".scripts/logs/changelog-checker.log",
        activity_only=True,
    ),
    HealthPromise(
        id="com.dex.learning-review",
        label="Learning review",
        cadence=timedelta(days=7),
        receipt_kind="file-activity",
        receipt_path=".scripts/logs/learning-review.log",
        activity_only=True,
    ),
    HealthPromise(
        id="com.dex.obsidian-sync",
        label="Obsidian sync daemon",
        cadence=None,
        receipt_kind="daemon",
        receipt_path="System/obsidian-sync.log",
        activity_only=True,
    ),
)


@dataclass(frozen=True)
class PromiseAudit:
    """The auditor's verdict for one installed promise."""

    promise: HealthPromise
    state: str  # "kept" | "never" | "broken"
    last_success: datetime | None = None

    def detail(self) -> str:
        label = self.promise.label
        verb = "ran" if self.promise.activity_only else "completed successfully"
        if self.state == "never":
            if self.promise.activity_only:
                return f"{label} has never run"
            return (
                f"{label} has never recorded a completed run "
                "(a job can keep writing its log while failing every time)"
            )
        assert self.last_success is not None
        stamp = self.last_success.date().isoformat()
        if self.state == "broken":
            suffix = "" if self.promise.activity_only else " — it may still be running without succeeding"
            return f"{label} last {verb} on {stamp}{suffix}"
        return f"{label} last {verb} on {stamp}"


def promise_by_id(promise_id: str) -> HealthPromise | None:
    for promise in PROMISES:
        if promise.id == promise_id:
            return promise
    return None


def read_receipt_timestamp(vault_root: str | Path, promise: HealthPromise) -> datetime | None:
    """Read the promise's receipt without trusting anything malformed."""
    path = Path(vault_root) / promise.receipt_path
    if not path.is_file():
        return None
    if promise.receipt_kind != "json-timestamp":
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = document.get(promise.receipt_key) if isinstance(document, dict) else None
    parsed = parse_timestamp(value)
    return parsed.astimezone(timezone.utc) if parsed is not None else None


def audit_promise(
    vault_root: str | Path,
    promise: HealthPromise,
    *,
    now: datetime | None = None,
) -> PromiseAudit:
    """Judge one installed periodic promise: kept, never succeeded, or broken."""
    if promise.receipt_kind == "daemon":
        raise ValueError("daemon promises have no cadence to audit; launchd liveness is their check")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    recorded = read_receipt_timestamp(vault_root, promise)
    if recorded is None:
        return PromiseAudit(promise, "never")
    assert promise.cadence is not None
    if current - recorded > promise.cadence:
        return PromiseAudit(promise, "broken", last_success=recorded)
    return PromiseAudit(promise, "kept", last_success=recorded)


__all__ = [
    "PROMISES",
    "HealthPromise",
    "PromiseAudit",
    "audit_promise",
    "promise_by_id",
    "read_receipt_timestamp",
]
