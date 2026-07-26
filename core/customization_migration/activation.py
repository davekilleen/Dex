"""Consent-agnostic live activation and receipt-backed rewind.

These primitives are called only after the Doctor/CLI layer has collected a
real interactive confirmation. The approval and acknowledgement tokens below
bind integrity; they are reproducible hashes and therefore non-secret by
construction (threat-model amendment A1).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from core import portable_contract
from core.customization_migration.capsule import CAPSULE_ROOT
from core.customization_migration.capsule_model import CAPSULE_ID
from core.customization_migration.model import SHA256
from core.customization_migration.planning import (
    PROPOSAL_ID,
    Disposition,
    RegenerationCandidate,
)
from core.customization_migration.staging import (
    STAGING_SUBDIR,
    StagingError,
    _append_event,
    _assessment_from_capsule,
    _read_event_records_beneath,
    _read_regular_beneath,
    _validate_candidate_against_capsule,
    load_staged_candidate,
    read_staging_status,
    validate_staging,
)
from core.customization_migration.state import MigrationEvent, MigrationState
from core.customization_migration.verification import (
    VerificationError,
    VerificationReport,
    validate_persisted_verification_report,
    verify_staging,
)
from core.path_safety import unsafe_existing_parent
from core.transaction.engine import (
    TX_ROOT_RELATIVE,
    PlanEntry,
    PlanRejected,
    Transaction,
    TransactionError,
)
from core.transaction.journal import Journal, JournalCorruptError
from core.transaction.lock import LockBusyError
from core.transaction.snapshot import SnapshotEntry, SnapshotError

_MAX_LIVE_BYTES = 1024 * 1024
_MAX_RECEIPT_BYTES = 1024 * 1024
_SNAPSHOT_RETENTION_NOTE = (
    "The transaction engine keeps only the newest three committed snapshots."
)
_REWIND_NOTE = (
    "Rewind is available only while this snapshot remains retained and every "
    "activated live file still matches the receipt."
)
_TX_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PLAN_ENTRY_KEYS = frozenset(
    {
        "relative",
        "operation",
        "sha256",
        "mode",
        "size",
        "expected_current_sha256",
        "expected_absent",
    }
)
_SNAPSHOT_ENTRY_KEYS = frozenset(
    {"relative", "existed", "mode", "sha256", "size"}
)


class ActivationError(RuntimeError):
    """Activation or rewind refused without claiming a partial result."""


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_relative(value: str, *, name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError(f"{name} must be a canonical relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{name} must be a canonical relative path")
    return value


def _digest(value: str, *, name: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase sha256")
    return value


def _mode(value: int, *, name: str) -> int:
    if type(value) is not int or not 0 <= value <= 0o777:
        raise ValueError(f"{name} must contain only permission bits")
    return value


def _closed(
    value: object,
    *,
    keys: frozenset[str],
    name: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or frozenset(value) != keys:
        raise ActivationError(f"{name} has an invalid closed shape")
    return value


@dataclass(frozen=True)
class ActivationFile:
    target_path: str
    previous_sha256: str | None
    sha256: str
    mode: int
    expected_absent: bool

    def __post_init__(self) -> None:
        _canonical_relative(self.target_path, name="activation target_path")
        if self.previous_sha256 is not None:
            _digest(self.previous_sha256, name="activation previous_sha256")
        _digest(self.sha256, name="activation sha256")
        _mode(self.mode, name="activation mode")
        if type(self.expected_absent) is not bool:
            raise TypeError("activation expected_absent must be boolean")
        if self.expected_absent != (self.previous_sha256 is None):
            raise ValueError(
                "activation expected_absent must exactly match the previous state"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "target_path": self.target_path,
            "previous_sha256": self.previous_sha256,
            "sha256": self.sha256,
            "mode": self.mode,
            "expected_absent": self.expected_absent,
        }


@dataclass(frozen=True)
class ActivationPreview:
    schema_version: int
    capsule_id: str
    proposal_id: str
    verification_report_sha256: str
    candidate_sha256: str
    files: tuple[ActivationFile, ...]
    snapshot_retention_note: str
    rewind_note: str
    approval_token: str

    def __post_init__(self) -> None:
        if self.schema_version != 0:
            raise ValueError("unsupported activation preview schema_version")
        if CAPSULE_ID.fullmatch(self.capsule_id) is None:
            raise ValueError("activation preview capsule_id is not canonical")
        if PROPOSAL_ID.fullmatch(self.proposal_id) is None:
            raise ValueError("activation preview proposal_id is not canonical")
        _digest(
            self.verification_report_sha256,
            name="activation verification_report_sha256",
        )
        _digest(self.candidate_sha256, name="activation candidate_sha256")
        if not isinstance(self.files, tuple) or any(
            type(item) is not ActivationFile for item in self.files
        ):
            raise TypeError("activation preview files must be ActivationFile records")
        if self.files != tuple(sorted(self.files, key=lambda item: item.target_path)):
            raise ValueError("activation preview files must be sorted")
        if len({item.target_path for item in self.files}) != len(self.files):
            raise ValueError("activation preview target paths must be unique")
        if (
            self.snapshot_retention_note != _SNAPSHOT_RETENTION_NOTE
            or self.rewind_note != _REWIND_NOTE
        ):
            raise ValueError("activation preview safety notes are not canonical")
        _digest(self.approval_token, name="activation approval_token")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capsule_id": self.capsule_id,
            "proposal_id": self.proposal_id,
            "verification_report_sha256": self.verification_report_sha256,
            "candidate_sha256": self.candidate_sha256,
            "files": [item.to_dict() for item in self.files],
            "snapshot_retention_note": self.snapshot_retention_note,
            "rewind_note": self.rewind_note,
        }

    def canonical_preview_bytes(self) -> bytes:
        return _canonical_json(self._unsigned_dict())

    def to_dict(self) -> dict[str, object]:
        result = self._unsigned_dict()
        result["approval_token"] = self.approval_token
        return result


@dataclass(frozen=True)
class ActivatedFile:
    path: str
    sha256: str
    byte_size: int
    mode: int

    def __post_init__(self) -> None:
        _canonical_relative(self.path, name="activated path")
        _digest(self.sha256, name="activated sha256")
        if type(self.byte_size) is not int or self.byte_size <= 0:
            raise ValueError("activated byte_size must be positive")
        _mode(self.mode, name="activated mode")

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, raw: object) -> ActivatedFile:
        value = _closed(
            raw,
            keys=frozenset({"path", "sha256", "byte_size", "mode"}),
            name="activated file",
        )
        try:
            return cls(
                value["path"],
                value["sha256"],
                value["byte_size"],
                value["mode"],
            )
        except (TypeError, ValueError) as error:
            raise ActivationError("activated file is invalid") from error


@dataclass(frozen=True)
class ActivationReceipt:
    schema_version: int
    capsule_id: str
    proposal_id: str
    verification_report_sha256: str
    candidate_sha256: str
    files_written: tuple[ActivatedFile, ...]
    transaction_id: str
    snapshot_ref: str
    activated_epoch_seconds: int
    rewind_available: bool

    def __post_init__(self) -> None:
        if self.schema_version != 0:
            raise ValueError("unsupported activation receipt schema_version")
        if CAPSULE_ID.fullmatch(self.capsule_id) is None:
            raise ValueError("activation receipt capsule_id is not canonical")
        if PROPOSAL_ID.fullmatch(self.proposal_id) is None:
            raise ValueError("activation receipt proposal_id is not canonical")
        _digest(
            self.verification_report_sha256,
            name="receipt verification_report_sha256",
        )
        _digest(self.candidate_sha256, name="receipt candidate_sha256")
        if not isinstance(self.files_written, tuple) or not self.files_written or any(
            type(item) is not ActivatedFile for item in self.files_written
        ):
            raise TypeError(
                "activation receipt files_written must be non-empty ActivatedFile records"
            )
        if self.files_written != tuple(
            sorted(self.files_written, key=lambda item: item.path)
        ):
            raise ValueError("activation receipt files_written must be sorted")
        if len({item.path for item in self.files_written}) != len(self.files_written):
            raise ValueError("activation receipt repeats a live path")
        if not isinstance(self.transaction_id, str) or _TX_ID.fullmatch(
            self.transaction_id
        ) is None:
            raise ValueError("activation receipt transaction_id is not canonical")
        expected_snapshot = (
            f"System/.dex/tx/{self.transaction_id}/snapshot"
        )
        if self.snapshot_ref != expected_snapshot:
            raise ValueError(
                "activation receipt snapshot_ref does not match its transaction"
            )
        if (
            type(self.activated_epoch_seconds) is not int
            or self.activated_epoch_seconds < 0
        ):
            raise ValueError("activation time must be a non-negative integer")
        if self.rewind_available is not True:
            raise ValueError(
                "a newly committed activation must honestly mark rewind available"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capsule_id": self.capsule_id,
            "proposal_id": self.proposal_id,
            "verification_report_sha256": self.verification_report_sha256,
            "candidate_sha256": self.candidate_sha256,
            "files_written": [item.to_dict() for item in self.files_written],
            "transaction_id": self.transaction_id,
            "snapshot_ref": self.snapshot_ref,
            "activated_epoch_seconds": self.activated_epoch_seconds,
            "rewind_available": self.rewind_available,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, raw: object) -> ActivationReceipt:
        value = _closed(
            raw,
            keys=frozenset(
                {
                    "schema_version",
                    "capsule_id",
                    "proposal_id",
                    "verification_report_sha256",
                    "candidate_sha256",
                    "files_written",
                    "transaction_id",
                    "snapshot_ref",
                    "activated_epoch_seconds",
                    "rewind_available",
                }
            ),
            name="activation receipt",
        )
        raw_files = value["files_written"]
        if not isinstance(raw_files, list):
            raise ActivationError("activation receipt files_written must be a list")
        try:
            return cls(
                value["schema_version"],
                value["capsule_id"],
                value["proposal_id"],
                value["verification_report_sha256"],
                value["candidate_sha256"],
                tuple(ActivatedFile.from_dict(item) for item in raw_files),
                value["transaction_id"],
                value["snapshot_ref"],
                value["activated_epoch_seconds"],
                value["rewind_available"],
            )
        except (TypeError, ValueError) as error:
            raise ActivationError("activation receipt is invalid") from error


def activation_receipt_from_bytes(raw: bytes) -> ActivationReceipt:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ActivationError("activation receipt is unreadable") from error
    receipt = ActivationReceipt.from_dict(value)
    if receipt.canonical_bytes() != raw:
        raise ActivationError("activation receipt is not canonical")
    return receipt


@dataclass(frozen=True)
class ActivationStatus:
    capsule_id: str
    proposal_id: str | None
    state: MigrationState
    reason: str


@dataclass(frozen=True)
class RewindFile:
    path: str
    existed_before_activation: bool
    restored_sha256: str | None
    byte_size: int | None
    mode: int | None

    def __post_init__(self) -> None:
        _canonical_relative(self.path, name="rewind path")
        if type(self.existed_before_activation) is not bool:
            raise TypeError("rewind existed_before_activation must be boolean")
        if self.existed_before_activation:
            _digest(self.restored_sha256, name="rewind restored_sha256")
            if type(self.byte_size) is not int or self.byte_size < 0:
                raise ValueError("rewind byte_size must be non-negative")
            _mode(self.mode, name="rewind mode")
        elif any(
            value is not None
            for value in (self.restored_sha256, self.byte_size, self.mode)
        ):
            raise ValueError("an absent rewind state must carry null file evidence")

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "existed_before_activation": self.existed_before_activation,
            "restored_sha256": self.restored_sha256,
            "byte_size": self.byte_size,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, raw: object) -> RewindFile:
        value = _closed(
            raw,
            keys=frozenset(
                {
                    "path",
                    "existed_before_activation",
                    "restored_sha256",
                    "byte_size",
                    "mode",
                }
            ),
            name="rewind file",
        )
        try:
            return cls(
                value["path"],
                value["existed_before_activation"],
                value["restored_sha256"],
                value["byte_size"],
                value["mode"],
            )
        except (TypeError, ValueError) as error:
            raise ActivationError("rewind file is invalid") from error


@dataclass(frozen=True)
class RewindPreview:
    schema_version: int
    capsule_id: str
    proposal_id: str
    activation_transaction_id: str
    status: str
    reason: str
    files: tuple[RewindFile, ...]
    acknowledgement_token: str | None


@dataclass(frozen=True)
class RewindReceipt:
    schema_version: int
    capsule_id: str
    proposal_id: str
    activation_transaction_id: str
    rewind_transaction_id: str | None
    status: str
    reason: str
    files_restored: tuple[RewindFile, ...]
    rewound_epoch_seconds: int | None

    def __post_init__(self) -> None:
        if self.schema_version != 0:
            raise ValueError("unsupported rewind receipt schema_version")
        if CAPSULE_ID.fullmatch(self.capsule_id) is None:
            raise ValueError("rewind receipt capsule_id is not canonical")
        if PROPOSAL_ID.fullmatch(self.proposal_id) is None:
            raise ValueError("rewind receipt proposal_id is not canonical")
        if (
            not isinstance(self.activation_transaction_id, str)
            or _TX_ID.fullmatch(self.activation_transaction_id) is None
        ):
            raise ValueError(
                "rewind receipt activation_transaction_id is not canonical"
            )
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("rewind receipt reason must be non-empty")
        if not isinstance(self.files_restored, tuple) or any(
            type(item) is not RewindFile for item in self.files_restored
        ):
            raise TypeError(
                "rewind receipt files_restored must be RewindFile records"
            )
        if self.files_restored != tuple(
            sorted(self.files_restored, key=lambda item: item.path)
        ):
            raise ValueError("rewind receipt files_restored must be sorted")
        if len({item.path for item in self.files_restored}) != len(
            self.files_restored
        ):
            raise ValueError("rewind receipt repeats a live path")
        if self.status == "OK":
            if (
                not isinstance(self.rewind_transaction_id, str)
                or _TX_ID.fullmatch(self.rewind_transaction_id) is None
                or not self.files_restored
                or type(self.rewound_epoch_seconds) is not int
                or self.rewound_epoch_seconds < 0
            ):
                raise ValueError("successful rewind receipt evidence is incomplete")
        elif self.status == "UNKNOWN":
            if (
                self.rewind_transaction_id is not None
                or self.files_restored
                or self.rewound_epoch_seconds is not None
            ):
                raise ValueError("unknown rewind receipt must not claim a restore")
        else:
            raise ValueError("rewind receipt status must be OK or UNKNOWN")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capsule_id": self.capsule_id,
            "proposal_id": self.proposal_id,
            "activation_transaction_id": self.activation_transaction_id,
            "rewind_transaction_id": self.rewind_transaction_id,
            "status": self.status,
            "reason": self.reason,
            "files_restored": [item.to_dict() for item in self.files_restored],
            "rewound_epoch_seconds": self.rewound_epoch_seconds,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, raw: object) -> RewindReceipt:
        value = _closed(
            raw,
            keys=frozenset(
                {
                    "schema_version",
                    "capsule_id",
                    "proposal_id",
                    "activation_transaction_id",
                    "rewind_transaction_id",
                    "status",
                    "reason",
                    "files_restored",
                    "rewound_epoch_seconds",
                }
            ),
            name="rewind receipt",
        )
        raw_files = value["files_restored"]
        if not isinstance(raw_files, list):
            raise ActivationError("rewind receipt files_restored must be a list")
        try:
            return cls(
                value["schema_version"],
                value["capsule_id"],
                value["proposal_id"],
                value["activation_transaction_id"],
                value["rewind_transaction_id"],
                value["status"],
                value["reason"],
                tuple(RewindFile.from_dict(item) for item in raw_files),
                value["rewound_epoch_seconds"],
            )
        except (TypeError, ValueError) as error:
            raise ActivationError("rewind receipt is invalid") from error


def rewind_receipt_from_bytes(raw: bytes) -> RewindReceipt:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ActivationError("rewind receipt is unreadable") from error
    receipt = RewindReceipt.from_dict(value)
    if receipt.canonical_bytes() != raw:
        raise ActivationError("rewind receipt is not canonical")
    return receipt


@dataclass(frozen=True)
class _VerifiedEvidence:
    candidate: RegenerationCandidate
    report: VerificationReport
    report_sha256: str
    journal_relative: str
    journal_bytes: bytes


def _activation_receipt_relative(capsule_id: str) -> str:
    return f"{CAPSULE_ROOT}/{capsule_id}/receipts/activation.json"


def _rewind_receipt_relative(capsule_id: str) -> str:
    return f"{CAPSULE_ROOT}/{capsule_id}/receipts/rewind.json"


def _proposal_journal_relative(capsule_id: str, proposal_id: str) -> str:
    return (
        f"{CAPSULE_ROOT}/{capsule_id}/"
        + STAGING_SUBDIR.format(proposal_id=proposal_id)
        + "/journal.jsonl"
    )


def _require_report_ok(report: VerificationReport) -> None:
    if report.verdict != "OK":
        raise ActivationError(
            f"activation verification verdict is not OK: {report.verdict}"
        )
    if not report.staged_paths_private or not report.writes_confined_to_capsule:
        raise ActivationError(
            "activation verification did not prove private, capsule-confined staging"
        )


def _load_verified_evidence(
    root: Path,
    capsule_id: str,
    proposal_id: str,
) -> _VerifiedEvidence:
    try:
        candidate, _receipt, staging = load_staged_candidate(
            root,
            capsule_id,
            proposal_id,
        )
        _validate_candidate_against_capsule(root, capsule_id, candidate)
    except (OSError, StagingError) as error:
        raise ActivationError(
            "activation staging evidence is missing, invalid, or drifted"
        ) from error
    validation = validate_staging(root, capsule_id, proposal_id)
    if validation.status != "OK":
        raise ActivationError(
            "activation staging integrity is not OK: "
            + ", ".join(validation.mismatches)
        )
    journal_relative = _proposal_journal_relative(capsule_id, proposal_id)
    try:
        journal_bytes = _read_regular_beneath(
            root,
            journal_relative,
            _MAX_RECEIPT_BYTES,
        )
        records = _read_event_records_beneath(root, journal_relative)
    except (OSError, StagingError) as error:
        raise ActivationError("activation staging journal is unreadable") from error
    if (
        len(records) != 3
        or tuple(record["event"] for record in records[:2])
        != (
            MigrationEvent.REGENERATION_PROPOSED.value,
            MigrationEvent.REGENERATION_STAGED.value,
        )
        or records[2]["event"]
        not in {
            MigrationEvent.VERIFICATION_PASSED.value,
            MigrationEvent.VERIFICATION_BLOCKED.value,
        }
    ):
        raise ActivationError(
            "activation staging journal is not at a verified disposition"
        )
    binding = records[2]
    expected_report_relative = (
        f"{CAPSULE_ROOT}/{capsule_id}/verification/{proposal_id}.json"
    )
    if (
        binding.get("report_path") != expected_report_relative
        or binding.get("candidate_sha256") != candidate.candidate_sha256
    ):
        raise ActivationError("activation verification report binding drifted")
    try:
        report_raw = _read_regular_beneath(
            root,
            expected_report_relative,
            _MAX_RECEIPT_BYTES,
        )
        report_sha256 = _sha256(report_raw)
        if report_sha256 != binding.get("report_sha256"):
            raise ActivationError("activation verification report digest drifted")
        report = validate_persisted_verification_report(
            report_raw,
            candidate,
            binding["event"],
        )
    except (OSError, KeyError, TypeError, VerificationError) as error:
        if isinstance(error, ActivationError):
            raise
        raise ActivationError(
            "activation persisted verification report is invalid"
        ) from error
    _require_report_ok(report)
    fresh = verify_staging(root, capsule_id, proposal_id)
    if fresh.canonical_bytes() != report_raw:
        raise ActivationError("activation verification report drifted on re-derivation")

    assessment, _assessment_digest = _assessment_from_capsule(root, capsule_id)
    accounted_ids = {item.customization_id for item in candidate.dispositions}
    expected_ids = {item.customization_id for item in assessment.records}
    if accounted_ids != expected_ids:
        raise ActivationError("activation dispositions do not completely account for evidence")
    if any(
        item.disposition is Disposition.BLOCKED
        for item in candidate.dispositions
    ):
        raise ActivationError("activation has a blocked disposition")
    for item in candidate.files:
        relative = (
            staging.relative_to(root).as_posix()
            + f"/files/{item.sha256}"
        )
        try:
            raw = _read_regular_beneath(root, relative, len(item.content))
        except (OSError, StagingError) as error:
            raise ActivationError(
                f"activation staged bytes are unreadable: {item.target_path}"
            ) from error
        if raw != item.content or _sha256(raw) != item.sha256:
            raise ActivationError(
                f"activation staged bytes drifted: {item.target_path}"
            )
    return _VerifiedEvidence(
        candidate,
        report,
        report_sha256,
        journal_relative,
        journal_bytes,
    )


def _read_live_state(
    root: Path,
    relative: str,
) -> tuple[bool, str | None]:
    unsafe_parent = unsafe_existing_parent(root, relative)
    if unsafe_parent is not None:
        raise ActivationError(f"activation target is unsafe: {relative} [{unsafe_parent}]")
    target = root / relative
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return False, None
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ActivationError(
            f"activation target is not a regular non-symlink file: {relative}"
        )
    try:
        raw = _read_regular_beneath(root, relative, _MAX_LIVE_BYTES)
    except (OSError, StagingError) as error:
        raise ActivationError(
            f"activation target is not safely readable: {relative}"
        ) from error
    return True, _sha256(raw)


def preview_activation(
    vault_root: Path,
    capsule_id: str,
    proposal_id: str,
) -> ActivationPreview:
    """Build a deterministic live plan without changing any vault path."""
    root = Path(vault_root).resolve()
    receipt_path = root / _activation_receipt_relative(capsule_id)
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ActivationError(f"capsule is already activated: {capsule_id}")
    evidence = _load_verified_evidence(root, capsule_id, proposal_id)
    files: list[ActivationFile] = []
    for item in evidence.candidate.files:
        exists, previous_sha256 = _read_live_state(root, item.target_path)
        verdict = portable_contract.update_write_verdict(
            item.target_path,
            exists=exists,
            operation="customization-migration",
        )
        if not verdict.allowed:
            raise ActivationError(
                "activation target is no longer contract-authorized: "
                f"{item.target_path} [{verdict.action}]"
            )
        files.append(
            ActivationFile(
                item.target_path,
                previous_sha256,
                item.sha256,
                0o644,
                not exists,
            )
        )
    unsigned = ActivationPreview(
        0,
        capsule_id,
        proposal_id,
        evidence.report_sha256,
        evidence.candidate.candidate_sha256,
        tuple(sorted(files, key=lambda item: item.target_path)),
        _SNAPSHOT_RETENTION_NOTE,
        _REWIND_NOTE,
        "0" * 64,
    )
    return ActivationPreview(
        0,
        capsule_id,
        proposal_id,
        evidence.report_sha256,
        evidence.candidate.candidate_sha256,
        unsigned.files,
        _SNAPSHOT_RETENTION_NOTE,
        _REWIND_NOTE,
        _sha256(unsigned.canonical_preview_bytes()),
    )


def _transaction_id() -> str:
    return (
        time.strftime("%Y%m%dT%H%M%S")
        + f"{time.time_ns():020d}-"
        + uuid.uuid4().hex[:8]
    )


def _activation_stop_seam(name: str) -> None:
    if os.environ.get("DEX_TX_TEST_STOP_AFTER") == name:
        os._exit(137)


def _matching_preview_files(
    preview: ActivationPreview,
    candidate: RegenerationCandidate,
) -> dict[str, ActivationFile]:
    by_path = {item.target_path: item for item in preview.files}
    if set(by_path) != {item.target_path for item in candidate.files}:
        raise ActivationError("activation preview file set drifted from staging")
    for item in candidate.files:
        planned = by_path[item.target_path]
        if planned.sha256 != item.sha256 or planned.mode != 0o644:
            raise ActivationError(
                f"activation preview bytes or mode drifted: {item.target_path}"
            )
    return by_path


def activate(
    vault_root: Path,
    preview: ActivationPreview,
    approval_token: str,
    *,
    clock: Callable[[], int | float] = time.time,
) -> ActivationReceipt:
    """Commit every live file and its activation evidence in one transaction."""
    if type(preview) is not ActivationPreview:
        raise TypeError("preview must be ActivationPreview")
    expected_token = _sha256(preview.canonical_preview_bytes())
    if (
        not isinstance(approval_token, str)
        or not hmac.compare_digest(approval_token, preview.approval_token)
        or not hmac.compare_digest(approval_token, expected_token)
    ):
        raise ActivationError("activation approval token does not match the preview")
    root = Path(vault_root).resolve()
    evidence = _load_verified_evidence(
        root,
        preview.capsule_id,
        preview.proposal_id,
    )
    if (
        evidence.candidate.candidate_sha256 != preview.candidate_sha256
        or evidence.report_sha256 != preview.verification_report_sha256
    ):
        raise ActivationError("activation staging or verification evidence drifted")
    preview_files = _matching_preview_files(preview, evidence.candidate)
    activated_at = int(clock())
    if activated_at < 0:
        raise ActivationError("activation clock returned a negative time")
    tx_id = _transaction_id()
    receipt = ActivationReceipt(
        0,
        preview.capsule_id,
        preview.proposal_id,
        preview.verification_report_sha256,
        preview.candidate_sha256,
        tuple(
            ActivatedFile(item.target_path, item.sha256, len(item.content), 0o644)
            for item in evidence.candidate.files
        ),
        tx_id,
        f"System/.dex/tx/{tx_id}/snapshot",
        activated_at,
        True,
    )
    receipt_relative = _activation_receipt_relative(preview.capsule_id)
    plan: list[PlanEntry] = []
    for item in evidence.candidate.files:
        planned = preview_files[item.target_path]
        verdict = portable_contract.update_write_verdict(
            item.target_path,
            exists=(root / item.target_path).exists(),
            operation="customization-migration",
        )
        if not verdict.allowed:
            raise ActivationError(
                "activation target is no longer contract-authorized: "
                f"{item.target_path} [{verdict.action}]"
            )
        plan.append(
            PlanEntry(
                item.target_path,
                item.content,
                mode=planned.mode,
                expected_current_sha256=planned.previous_sha256,
                expected_absent=planned.expected_absent,
            )
        )
    plan.extend(
        (
            PlanEntry(
                receipt_relative,
                receipt.canonical_bytes(),
                mode=0o600,
                expected_absent=True,
            ),
            PlanEntry(
                evidence.journal_relative,
                evidence.journal_bytes,
                mode=0o600,
                expected_current_sha256=_sha256(evidence.journal_bytes),
            ),
        )
    )
    journal_path = root / evidence.journal_relative

    def finalize_activation() -> None:
        refreshed = _load_verified_evidence(
            root,
            preview.capsule_id,
            preview.proposal_id,
        )
        if (
            refreshed.candidate.candidate_sha256 != preview.candidate_sha256
            or refreshed.report_sha256 != preview.verification_report_sha256
        ):
            raise ActivationError(
                "activation evidence drifted during the live transaction"
            )
        _append_event(journal_path, MigrationEvent.ACTIVATION_PREVIEWED)
        _activation_stop_seam("activation-after-previewed")
        _append_event(journal_path, MigrationEvent.ACTIVATED)
        _activation_stop_seam("activation-mid-finalize")

    try:
        transaction = Transaction._begin_with_id(
            root,
            plan,
            allow_empty=False,
            operation="customization-migration",
            tx_id=tx_id,
        )
        transaction.run(before_commit=finalize_activation)
    except ActivationError:
        raise
    except (
        LockBusyError,
        OSError,
        PlanRejected,
        SnapshotError,
        StagingError,
        TransactionError,
        VerificationError,
    ) as error:
        raise ActivationError(f"activation refused safely: {error}") from error
    return receipt


def _load_activation_receipt(root: Path, capsule_id: str) -> ActivationReceipt:
    relative = _activation_receipt_relative(capsule_id)
    try:
        raw = _read_regular_beneath(root, relative, _MAX_RECEIPT_BYTES)
    except (OSError, StagingError) as error:
        raise ActivationError("activation receipt is missing or unsafe") from error
    receipt = activation_receipt_from_bytes(raw)
    if receipt.capsule_id != capsule_id:
        raise ActivationError("activation receipt capsule identity does not match")
    return receipt


def _load_rewind_receipt(root: Path, capsule_id: str) -> RewindReceipt:
    relative = _rewind_receipt_relative(capsule_id)
    try:
        raw = _read_regular_beneath(root, relative, _MAX_RECEIPT_BYTES)
    except (OSError, StagingError) as error:
        raise ActivationError("rewind receipt is missing or unsafe") from error
    receipt = rewind_receipt_from_bytes(raw)
    if receipt.capsule_id != capsule_id:
        raise ActivationError("rewind receipt capsule identity does not match")
    return receipt


def read_activation_status(
    vault_root: Path,
    capsule_id: str,
) -> ActivationStatus:
    """Project activation state; corrupt receipt/journal evidence fails closed."""
    if not isinstance(capsule_id, str) or CAPSULE_ID.fullmatch(capsule_id) is None:
        raise ActivationError("capsule_id is not canonical")
    root = Path(vault_root).resolve()
    receipt_target = root / _activation_receipt_relative(capsule_id)
    if receipt_target.is_symlink():
        return ActivationStatus(
            capsule_id,
            None,
            MigrationState.RECOVERY_REQUIRED,
            "activation-receipt-unsafe",
        )
    try:
        staging_status = read_staging_status(root, capsule_id)
    except (OSError, StagingError):
        return ActivationStatus(
            capsule_id,
            None,
            MigrationState.RECOVERY_REQUIRED,
            "staging-status-unreadable",
        )
    if receipt_target.exists():
        try:
            receipt = _load_activation_receipt(root, capsule_id)
        except ActivationError:
            return ActivationStatus(
                capsule_id,
                None,
                MigrationState.RECOVERY_REQUIRED,
                "activation-receipt-invalid",
            )
        state = next(
            (
                item.state
                for item in staging_status.proposals
                if item.proposal_id == receipt.proposal_id
            ),
            MigrationState.RECOVERY_REQUIRED,
        )
        if state not in {MigrationState.ACTIVATED, MigrationState.REWOUND}:
            state = MigrationState.RECOVERY_REQUIRED
        tx_root = (root / receipt.snapshot_ref).parent
        if tx_root.is_symlink():
            state = MigrationState.RECOVERY_REQUIRED
        elif tx_root.is_dir():
            try:
                _verify_activation_commit(root, receipt)
            except ActivationError:
                state = MigrationState.RECOVERY_REQUIRED
        if state is MigrationState.REWOUND:
            try:
                rewind_receipt = _load_rewind_receipt(root, capsule_id)
                if (
                    rewind_receipt.status != "OK"
                    or rewind_receipt.proposal_id != receipt.proposal_id
                    or rewind_receipt.activation_transaction_id
                    != receipt.transaction_id
                ):
                    raise ActivationError(
                        "rewind receipt does not match the activation"
                    )
                if rewind_receipt.rewind_transaction_id is None:
                    raise ActivationError(
                        "rewind receipt does not name a transaction"
                    )
                rewind_tx_root = (
                    root
                    / TX_ROOT_RELATIVE
                    / rewind_receipt.rewind_transaction_id
                )
                if rewind_tx_root.is_symlink():
                    raise ActivationError(
                        "rewind transaction directory is unsafe"
                    )
                if rewind_tx_root.is_dir():
                    _verify_rewind_commit(root, receipt, rewind_receipt)
            except ActivationError:
                state = MigrationState.RECOVERY_REQUIRED
        return ActivationStatus(
            capsule_id,
            receipt.proposal_id,
            state,
            state.value,
        )
    if len(staging_status.proposals) == 1:
        proposal = staging_status.proposals[0]
        return ActivationStatus(
            capsule_id,
            proposal.proposal_id,
            proposal.state,
            proposal.state.value,
        )
    return ActivationStatus(
        capsule_id,
        None,
        MigrationState.UNKNOWN,
        "activation-not-found",
    )


def _validated_activation_receipt(
    receipt: ActivationReceipt | object,
) -> ActivationReceipt:
    if isinstance(receipt, ActivationReceipt):
        return ActivationReceipt.from_dict(receipt.to_dict())
    try:
        return ActivationReceipt.from_dict(receipt)
    except (ActivationError, TypeError, ValueError) as error:
        raise ActivationError("activation receipt is invalid") from error


def _current_live_matches(
    root: Path,
    receipt: ActivationReceipt,
) -> tuple[str, ...]:
    drifted: list[str] = []
    for item in receipt.files_written:
        try:
            exists, digest = _read_live_state(root, item.path)
            target = root / item.path
            metadata = target.lstat()
            if (
                not exists
                or digest != item.sha256
                or not stat.S_ISREG(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or metadata.st_size != item.byte_size
                or stat.S_IMODE(metadata.st_mode) != item.mode
            ):
                drifted.append(item.path)
        except (ActivationError, OSError):
            drifted.append(item.path)
    return tuple(sorted(drifted))


def _verify_activation_commit(
    root: Path,
    receipt: ActivationReceipt,
) -> dict[str, dict[str, object]]:
    journal_path = (root / receipt.snapshot_ref).parent / "journal.jsonl"
    try:
        entries = Journal(journal_path).read()
    except (JournalCorruptError, OSError) as error:
        raise ActivationError("activation transaction journal is damaged") from error
    begins = [entry for entry in entries if entry.event == "BEGIN"]
    events = [entry.event for entry in entries]
    if (
        len(begins) != 1
        or begins[0].payload.get("tx_id") != receipt.transaction_id
        or begins[0].payload.get("operation") != "customization-migration"
        or events.count("COMMITTED") != 1
        or "ROLLED-BACK" in events
    ):
        raise ActivationError(
            "activation receipt does not point to one committed transaction"
        )
    try:
        candidate, _staging_receipt, _staging = load_staged_candidate(
            root,
            receipt.capsule_id,
            receipt.proposal_id,
        )
    except (OSError, StagingError) as error:
        raise ActivationError(
            "activation transaction no longer binds valid staged evidence"
        ) from error
    candidate_files = {
        item.target_path: item
        for item in candidate.files
    }
    receipt_files = {item.path: item for item in receipt.files_written}
    if (
        candidate.candidate_sha256 != receipt.candidate_sha256
        or set(candidate_files) != set(receipt_files)
    ):
        raise ActivationError(
            "activation receipt does not bind the complete staged candidate"
        )
    for relative, candidate_file in candidate_files.items():
        receipt_file = receipt_files[relative]
        if (
            receipt_file.sha256 != candidate_file.sha256
            or receipt_file.byte_size != len(candidate_file.content)
            or receipt_file.mode != 0o644
        ):
            raise ActivationError(
                f"activation receipt file evidence drifted: {relative}"
            )
    report_relative = (
        f"{CAPSULE_ROOT}/{receipt.capsule_id}/verification/"
        f"{receipt.proposal_id}.json"
    )
    try:
        report_raw = _read_regular_beneath(
            root,
            report_relative,
            _MAX_RECEIPT_BYTES,
        )
        report = validate_persisted_verification_report(
            report_raw,
            candidate,
            MigrationEvent.VERIFICATION_PASSED.value,
        )
    except (OSError, StagingError, VerificationError) as error:
        raise ActivationError(
            "activation transaction verification evidence is invalid"
        ) from error
    if _sha256(report_raw) != receipt.verification_report_sha256:
        raise ActivationError(
            "activation receipt verification report digest drifted"
        )
    _require_report_ok(report)

    raw_plan = begins[0].payload.get("plan")
    if not isinstance(raw_plan, list):
        raise ActivationError("activation transaction plan is invalid")
    plan_by_path: dict[str, dict[str, object]] = {}
    for index, raw in enumerate(raw_plan):
        plan_entry = _closed(
            raw,
            keys=_PLAN_ENTRY_KEYS,
            name=f"activation transaction plan entry {index}",
        )
        try:
            relative = _canonical_relative(
                plan_entry["relative"],
                name="activation transaction plan path",
            )
        except (TypeError, ValueError) as error:
            raise ActivationError(
                "activation transaction plan path is invalid"
            ) from error
        if relative in plan_by_path:
            raise ActivationError("activation transaction plan repeats a path")
        plan_by_path[relative] = plan_entry
    receipt_relative = _activation_receipt_relative(receipt.capsule_id)
    journal_relative = _proposal_journal_relative(
        receipt.capsule_id,
        receipt.proposal_id,
    )
    expected_paths = set(receipt_files) | {receipt_relative, journal_relative}
    if set(plan_by_path) != expected_paths:
        raise ActivationError(
            "activation transaction plan does not exactly match its receipt"
        )
    for relative, receipt_file in receipt_files.items():
        plan_entry = plan_by_path[relative]
        expected_current = plan_entry["expected_current_sha256"]
        expected_absent = plan_entry["expected_absent"]
        if (
            plan_entry["operation"] != "write"
            or plan_entry["sha256"] != receipt_file.sha256
            or plan_entry["size"] != receipt_file.byte_size
            or plan_entry["mode"] != receipt_file.mode
            or type(expected_absent) is not bool
            or expected_absent == (expected_current is not None)
            or (
                expected_current is not None
                and (
                    not isinstance(expected_current, str)
                    or SHA256.fullmatch(expected_current) is None
                )
            )
        ):
            raise ActivationError(
                f"activation transaction plan evidence drifted: {relative}"
            )
    receipt_plan = plan_by_path[receipt_relative]
    if (
        receipt_plan["operation"] != "write"
        or receipt_plan["sha256"] != _sha256(receipt.canonical_bytes())
        or receipt_plan["size"] != len(receipt.canonical_bytes())
        or receipt_plan["mode"] != 0o600
        or receipt_plan["expected_current_sha256"] is not None
        or receipt_plan["expected_absent"] is not True
    ):
        raise ActivationError("activation receipt is not bound to its transaction plan")
    journal_plan = plan_by_path[journal_relative]
    if (
        journal_plan["operation"] != "write"
        or journal_plan["mode"] != 0o600
        or journal_plan["expected_absent"] is not False
        or journal_plan["expected_current_sha256"] != journal_plan["sha256"]
        or not isinstance(journal_plan["sha256"], str)
        or SHA256.fullmatch(journal_plan["sha256"]) is None
        or type(journal_plan["size"]) is not int
        or journal_plan["size"] < 0
    ):
        raise ActivationError("activation journal is not bound to its transaction plan")
    return plan_by_path


def _verify_rewind_commit(
    root: Path,
    activation_receipt: ActivationReceipt,
    rewind_receipt: RewindReceipt,
) -> None:
    if rewind_receipt.rewind_transaction_id is None:
        raise ActivationError("rewind receipt does not name a transaction")
    journal_path = (
        root
        / TX_ROOT_RELATIVE
        / rewind_receipt.rewind_transaction_id
        / "journal.jsonl"
    )
    try:
        entries = Journal(journal_path).read()
    except (JournalCorruptError, OSError) as error:
        raise ActivationError("rewind transaction journal is damaged") from error
    begins = [entry for entry in entries if entry.event == "BEGIN"]
    events = [entry.event for entry in entries]
    if (
        len(begins) != 1
        or begins[0].payload.get("tx_id")
        != rewind_receipt.rewind_transaction_id
        or begins[0].payload.get("operation") != "customization-migration"
        or events.count("COMMITTED") != 1
        or "ROLLED-BACK" in events
    ):
        raise ActivationError(
            "rewind receipt does not point to one committed transaction"
        )
    restored_by_path = {
        item.path: item for item in rewind_receipt.files_restored
    }
    activated_by_path = {
        item.path: item for item in activation_receipt.files_written
    }
    if set(restored_by_path) != set(activated_by_path):
        raise ActivationError(
            "rewind receipt does not cover the complete activation"
        )
    raw_plan = begins[0].payload.get("plan")
    if not isinstance(raw_plan, list):
        raise ActivationError("rewind transaction plan is invalid")
    plan_by_path: dict[str, dict[str, object]] = {}
    for index, raw in enumerate(raw_plan):
        plan_entry = _closed(
            raw,
            keys=_PLAN_ENTRY_KEYS,
            name=f"rewind transaction plan entry {index}",
        )
        try:
            relative = _canonical_relative(
                plan_entry["relative"],
                name="rewind transaction plan path",
            )
        except (TypeError, ValueError) as error:
            raise ActivationError(
                "rewind transaction plan path is invalid"
            ) from error
        if relative in plan_by_path:
            raise ActivationError("rewind transaction plan repeats a path")
        plan_by_path[relative] = plan_entry
    receipt_relative = _rewind_receipt_relative(
        activation_receipt.capsule_id
    )
    journal_relative = _proposal_journal_relative(
        activation_receipt.capsule_id,
        activation_receipt.proposal_id,
    )
    expected_paths = set(restored_by_path) | {
        receipt_relative,
        journal_relative,
    }
    if set(plan_by_path) != expected_paths:
        raise ActivationError(
            "rewind transaction plan does not exactly match its receipt"
        )
    for relative, restored in restored_by_path.items():
        activated = activated_by_path[relative]
        plan_entry = plan_by_path[relative]
        if restored.existed_before_activation:
            valid = (
                plan_entry["operation"] == "write"
                and plan_entry["sha256"] == restored.restored_sha256
                and plan_entry["size"] == restored.byte_size
                and plan_entry["mode"] == restored.mode
            )
        else:
            valid = (
                plan_entry["operation"] == "delete"
                and plan_entry["sha256"] is None
                and plan_entry["size"] is None
                and plan_entry["mode"] == activated.mode
            )
        if (
            not valid
            or plan_entry["expected_current_sha256"] != activated.sha256
            or plan_entry["expected_absent"] is not False
        ):
            raise ActivationError(
                f"rewind transaction plan evidence drifted: {relative}"
            )
    receipt_plan = plan_by_path[receipt_relative]
    if (
        receipt_plan["operation"] != "write"
        or receipt_plan["sha256"] != _sha256(rewind_receipt.canonical_bytes())
        or receipt_plan["size"] != len(rewind_receipt.canonical_bytes())
        or receipt_plan["mode"] != 0o600
        or receipt_plan["expected_current_sha256"] is not None
        or receipt_plan["expected_absent"] is not True
    ):
        raise ActivationError("rewind receipt is not bound to its transaction plan")
    journal_plan = plan_by_path[journal_relative]
    if (
        journal_plan["operation"] != "write"
        or journal_plan["mode"] != 0o600
        or journal_plan["expected_absent"] is not False
        or journal_plan["expected_current_sha256"] != journal_plan["sha256"]
        or not isinstance(journal_plan["sha256"], str)
        or SHA256.fullmatch(journal_plan["sha256"]) is None
        or type(journal_plan["size"]) is not int
        or journal_plan["size"] < 0
    ):
        raise ActivationError("rewind journal is not bound to its transaction plan")


def _read_snapshot_manifest(
    root: Path,
    receipt: ActivationReceipt,
) -> tuple[SnapshotEntry, ...]:
    relative = f"{receipt.snapshot_ref}/manifest.json"
    try:
        raw = _read_regular_beneath(root, relative, _MAX_RECEIPT_BYTES)
        payload = json.loads(raw.decode("utf-8"))
    except (
        OSError,
        StagingError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise ActivationError("activation snapshot manifest is unreadable") from error
    if (
        not isinstance(payload, dict)
        or frozenset(payload) != frozenset({"schema_version", "entries"})
        or payload["schema_version"] != 1
        or not isinstance(payload["entries"], list)
    ):
        raise ActivationError("activation snapshot manifest has an invalid shape")
    manifest: list[SnapshotEntry] = []
    for index, raw_entry in enumerate(payload["entries"]):
        entry = _closed(
            raw_entry,
            keys=_SNAPSHOT_ENTRY_KEYS,
            name=f"activation snapshot entry {index}",
        )
        try:
            manifest.append(
                SnapshotEntry(
                    _canonical_relative(
                        entry["relative"],
                        name="activation snapshot path",
                    ),
                    entry["existed"],
                    entry["mode"],
                    entry["sha256"],
                    entry["size"],
                )
            )
        except (TypeError, ValueError) as error:
            raise ActivationError("activation snapshot entry is invalid") from error
    return tuple(manifest)


def _snapshot_rewind_files(
    root: Path,
    receipt: ActivationReceipt,
) -> tuple[tuple[RewindFile, ...], dict[str, bytes | None]]:
    plan_by_path = _verify_activation_commit(root, receipt)
    manifest = _read_snapshot_manifest(root, receipt)
    by_path: dict[str, tuple[int, SnapshotEntry]] = {}
    for index, entry in enumerate(manifest):
        try:
            relative = _canonical_relative(
                entry.relative,
                name="activation snapshot path",
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise ActivationError("activation snapshot path is invalid") from error
        if relative in by_path:
            raise ActivationError("activation snapshot repeats a path")
        by_path[relative] = (index, entry)
    if set(by_path) != set(plan_by_path):
        raise ActivationError(
            "activation snapshot does not exactly match the committed plan"
        )
    for relative, plan_entry in plan_by_path.items():
        _index, entry = by_path[relative]
        expected_current = plan_entry["expected_current_sha256"]
        if plan_entry["expected_absent"] is True:
            if entry.existed is not False or any(
                value is not None for value in (entry.mode, entry.sha256, entry.size)
            ):
                raise ActivationError(
                    f"activation snapshot absence evidence drifted: {relative}"
                )
        elif expected_current is not None:
            if entry.existed is not True or entry.sha256 != expected_current:
                raise ActivationError(
                    f"activation snapshot current-byte evidence drifted: {relative}"
                )
        else:
            raise ActivationError(
                f"activation snapshot plan lacks a state precondition: {relative}"
            )
    files: list[RewindFile] = []
    contents: dict[str, bytes | None] = {}
    for receipt_file in receipt.files_written:
        index, entry = by_path[receipt_file.path]
        if type(entry.existed) is not bool:
            raise ActivationError(
                f"activation snapshot state is invalid: {receipt_file.path}"
            )
        if entry.existed:
            if (
                type(entry.mode) is not int
                or not 0 <= entry.mode <= 0o777
                or not isinstance(entry.sha256, str)
                or SHA256.fullmatch(entry.sha256) is None
                or type(entry.size) is not int
                or not 0 <= entry.size <= _MAX_LIVE_BYTES
            ):
                raise ActivationError(
                    f"activation snapshot evidence is invalid: {receipt_file.path}"
                )
            try:
                raw = _read_regular_beneath(
                    root,
                    f"{receipt.snapshot_ref}/{index:06d}.bin",
                    entry.size,
                )
            except (OSError, StagingError) as error:
                raise ActivationError(
                    f"activation snapshot blob is unreadable: {receipt_file.path}"
                ) from error
            if len(raw) != entry.size or _sha256(raw) != entry.sha256:
                raise ActivationError(
                    f"activation snapshot blob is damaged: {receipt_file.path}"
                )
            files.append(
                RewindFile(
                    receipt_file.path,
                    True,
                    entry.sha256,
                    entry.size,
                    entry.mode,
                )
            )
            contents[receipt_file.path] = raw
        else:
            if any(
                value is not None
                for value in (entry.mode, entry.sha256, entry.size)
            ):
                raise ActivationError(
                    f"activation absent snapshot is invalid: {receipt_file.path}"
                )
            files.append(
                RewindFile(receipt_file.path, False, None, None, None)
            )
            contents[receipt_file.path] = None
    return tuple(sorted(files, key=lambda item: item.path)), contents


def _rewind_acknowledgement_token(receipt: ActivationReceipt) -> str:
    payload = {
        "rewind": receipt.transaction_id,
        "activation_receipt_sha256": _sha256(receipt.canonical_bytes()),
        "files": [item.path for item in receipt.files_written],
    }
    return _sha256(_canonical_json(payload))


def _unknown_rewind_preview(
    receipt: ActivationReceipt,
    reason: str,
) -> RewindPreview:
    return RewindPreview(
        0,
        receipt.capsule_id,
        receipt.proposal_id,
        receipt.transaction_id,
        "UNKNOWN",
        reason,
        (),
        None,
    )


def preview_rewind(
    vault_root: Path,
    activation_receipt: ActivationReceipt | object,
) -> RewindPreview:
    """Report rewindability without mutating the vault."""
    receipt = _validated_activation_receipt(activation_receipt)
    root = Path(vault_root).resolve()
    status = read_activation_status(root, receipt.capsule_id)
    if status.state is MigrationState.REWOUND:
        return _unknown_rewind_preview(receipt, "already-rewound")
    if status.state is not MigrationState.ACTIVATED:
        return _unknown_rewind_preview(receipt, "activation-not-active")
    persisted = _load_activation_receipt(root, receipt.capsule_id)
    if persisted != receipt:
        return _unknown_rewind_preview(receipt, "activation-receipt-drift")
    drifted = _current_live_matches(root, receipt)
    if drifted:
        return _unknown_rewind_preview(receipt, "live-drift")
    snapshot_root = root / receipt.snapshot_ref
    if snapshot_root.is_symlink() or not snapshot_root.is_dir():
        return _unknown_rewind_preview(receipt, "snapshot-pruned")
    try:
        _verify_activation_commit(root, receipt)
        files, _contents = _snapshot_rewind_files(root, receipt)
    except ActivationError:
        return _unknown_rewind_preview(receipt, "snapshot-damaged")
    return RewindPreview(
        0,
        receipt.capsule_id,
        receipt.proposal_id,
        receipt.transaction_id,
        "OK",
        "ready",
        files,
        _rewind_acknowledgement_token(receipt),
    )


def _unknown_rewind_receipt(
    receipt: ActivationReceipt,
    reason: str,
) -> RewindReceipt:
    return RewindReceipt(
        0,
        receipt.capsule_id,
        receipt.proposal_id,
        receipt.transaction_id,
        None,
        "UNKNOWN",
        reason,
        (),
        None,
    )


def rewind(
    vault_root: Path,
    activation_receipt: ActivationReceipt | object,
    acknowledgement_token: str | None,
    *,
    clock: Callable[[], int | float] = time.time,
) -> RewindReceipt:
    """Restore the exact pre-activation live state in one new transaction."""
    receipt = _validated_activation_receipt(activation_receipt)
    root = Path(vault_root).resolve()
    preview = preview_rewind(root, receipt)
    if preview.status != "OK":
        return _unknown_rewind_receipt(receipt, preview.reason)
    if (
        not isinstance(acknowledgement_token, str)
        or preview.acknowledgement_token is None
        or not hmac.compare_digest(
            acknowledgement_token,
            preview.acknowledgement_token,
        )
    ):
        raise ActivationError(
            "rewind acknowledgement token does not match the exact activation"
        )
    files, contents = _snapshot_rewind_files(root, receipt)
    tx_id = _transaction_id()
    rewound_at = int(clock())
    if rewound_at < 0:
        raise ActivationError("rewind clock returned a negative time")
    result_receipt = RewindReceipt(
        0,
        receipt.capsule_id,
        receipt.proposal_id,
        receipt.transaction_id,
        tx_id,
        "OK",
        "rewound",
        files,
        rewound_at,
    )
    journal_relative = _proposal_journal_relative(
        receipt.capsule_id,
        receipt.proposal_id,
    )
    try:
        journal_bytes = _read_regular_beneath(
            root,
            journal_relative,
            _MAX_RECEIPT_BYTES,
        )
    except (OSError, StagingError) as error:
        raise ActivationError("rewind activation journal is unreadable") from error
    plan: list[PlanEntry] = []
    activated_by_path = {item.path: item for item in receipt.files_written}
    for item in files:
        activated = activated_by_path[item.path]
        content = contents[item.path]
        if item.existed_before_activation:
            if content is None or item.mode is None:
                raise ActivationError(
                    f"rewind snapshot evidence is incomplete: {item.path}"
                )
            plan.append(
                PlanEntry(
                    item.path,
                    content,
                    mode=item.mode,
                    expected_current_sha256=activated.sha256,
                )
            )
        else:
            plan.append(
                PlanEntry(
                    item.path,
                    None,
                    mode=activated.mode,
                    expected_current_sha256=activated.sha256,
                )
            )
    plan.extend(
        (
            PlanEntry(
                _rewind_receipt_relative(receipt.capsule_id),
                result_receipt.canonical_bytes(),
                mode=0o600,
                expected_absent=True,
            ),
            PlanEntry(
                journal_relative,
                journal_bytes,
                mode=0o600,
                expected_current_sha256=_sha256(journal_bytes),
            ),
        )
    )
    journal_path = root / journal_relative

    def finalize_rewind() -> None:
        for item in files:
            target = root / item.path
            if item.existed_before_activation:
                if (
                    item.restored_sha256 is None
                    or item.byte_size is None
                    or item.mode is None
                ):
                    raise ActivationError(
                        f"rewind snapshot evidence is incomplete: {item.path}"
                    )
                exists, digest = _read_live_state(root, item.path)
                metadata = target.lstat()
                if (
                    not exists
                    or digest != item.restored_sha256
                    or not stat.S_ISREG(metadata.st_mode)
                    or stat.S_ISLNK(metadata.st_mode)
                    or metadata.st_size != item.byte_size
                    or stat.S_IMODE(metadata.st_mode) != item.mode
                ):
                    raise ActivationError(
                        f"rewind verification failed: {item.path}"
                    )
            elif target.exists() or target.is_symlink():
                raise ActivationError(
                    f"rewind verification failed to restore absence: {item.path}"
                )
        _activation_stop_seam("rewind-before-journal")
        _append_event(journal_path, MigrationEvent.REWOUND)
        _activation_stop_seam("rewind-mid-finalize")

    try:
        transaction = Transaction._begin_with_id(
            root,
            plan,
            allow_empty=False,
            operation="customization-migration",
            tx_id=tx_id,
        )
        transaction.run(before_commit=finalize_rewind)
    except ActivationError:
        raise
    except PlanRejected as error:
        if _current_live_matches(root, receipt):
            return _unknown_rewind_receipt(receipt, "live-drift")
        raise ActivationError(f"rewind refused safely: {error}") from error
    except (
        LockBusyError,
        OSError,
        SnapshotError,
        StagingError,
        TransactionError,
    ) as error:
        raise ActivationError(f"rewind refused safely: {error}") from error
    return result_receipt


__all__ = [
    "ActivatedFile",
    "ActivationError",
    "ActivationFile",
    "ActivationPreview",
    "ActivationReceipt",
    "ActivationStatus",
    "RewindFile",
    "RewindPreview",
    "RewindReceipt",
    "activate",
    "activation_receipt_from_bytes",
    "preview_activation",
    "preview_rewind",
    "read_activation_status",
    "rewind",
]
