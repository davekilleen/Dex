"""Repair Dex bookkeeping files that Windows text-mode writes left unreadable.

Phase 2 of the Windows support spec. Detection is read-only and identical on
every OS. Apply rewrites only an exact trailing-CRLF difference on the
activation record, adoption receipts, and topology receipts. Ledger events
with a trailing CRLF are detected and blocked — they are never rewritten.

Snapshots taken before this repair are marked with a flag written at the
start of each operation (never a clock comparison). Restore of those
snapshots is refused on Windows, including crash-recovery rollback.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from core.lifecycle.bridge import (
    ACTIVATION_RELATIVE,
    _canonical,
    _well_formed_activation,
)
from core.lifecycle.engine import (
    ADOPTION_RECEIPTS_RELATIVE,
    TOPOLOGY_RECEIPTS_RELATIVE,
    AdoptionReceipt,
    canonical_adoption_receipt_bytes,
    load_adoption_receipt,
)
from core.lifecycle.ledger import LEDGER_RELATIVE, _canonical_bytes
from core.transaction.byte_mode_flag import (
    HASH_READ_MODE_BINARY,
    snapshot_is_pre_repair,
    stamp_unmarked_snapshots_pre_repair,
)
from core.transaction.engine import TX_ROOT_RELATIVE
from core.transaction.fsync import fsync_directory
from core.transaction.journal import Journal, JournalCorruptError
from core.transaction.lock import acquire_owned_lock
from core.utils.os_flags import binary_write_flags

BYTE_MODE_VERSION = 1
MARKER_RELATIVE = Path("System/.dex/lifecycle/byte-mode.json")
QUARANTINE_ROOT_RELATIVE = Path("System/.dex/lifecycle/byte-mode-quarantine")

FINDING_CRLF_TAIL = "crlf-tail"
FINDING_TEXT_MODE_BASELINE = "text-mode-baseline"
FINDING_LEDGER_CRLF = "ledger-crlf"
FINDING_UNEXPLAINED = "unexplained"

ACTION_RE_RECORDED = "re-recorded"
ACTION_BYTES_NORMALISED = "bytes-normalised"
ACTION_BLOCKED = "blocked"

UNEXPLAINED_REASON = (
    "record is non-canonical for a reason the Windows byte-mode migration "
    "does not explain"
)
LEDGER_BLOCK_REASON = (
    "a history file has Windows line endings; Dex will not rewrite history. "
    "Run /dex-doctor."
)

MESSAGE_APPLY = (
    "Dex is putting right some of its own bookkeeping files that were written "
    "with Windows line endings. Your notes are not touched. A copy of each "
    "file before the change is kept in "
    "System/.dex/lifecycle/byte-mode-quarantine."
)
MESSAGE_BLOCKING = (
    "Dex found a bookkeeping file it cannot safely repair on its own: {relative}. "
    "Nothing was changed. Run /dex-doctor, or "
    "`python -m core.lifecycle.cli --vault-root {vault} byte-mode status` "
    "to see the detail."
)
MESSAGE_REWIND_REFUSED = (
    "This update was recorded before Dex fixed how it reads files on Windows, "
    "so its undo copy may have altered line endings. Dex will not restore it. "
    "Your current files are untouched; to go back, restore from your own backup."
)
MESSAGE_ROLLBACK_REFUSED = (
    "The bookkeeping repair cannot be undone because Dex has recorded newer "
    "updates since. The pre-repair copies are still in {quarantine} if you "
    "need them."
)


class ByteModeError(RuntimeError):
    """The Windows bookkeeping repair could not proceed safely."""


class ByteModeBlocked(ByteModeError):
    """A record is non-canonical in a way this repair will not touch."""

    def __init__(self, relative: str, vault_root: Path | None = None) -> None:
        self.relative = relative
        vault = vault_root if vault_root is not None else Path("<vault>")
        super().__init__(MESSAGE_BLOCKING.format(relative=relative, vault=vault))


class ByteModeRollbackRefused(ByteModeError):
    """Rollback is refused because newer updates were recorded after repair."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_json(raw: bytes) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"repeats field {key!r}")
            result[key] = value
        return result

    return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)


def _crlf_variant(raw: bytes, canonical: bytes) -> bool:
    return raw == canonical.replace(b"\n", b"\r\n")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _atomic_write(target: Path, data: bytes) -> None:
    directory = target.parent
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = directory / f".{target.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            binary_write_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL),
            0o600,
        )
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, target)
        os.chmod(target, 0o600)
        fsync_directory(directory)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def canonical_topology_receipt_bytes(receipt: object) -> bytes:
    """Canonical bytes for a topology receipt document."""
    return (
        json.dumps(
            receipt,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _activation_shape(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        return None
    expected = {
        "activation_version",
        "api_version",
        "bridge_release_version",
        "baseline_inventory_sha256",
    }
    if set(raw) != expected:
        return None
    if type(raw["activation_version"]) is not int or raw["activation_version"] != 1:
        return None
    if not isinstance(raw["api_version"], str):
        return None
    recorded = raw["bridge_release_version"]
    digest = raw["baseline_inventory_sha256"]
    if not isinstance(recorded, str) or not isinstance(digest, str):
        return None
    return dict(raw)


@dataclass(frozen=True)
class ByteModeFinding:
    record: str
    finding: str
    action: str
    reason: str | None = None
    previous_bytes_sha256: str | None = None
    new_bytes_sha256: str | None = None
    document_identity_unchanged: bool | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "record": self.record,
            "finding": self.finding,
            "action": self.action,
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.previous_bytes_sha256 is not None:
            payload["previous_bytes_sha256"] = self.previous_bytes_sha256
        if self.new_bytes_sha256 is not None:
            payload["new_bytes_sha256"] = self.new_bytes_sha256
        if self.document_identity_unchanged is not None:
            payload["document_identity_unchanged"] = self.document_identity_unchanged
        return payload


@dataclass
class ByteModeReport:
    findings: list[ByteModeFinding] = field(default_factory=list)
    rewind_unsafe: list[str] = field(default_factory=list)
    blocking: list[ByteModeFinding] = field(default_factory=list)
    state: str = "needs-repair"

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "findings": [finding.to_dict() for finding in self.findings],
            "rewind_unsafe": list(self.rewind_unsafe),
            "blocking": [finding.to_dict() for finding in self.blocking],
        }

    @property
    def repairable(self) -> list[ByteModeFinding]:
        return [
            finding
            for finding in self.findings
            if finding.action in {ACTION_RE_RECORDED, ACTION_BYTES_NORMALISED}
        ]


def _marker_path(vault_root: Path) -> Path:
    return Path(vault_root) / MARKER_RELATIVE


def load_marker(vault_root: Path) -> dict[str, object] | None:
    path = _marker_path(vault_root)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        raw = path.read_bytes()
        document = _strict_json(raw)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    if raw != _canonical(document):
        return None
    return document


def marker_is_binary_for_this_platform(vault_root: Path) -> bool:
    marker = load_marker(vault_root)
    if marker is None:
        return False
    return (
        marker.get("hash_read_mode") == HASH_READ_MODE_BINARY
        and marker.get("platform") == sys.platform
    )


def _committed_tx_ids(vault_root: Path) -> list[str]:
    tx_root = Path(vault_root) / TX_ROOT_RELATIVE
    if not tx_root.is_dir() or tx_root.is_symlink():
        return []
    committed: list[str] = []
    for tx_dir in sorted(tx_root.iterdir(), key=lambda path: path.name):
        if tx_dir.is_symlink() or not tx_dir.is_dir():
            continue
        journal = tx_dir / "journal.jsonl"
        if journal.is_symlink() or not journal.is_file():
            continue
        try:
            events = {entry.event for entry in Journal(journal).read()}
        except (JournalCorruptError, OSError):
            continue
        if "COMMITTED" in events:
            committed.append(tx_dir.name)
    return committed


def _ledger_last_seq(vault_root: Path) -> int:
    """Read last_seq without taking the ledger lock.

    Apply already holds the write lock; calling ``project_state`` here would
    deadlock on a second flock of the same file.
    """
    ledger_root = Path(vault_root) / LEDGER_RELATIVE
    if not ledger_root.exists():
        return 0
    try:
        from core.lifecycle.ledger import _project_state_unlocked

        state = _project_state_unlocked(Path(vault_root))
        last_seq = state.get("last_seq", 0)
        return last_seq if type(last_seq) is int and last_seq >= 0 else 0
    except Exception:
        return 0


def _detect_activation(vault_root: Path, marker_present: bool) -> tuple[
    list[ByteModeFinding],
    list[ByteModeFinding],
]:
    findings: list[ByteModeFinding] = []
    blocking: list[ByteModeFinding] = []
    path = Path(vault_root) / ACTIVATION_RELATIVE
    relative = ACTIVATION_RELATIVE.as_posix()
    if path.is_symlink():
        blocking.append(
            ByteModeFinding(relative, FINDING_UNEXPLAINED, ACTION_BLOCKED, UNEXPLAINED_REASON)
        )
        return findings, blocking
    if not path.is_file():
        return findings, blocking
    try:
        raw = path.read_bytes()
    except OSError:
        blocking.append(
            ByteModeFinding(relative, FINDING_UNEXPLAINED, ACTION_BLOCKED, UNEXPLAINED_REASON)
        )
        return findings, blocking
    if _well_formed_activation(raw) is not None:
        if not marker_present and sys.platform == "win32":
            findings.append(
                ByteModeFinding(
                    relative,
                    FINDING_TEXT_MODE_BASELINE,
                    ACTION_RE_RECORDED,
                    previous_bytes_sha256=_sha256_bytes(raw),
                )
            )
        return findings, blocking
    try:
        document = _activation_shape(_strict_json(raw))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        document = None
    if document is not None and _crlf_variant(raw, _canonical(document)):
        findings.append(
            ByteModeFinding(
                relative,
                FINDING_CRLF_TAIL,
                ACTION_RE_RECORDED,
                previous_bytes_sha256=_sha256_bytes(raw),
            )
        )
        return findings, blocking
    blocking.append(
        ByteModeFinding(relative, FINDING_UNEXPLAINED, ACTION_BLOCKED, UNEXPLAINED_REASON)
    )
    return findings, blocking


def _detect_adoption_receipts(vault_root: Path) -> tuple[
    list[ByteModeFinding],
    list[ByteModeFinding],
]:
    findings: list[ByteModeFinding] = []
    blocking: list[ByteModeFinding] = []
    directory = Path(vault_root) / ADOPTION_RECEIPTS_RELATIVE
    if not directory.exists():
        return findings, blocking
    if directory.is_symlink() or not directory.is_dir():
        blocking.append(
            ByteModeFinding(
                ADOPTION_RECEIPTS_RELATIVE.as_posix(),
                FINDING_UNEXPLAINED,
                ACTION_BLOCKED,
                UNEXPLAINED_REASON,
            )
        )
        return findings, blocking
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.name.startswith("."):
            continue
        relative = path.relative_to(vault_root).as_posix()
        if path.is_symlink() or not path.is_file() or not path.name.endswith(".receipt.json"):
            blocking.append(
                ByteModeFinding(relative, FINDING_UNEXPLAINED, ACTION_BLOCKED, UNEXPLAINED_REASON)
            )
            continue
        try:
            raw = path.read_bytes()
            document = _strict_json(raw)
            receipt = AdoptionReceipt.from_dict(document)
            canonical = canonical_adoption_receipt_bytes(receipt)
        except Exception:
            blocking.append(
                ByteModeFinding(relative, FINDING_UNEXPLAINED, ACTION_BLOCKED, UNEXPLAINED_REASON)
            )
            continue
        if raw == canonical:
            continue
        if _crlf_variant(raw, canonical):
            findings.append(
                ByteModeFinding(
                    relative,
                    FINDING_CRLF_TAIL,
                    ACTION_BYTES_NORMALISED,
                    previous_bytes_sha256=_sha256_bytes(raw),
                    document_identity_unchanged=True,
                )
            )
            continue
        blocking.append(
            ByteModeFinding(relative, FINDING_UNEXPLAINED, ACTION_BLOCKED, UNEXPLAINED_REASON)
        )
    return findings, blocking


def _detect_topology_receipts(vault_root: Path) -> tuple[
    list[ByteModeFinding],
    list[ByteModeFinding],
]:
    findings: list[ByteModeFinding] = []
    blocking: list[ByteModeFinding] = []
    directory = Path(vault_root) / TOPOLOGY_RECEIPTS_RELATIVE
    if not directory.exists():
        return findings, blocking
    if directory.is_symlink() or not directory.is_dir():
        blocking.append(
            ByteModeFinding(
                TOPOLOGY_RECEIPTS_RELATIVE.as_posix(),
                FINDING_UNEXPLAINED,
                ACTION_BLOCKED,
                UNEXPLAINED_REASON,
            )
        )
        return findings, blocking
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.name.startswith("."):
            continue
        relative = path.relative_to(vault_root).as_posix()
        if path.is_symlink() or not path.is_file() or not path.name.endswith(".receipt.json"):
            blocking.append(
                ByteModeFinding(relative, FINDING_UNEXPLAINED, ACTION_BLOCKED, UNEXPLAINED_REASON)
            )
            continue
        try:
            raw = path.read_bytes()
            document = _strict_json(raw)
            if not isinstance(document, dict):
                raise ValueError("topology receipt must be an object")
            canonical = canonical_topology_receipt_bytes(document)
        except Exception:
            blocking.append(
                ByteModeFinding(relative, FINDING_UNEXPLAINED, ACTION_BLOCKED, UNEXPLAINED_REASON)
            )
            continue
        if raw == canonical:
            continue
        if _crlf_variant(raw, canonical):
            findings.append(
                ByteModeFinding(
                    relative,
                    FINDING_CRLF_TAIL,
                    ACTION_BYTES_NORMALISED,
                    previous_bytes_sha256=_sha256_bytes(raw),
                    document_identity_unchanged=True,
                )
            )
            continue
        blocking.append(
            ByteModeFinding(relative, FINDING_UNEXPLAINED, ACTION_BLOCKED, UNEXPLAINED_REASON)
        )
    return findings, blocking


def _detect_ledger_events(vault_root: Path) -> list[ByteModeFinding]:
    """DETECT-AND-BLOCK only: never rewrite ledger event files."""
    blocking: list[ByteModeFinding] = []
    events_dir = Path(vault_root) / LEDGER_RELATIVE / "events"
    if not events_dir.exists():
        return blocking
    if events_dir.is_symlink() or not events_dir.is_dir():
        blocking.append(
            ByteModeFinding(
                (LEDGER_RELATIVE / "events").as_posix(),
                FINDING_UNEXPLAINED,
                ACTION_BLOCKED,
                UNEXPLAINED_REASON,
            )
        )
        return blocking
    for path in sorted(events_dir.iterdir(), key=lambda item: item.name):
        if path.name.startswith("."):
            continue
        relative = path.relative_to(vault_root).as_posix()
        if path.is_symlink() or not path.is_file() or not path.name.endswith(".json"):
            blocking.append(
                ByteModeFinding(relative, FINDING_UNEXPLAINED, ACTION_BLOCKED, UNEXPLAINED_REASON)
            )
            continue
        try:
            raw = path.read_bytes()
            document = _strict_json(raw)
            if not isinstance(document, dict):
                raise ValueError("ledger event must be an object")
            canonical = _canonical_bytes(document, relative)
        except Exception:
            blocking.append(
                ByteModeFinding(relative, FINDING_UNEXPLAINED, ACTION_BLOCKED, UNEXPLAINED_REASON)
            )
            continue
        if raw == canonical:
            continue
        if _crlf_variant(raw, canonical):
            blocking.append(
                ByteModeFinding(
                    relative,
                    FINDING_LEDGER_CRLF,
                    ACTION_BLOCKED,
                    LEDGER_BLOCK_REASON,
                    previous_bytes_sha256=_sha256_bytes(raw),
                )
            )
            continue
        blocking.append(
            ByteModeFinding(relative, FINDING_UNEXPLAINED, ACTION_BLOCKED, UNEXPLAINED_REASON)
        )
    return blocking


def _detect_rewind_unsafe(vault_root: Path) -> list[str]:
    tx_root = Path(vault_root) / TX_ROOT_RELATIVE
    if not tx_root.is_dir() or tx_root.is_symlink():
        return []
    unsafe: list[str] = []
    for tx_dir in sorted(tx_root.iterdir(), key=lambda path: path.name):
        if tx_dir.is_symlink() or not tx_dir.is_dir():
            continue
        journal = tx_dir / "journal.jsonl"
        if journal.is_symlink() or not journal.is_file():
            continue
        try:
            events = {entry.event for entry in Journal(journal).read()}
        except (JournalCorruptError, OSError):
            continue
        if "COMMITTED" not in events:
            continue
        if snapshot_is_pre_repair(tx_dir):
            unsafe.append(f"System/.dex/tx/{tx_dir.name}/snapshot")
    return unsafe


def detect(vault_root: Path) -> ByteModeReport:
    """Read-only scan. Identical on every OS."""
    root = Path(vault_root)
    marker = load_marker(root)
    marker_present = marker is not None
    findings: list[ByteModeFinding] = []
    blocking: list[ByteModeFinding] = []

    activation_findings, activation_blocking = _detect_activation(root, marker_present)
    findings.extend(activation_findings)
    blocking.extend(activation_blocking)

    receipt_findings, receipt_blocking = _detect_adoption_receipts(root)
    findings.extend(receipt_findings)
    blocking.extend(receipt_blocking)

    topology_findings, topology_blocking = _detect_topology_receipts(root)
    findings.extend(topology_findings)
    blocking.extend(topology_blocking)

    blocking.extend(_detect_ledger_events(root))
    rewind_unsafe = _detect_rewind_unsafe(root)

    if blocking:
        state = "blocked"
    elif findings or rewind_unsafe:
        state = "needs-repair"
    else:
        state = "binary"
    return ByteModeReport(
        findings=findings,
        rewind_unsafe=rewind_unsafe,
        blocking=blocking,
        state=state,
    )


def _quarantine_copy(vault_root: Path, relative: str, quarantine: Path) -> None:
    source = Path(vault_root) / relative
    destination = quarantine / relative
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.write_bytes(source.read_bytes())
    os.chmod(destination, 0o600)


def _remove_older_quarantines(quarantine_root: Path, keep: Path) -> None:
    if not quarantine_root.is_dir():
        return
    for candidate in quarantine_root.iterdir():
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        if candidate.resolve() == keep.resolve():
            continue
        shutil.rmtree(candidate)


@contextmanager
def _ledger_write_lock(vault_root: Path) -> Iterator[None]:
    ledger_root = Path(vault_root) / LEDGER_RELATIVE
    if not ledger_root.exists():
        yield
        return
    try:
        from core.lifecycle.ledger import _write_lock
    except Exception:
        yield
        return
    try:
        with _write_lock(vault_root):
            yield
    except ModuleNotFoundError:
        yield


def _normalize_receipt(vault_root: Path, finding: ByteModeFinding) -> ByteModeFinding:
    path = Path(vault_root) / finding.record
    raw = path.read_bytes()
    document = _strict_json(raw)
    if finding.record.startswith(TOPOLOGY_RECEIPTS_RELATIVE.as_posix()):
        if not isinstance(document, dict):
            raise ByteModeError(f"{finding.record} is not a topology receipt object")
        original = json.loads(raw.decode("utf-8"))
        canonical = canonical_topology_receipt_bytes(document)
        _atomic_write(path, canonical)
        rewritten = path.read_bytes()
        if rewritten != canonical:
            raise ByteModeError(f"{finding.record} did not stay canonical after repair")
        if json.loads(rewritten.decode("utf-8")) != original:
            raise ByteModeError(f"{finding.record} identity changed during repair")
        return ByteModeFinding(
            finding.record,
            finding.finding,
            ACTION_BYTES_NORMALISED,
            previous_bytes_sha256=finding.previous_bytes_sha256,
            new_bytes_sha256=_sha256_bytes(rewritten),
            document_identity_unchanged=True,
        )
    receipt = AdoptionReceipt.from_dict(document)
    original = AdoptionReceipt.from_dict(json.loads(raw.decode("utf-8")))
    canonical = canonical_adoption_receipt_bytes(receipt)
    _atomic_write(path, canonical)
    transaction_id = Path(finding.record).name.removesuffix(".receipt.json")
    loaded = load_adoption_receipt(Path(vault_root), transaction_id)
    if loaded != original:
        raise ByteModeError(f"{finding.record} identity changed during repair")
    if loaded.inventory_sha256 != original.inventory_sha256:
        raise ByteModeError(f"{finding.record} inventory_sha256 changed during repair")
    rewritten = path.read_bytes()
    return ByteModeFinding(
        finding.record,
        finding.finding,
        ACTION_BYTES_NORMALISED,
        previous_bytes_sha256=finding.previous_bytes_sha256,
        new_bytes_sha256=_sha256_bytes(rewritten),
        document_identity_unchanged=True,
    )


def apply(vault_root: Path, report: ByteModeReport | None = None) -> dict[str, object]:
    """Repair repairable findings. Ledger events are never rewritten."""
    root = Path(vault_root)
    scanned = report if report is not None else detect(root)
    if scanned.blocking:
        raise ByteModeBlocked(scanned.blocking[0].record, root)
    marker = load_marker(root)
    if (
        marker is not None
        and marker.get("hash_read_mode") == HASH_READ_MODE_BINARY
        and marker.get("platform") == sys.platform
        and not scanned.repairable
    ):
        return {
            "state": "binary",
            "actions": [],
            "rewind_unsafe": list(scanned.rewind_unsafe),
            "quarantine": marker.get("quarantine"),
        }

    release = acquire_owned_lock(root, "byte-mode")
    try:
        with _ledger_write_lock(root):
            return _apply_locked(root, scanned)
    finally:
        release()


def _apply_locked(root: Path, scanned: ByteModeReport) -> dict[str, object]:
    now = _utc_now()
    stamp = _stamp(now)
    quarantine_root = root / QUARANTINE_ROOT_RELATIVE
    quarantine = quarantine_root / stamp
    quarantine.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(quarantine, 0o700)

    rewind_unsafe = list(stamp_unmarked_snapshots_pre_repair(root))
    for existing in scanned.rewind_unsafe:
        if existing not in rewind_unsafe:
            rewind_unsafe.append(existing)

    to_copy = [finding.record for finding in scanned.repairable]
    manifest_entries: list[dict[str, str]] = []
    for relative in to_copy:
        source = root / relative
        if source.is_file() and not source.is_symlink():
            _quarantine_copy(root, relative, quarantine)
            manifest_entries.append(
                {"relative": relative, "sha256_before": _sha256_bytes(source.read_bytes())}
            )

    manifest = {
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": manifest_entries,
    }
    _atomic_write(quarantine / "manifest.json", _canonical(manifest))

    actions: list[dict[str, object]] = []
    for finding in scanned.repairable:
        if finding.action == ACTION_BYTES_NORMALISED:
            actions.append(_normalize_receipt(root, finding).to_dict())
            continue
        path = root / finding.record
        if path.is_file() and not path.is_symlink():
            path.unlink()
            fsync_directory(path.parent)
        actions.append(
            {
                "record": finding.record,
                "finding": finding.finding,
                "action": ACTION_RE_RECORDED,
                "previous_bytes_sha256": finding.previous_bytes_sha256,
            }
        )

    marker_document: dict[str, object] = {
        "byte_mode_version": BYTE_MODE_VERSION,
        "hash_read_mode": HASH_READ_MODE_BINARY,
        "platform": sys.platform,
        "migrated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "quarantine": quarantine.relative_to(root).as_posix(),
        "actions": actions,
        "rewind_unsafe": rewind_unsafe,
        "ledger_seq_at_migration": _ledger_last_seq(root),
        "committed_tx_ids_at_migration": _committed_tx_ids(root),
    }
    _atomic_write(_marker_path(root), _canonical(marker_document))
    _remove_older_quarantines(quarantine_root, quarantine)
    if actions:
        print(MESSAGE_APPLY, file=sys.stderr)
    return {
        "state": "binary",
        "actions": actions,
        "rewind_unsafe": rewind_unsafe,
        "quarantine": marker_document["quarantine"],
        "marker": marker_document,
    }


def rollback(vault_root: Path) -> dict[str, object]:
    """Restore quarantined files when no newer update has been recorded."""
    root = Path(vault_root)
    marker = load_marker(root)
    if marker is None:
        raise ByteModeError("there is no bookkeeping repair to undo")
    quarantine_relative = marker.get("quarantine")
    if not isinstance(quarantine_relative, str):
        raise ByteModeError("the bookkeeping repair record is missing its copy folder")
    quarantine = root / quarantine_relative
    recorded_seq = marker.get("ledger_seq_at_migration")
    recorded_txs = marker.get("committed_tx_ids_at_migration")
    current_seq = _ledger_last_seq(root)
    current_txs = _committed_tx_ids(root)
    recorded_tx_set = set(recorded_txs) if isinstance(recorded_txs, list) else None
    if (
        type(recorded_seq) is not int
        or recorded_seq != current_seq
        or recorded_tx_set is None
        or recorded_tx_set != set(current_txs)
    ):
        raise ByteModeRollbackRefused(
            MESSAGE_ROLLBACK_REFUSED.format(quarantine=quarantine_relative)
        )

    release = acquire_owned_lock(root, "byte-mode")
    try:
        with _ledger_write_lock(root):
            locked_seq = _ledger_last_seq(root)
            locked_txs = set(_committed_tx_ids(root))
            if locked_seq != recorded_seq or locked_txs != recorded_tx_set:
                raise ByteModeRollbackRefused(
                    MESSAGE_ROLLBACK_REFUSED.format(quarantine=quarantine_relative)
                )
            restored = _rollback_locked(root, marker, quarantine)
    finally:
        release()
    return restored


def _rollback_locked(
    root: Path,
    marker: dict[str, object],
    quarantine: Path,
) -> dict[str, object]:
    manifest_path = quarantine / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ByteModeError("the pre-repair copy list is missing or unsafe")
    manifest_raw = manifest_path.read_bytes()
    manifest = _strict_json(manifest_raw)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise ByteModeError("the pre-repair copy list is not valid")
    restored: list[str] = []
    for entry in manifest["files"]:
        if not isinstance(entry, dict):
            raise ByteModeError("the pre-repair copy list has a damaged entry")
        relative = entry.get("relative")
        expected = entry.get("sha256_before")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ByteModeError("the pre-repair copy list has a damaged entry")
        source = quarantine / relative
        if source.is_symlink() or not source.is_file():
            raise ByteModeError(f"the pre-repair copy of {relative} is missing")
        raw = source.read_bytes()
        if _sha256_bytes(raw) != expected:
            raise ByteModeError(f"the pre-repair copy of {relative} no longer matches")
        target = root / relative
        _atomic_write(target, raw)
        restored.append(relative)

    marker_path = _marker_path(root)
    if marker_path.is_file() and not marker_path.is_symlink():
        marker_path.unlink()
        fsync_directory(marker_path.parent)

    updated = dict(manifest)
    updated["rolled_back_at"] = _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    _atomic_write(manifest_path, _canonical(updated))
    return {
        "restored": restored,
        "quarantine": quarantine.relative_to(root).as_posix(),
    }


def ensure(vault_root: Path) -> ByteModeReport:
    """Detect, refuse blocking findings, and apply repairable ones.

    Fast path: a marker for this platform with ``hash_read_mode=binary``
    skips detection. Used from ``_prepare``. Silent when there is nothing
    to do.
    """
    root = Path(vault_root)
    if marker_is_binary_for_this_platform(root):
        return ByteModeReport(state="binary")
    scanned = detect(root)
    if scanned.blocking:
        raise ByteModeBlocked(scanned.blocking[0].record, root)
    if scanned.repairable:
        apply(root, scanned)
        return detect(root)
    return scanned


def status_payload(vault_root: Path) -> dict[str, object]:
    if marker_is_binary_for_this_platform(vault_root):
        scanned = detect(vault_root)
        if scanned.state == "binary" and not scanned.findings and not scanned.blocking:
            return {"state": "binary", "findings": []}
        return scanned.to_dict()
    scanned = detect(vault_root)
    if scanned.state == "binary" and not scanned.findings and not scanned.blocking:
        return {"state": "binary", "findings": []}
    return scanned.to_dict()
