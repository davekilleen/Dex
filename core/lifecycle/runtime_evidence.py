"""Bounded read-only probes for transaction and lifecycle runtime evidence."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from core.lifecycle.filesystem import FilesystemInspectionError, bounded_read
from core.lifecycle.secrets import assert_no_denied_metadata, redact_document
from core.transaction.engine import TX_ROOT_RELATIVE
from core.transaction.lock import LOCK_RELATIVE

LIFECYCLE_RELATIVE = Path("System") / ".dex" / "lifecycle"
LEDGER_RELATIVE = LIFECYCLE_RELATIVE / "ledger"
MAX_LOCK_BYTES = 64 * 1024
MAX_JOURNAL_BYTES = 4 * 1024 * 1024
MAX_TRANSACTIONS = 10_000
JOURNAL_EVENTS = frozenset(
    {
        "BEGIN",
        "STAGED",
        "SNAPSHOT-START",
        "SNAPSHOT-DONE",
        "APPLY-START",
        "APPLYING",
        "APPLIED",
        "NOT-APPLIED",
        "APPLY-DONE",
        "VERIFY-START",
        "VERIFY-DONE",
        "COMMITTED",
        "ROLLED-BACK",
    }
)


@dataclass(frozen=True)
class LockEvidence:
    path: str
    state: str
    pid: int | None = None
    kind: str | None = None
    at: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "state": self.state,
            "pid": self.pid,
            "kind": self.kind,
            "at": self.at,
            "error": self.error,
        }


@dataclass(frozen=True)
class TransactionEvidence:
    path: str
    state: str
    journal_present: bool
    events: tuple[str, ...]
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "state": self.state,
            "journal_present": self.journal_present,
            "events": list(self.events),
            "error": self.error,
        }


@dataclass(frozen=True)
class LedgerEvidence:
    path: str
    state: str
    events_directory_present: bool
    event_file_count: int
    state_file_present: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "state": self.state,
            "events_directory_present": self.events_directory_present,
            "event_file_count": self.event_file_count,
            "state_file_present": self.state_file_present,
        }


@dataclass(frozen=True)
class RuntimeEvidenceReport:
    lock: LockEvidence
    transactions: tuple[TransactionEvidence, ...]
    ledger: LedgerEvidence
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        raw = {
            "lock": self.lock.to_dict(),
            "transactions": [entry.to_dict() for entry in self.transactions],
            "ledger": self.ledger.to_dict(),
            "errors": list(self.errors),
        }
        redacted = redact_document(raw)
        assert_no_denied_metadata(redacted)
        assert isinstance(redacted, dict)
        return redacted


def _is_real_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _is_real_directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _probe_lock(root: Path) -> LockEvidence:
    relative = LOCK_RELATIVE.as_posix()
    target = root / LOCK_RELATIVE
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return LockEvidence(relative, "ABSENT")
    except OSError as error:
        return LockEvidence(relative, "UNKNOWN", error=error.__class__.__name__)
    if not stat.S_ISREG(metadata.st_mode):
        return LockEvidence(relative, "UNKNOWN", error="lock is not a regular file")
    try:
        payload = json.loads(bounded_read(root, relative, max_bytes=MAX_LOCK_BYTES))
    except (FilesystemInspectionError, json.JSONDecodeError) as error:
        return LockEvidence(relative, "UNKNOWN", error=str(error))
    if not isinstance(payload, dict):
        return LockEvidence(relative, "UNKNOWN", error="lock payload is not an object")
    pid = payload.get("pid")
    kind = payload.get("kind")
    at = payload.get("at")
    if not isinstance(pid, int) or not isinstance(kind, str) or not isinstance(at, str):
        return LockEvidence(relative, "UNKNOWN", error="lock payload fields are invalid")
    # Deliberately omit the ownership token from every output.
    return LockEvidence(relative, "PRESENT", pid=pid, kind=kind, at=at)


def _journal_events(root: Path, relative: str) -> tuple[tuple[str, ...], str | None]:
    try:
        raw = bounded_read(root, relative, max_bytes=MAX_JOURNAL_BYTES)
    except FilesystemInspectionError as error:
        return (), str(error)
    events: list[str] = []
    for index, line in enumerate(raw.splitlines(), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return tuple(events), f"journal line {index} is invalid JSON"
        if not isinstance(record, dict):
            return tuple(events), f"journal line {index} is not an object"
        event = record.get("event")
        payload = record.get("payload")
        sequence = record.get("sequence")
        if (
            record.get("schema_version") != 1
            or sequence != index
            or event not in JOURNAL_EVENTS
            or not isinstance(payload, dict)
        ):
            return tuple(events), f"journal line {index} has invalid closed fields"
        expected_sha = hashlib.sha256(
            json.dumps(
                {key: value for key, value in record.items() if key != "sha"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if record.get("sha") != expected_sha:
            return tuple(events), f"journal line {index} fails its integrity hash"
        events.append(event)
    if not events:
        return (), "journal is empty"
    return tuple(events), None


def _probe_transactions(root: Path) -> tuple[tuple[TransactionEvidence, ...], tuple[str, ...]]:
    tx_root = root / TX_ROOT_RELATIVE
    if not _is_real_directory(tx_root):
        return (), ()
    try:
        with os.scandir(tx_root) as iterator:
            children = sorted(iterator, key=lambda entry: entry.name)
    except OSError as error:
        return (), (f"transaction root unreadable: {error.__class__.__name__}",)
    errors: list[str] = []
    evidence: list[TransactionEvidence] = []
    if len(children) > MAX_TRANSACTIONS:
        children = children[:MAX_TRANSACTIONS]
        errors.append("transaction directory count exceeded its configured bound")
    for child in children:
        relative = (TX_ROOT_RELATIVE / child.name).as_posix()
        try:
            metadata = child.stat(follow_symlinks=False)
        except OSError as error:
            evidence.append(TransactionEvidence(relative, "UNKNOWN", False, (), error.__class__.__name__))
            continue
        if not stat.S_ISDIR(metadata.st_mode):
            evidence.append(TransactionEvidence(relative, "UNKNOWN", False, (), "not a real directory"))
            continue
        journal_relative = f"{relative}/journal.jsonl"
        if not _is_real_file(root / journal_relative):
            evidence.append(TransactionEvidence(relative, "UNKNOWN", False, (), "journal absent"))
            continue
        events, error = _journal_events(root, journal_relative)
        if error:
            state = "UNKNOWN"
        elif events[-1] in {"COMMITTED", "ROLLED-BACK"}:
            state = events[-1]
        else:
            state = "INTERRUPTED"
        evidence.append(TransactionEvidence(relative, state, True, events, error))
    return tuple(evidence), tuple(errors)


def _probe_ledger(root: Path) -> LedgerEvidence:
    ledger = root / LEDGER_RELATIVE
    events = ledger / "events"
    state_file = root / LIFECYCLE_RELATIVE / "state.json"
    event_count = 0
    events_present = _is_real_directory(events)
    if events_present:
        try:
            with os.scandir(events) as iterator:
                event_count = sum(
                    1
                    for entry in iterator
                    if stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode)
                )
        except OSError:
            return LedgerEvidence(LEDGER_RELATIVE.as_posix(), "UNKNOWN", True, 0, _is_real_file(state_file))
    present = _is_real_directory(ledger)
    return LedgerEvidence(
        LEDGER_RELATIVE.as_posix(),
        "PRESENT" if present else "ABSENT",
        events_present,
        event_count,
        _is_real_file(state_file),
    )


def probe_runtime_evidence(vault_root: Path) -> RuntimeEvidenceReport:
    """Inspect locks, tx journals/directories, and ledger presence read-only."""
    root = Path(vault_root)
    lock = _probe_lock(root)
    transactions, tx_errors = _probe_transactions(root)
    errors = list(tx_errors)
    if lock.error:
        errors.append(lock.error)
    errors.extend(entry.error for entry in transactions if entry.error)
    return RuntimeEvidenceReport(lock, transactions, _probe_ledger(root), tuple(sorted(set(errors))))


__all__ = [
    "LEDGER_RELATIVE",
    "LIFECYCLE_RELATIVE",
    "LedgerEvidence",
    "LockEvidence",
    "RuntimeEvidenceReport",
    "TransactionEvidence",
    "probe_runtime_evidence",
]
