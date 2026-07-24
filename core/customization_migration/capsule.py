"""Protected customization-capsule preview, creation, and inspection.

These functions are consent-agnostic infrastructure. They are not exposed to
any model surface in this lane. Doctor/CLI layers in later lanes own genuine
user confirmation. ``preview_sha256`` is an integrity binding, not consent
(threat-model amendment A1).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from core.customization_migration.capsule_model import (
    CAPSULE_ID,
    EVIDENCE_SECTIONS_V0,
    CapsuleManifest,
)
from core.customization_migration.model import SHA256, Assessment
from core.customization_migration.sensitivity import SECRET_ARCHIVAL_POLICY
from core.customization_migration.service import assess
from core.customization_migration.state import (
    MigrationEvent,
    MigrationState,
    project_state,
    validate_transition,
)
from core.lifecycle.filesystem import FilesystemInspectionError, bounded_read
from core.transaction.engine import PlanEntry, Transaction
from core.transaction.lock import acquire_owned_lock

CAPSULE_ROOT = "System/.dex/customization-migrations"
_MAX_SOURCE_BYTES = 1024 * 1024
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_JOURNAL_BYTES = 1024 * 1024
_MAX_JOURNAL_EVENTS = 256
_MAX_CAPSULES = 256
_EVENT_RECORD_KEYS = frozenset({"schema_version", "event"})


def _capsule_stop_seam(name: str) -> None:
    if os.environ.get("DEX_TX_TEST_STOP_AFTER") == name:
        os._exit(137)


class CapsuleError(RuntimeError):
    """A capsule operation refused to proceed safely."""


@dataclass(frozen=True)
class PlannedCapsuleFile:
    path: str
    byte_size: int
    sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.path, str)
            or not self.path.startswith(CAPSULE_ROOT + "/")
            or PurePosixPath(self.path).as_posix() != self.path
            or any(part in {"", ".", ".."} for part in PurePosixPath(self.path).parts)
        ):
            raise ValueError("planned capsule path is not canonical")
        if type(self.byte_size) is not int or self.byte_size < 0:
            raise ValueError("planned capsule byte_size must be non-negative")
        if not isinstance(self.sha256, str) or SHA256.fullmatch(self.sha256) is None:
            raise ValueError("planned capsule sha256 must be canonical")

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class CapsuleBlobSource:
    source_path: str
    blob_path: str
    byte_size: int
    sha256: str

    def __post_init__(self) -> None:
        source = PurePosixPath(self.source_path)
        if (
            not isinstance(self.source_path, str)
            or not self.source_path
            or source.is_absolute()
            or source.as_posix() != self.source_path
            or any(part in {"", ".", ".."} for part in source.parts)
        ):
            raise ValueError("blob source path is not canonical")
        blob_path = PurePosixPath(self.blob_path)
        if (
            not isinstance(self.blob_path, str)
            or blob_path.as_posix() != self.blob_path
            or any(part in {"", ".", ".."} for part in blob_path.parts)
            or not self.blob_path.endswith("/blobs/" + self.sha256)
        ):
            raise ValueError("blob path is not content-addressed")
        if type(self.byte_size) is not int or self.byte_size < 0:
            raise ValueError("blob source byte_size must be non-negative")
        if not isinstance(self.sha256, str) or SHA256.fullmatch(self.sha256) is None:
            raise ValueError("blob source sha256 must be canonical")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_path": self.source_path,
            "blob_path": self.blob_path,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class CapsulePreview:
    schema_version: int
    capsule_id: str
    manifest: CapsuleManifest
    assessment: Assessment
    files: tuple[PlannedCapsuleFile, ...]
    blob_sources: tuple[CapsuleBlobSource, ...]
    preview_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != 0:
            raise ValueError("unsupported capsule preview schema_version")
        if (
            not isinstance(self.capsule_id, str)
            or CAPSULE_ID.fullmatch(self.capsule_id) is None
        ):
            raise ValueError("capsule preview id is not canonical")
        if type(self.manifest) is not CapsuleManifest:
            raise TypeError("capsule preview manifest must be CapsuleManifest")
        if type(self.assessment) is not Assessment:
            raise TypeError("capsule preview assessment must be Assessment")
        if self.manifest.capsule_id != self.capsule_id:
            raise ValueError("capsule preview manifest id does not match")
        if self.assessment.verdict != "OK":
            raise ValueError("capsule preview requires an OK assessment")
        if not isinstance(self.files, tuple) or any(
            type(item) is not PlannedCapsuleFile for item in self.files
        ):
            raise TypeError("capsule preview files must be a tuple of planned files")
        if tuple(sorted(self.files, key=lambda item: item.path)) != self.files:
            raise ValueError("capsule preview files must be sorted")
        if len({item.path for item in self.files}) != len(self.files):
            raise ValueError("capsule preview file paths must be unique")
        prefix = f"{CAPSULE_ROOT}/{self.capsule_id}/"
        if any(not item.path.startswith(prefix) for item in self.files):
            raise ValueError("capsule preview file escapes its capsule directory")
        if not isinstance(self.blob_sources, tuple) or any(
            type(item) is not CapsuleBlobSource for item in self.blob_sources
        ):
            raise TypeError("capsule blob sources must be a tuple")
        if tuple(
            sorted(self.blob_sources, key=lambda item: item.source_path)
        ) != self.blob_sources:
            raise ValueError("capsule blob sources must be sorted")
        if len({item.source_path for item in self.blob_sources}) != len(
            self.blob_sources
        ):
            raise ValueError("capsule blob source paths must be unique")
        if any(not item.blob_path.startswith(prefix) for item in self.blob_sources):
            raise ValueError("capsule blob path escapes its capsule directory")
        if not isinstance(self.preview_sha256, str) or SHA256.fullmatch(
            self.preview_sha256
        ) is None:
            raise ValueError("preview_sha256 must be canonical")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capsule_id": self.capsule_id,
            "manifest": self.manifest.to_dict(),
            "assessment": self.assessment.to_dict(),
            "files": [item.to_dict() for item in self.files],
            "blob_sources": [item.to_dict() for item in self.blob_sources],
        }

    def canonical_preview_bytes(self) -> bytes:
        return _canonical_json(self._unsigned_dict())

    def to_dict(self) -> dict[str, object]:
        result = self._unsigned_dict()
        result["preview_sha256"] = self.preview_sha256
        return result


@dataclass(frozen=True)
class CapsuleReceipt:
    schema_version: int
    capsule_id: str
    manifest_sha256: str
    file_count: int
    byte_count: int
    transaction_id: str

    def __post_init__(self) -> None:
        if (
            self.schema_version != 0
            or not isinstance(self.capsule_id, str)
            or CAPSULE_ID.fullmatch(self.capsule_id) is None
        ):
            raise ValueError("capsule receipt identity is invalid")
        if (
            not isinstance(self.manifest_sha256, str)
            or SHA256.fullmatch(self.manifest_sha256) is None
        ):
            raise ValueError("capsule receipt manifest_sha256 is invalid")
        if type(self.file_count) is not int or self.file_count < 0:
            raise ValueError("capsule receipt file_count must be non-negative")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise ValueError("capsule receipt byte_count must be non-negative")
        if (
            not isinstance(self.transaction_id, str)
            or not self.transaction_id
            or "/" in self.transaction_id
            or "\x00" in self.transaction_id
        ):
            raise ValueError("capsule receipt transaction_id is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capsule_id": self.capsule_id,
            "manifest_sha256": self.manifest_sha256,
            "file_count": self.file_count,
            "byte_count": self.byte_count,
            "transaction_id": self.transaction_id,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True)
class CapsuleStatus:
    capsule_id: str
    state: MigrationState

    def __post_init__(self) -> None:
        if (
            not isinstance(self.capsule_id, str)
            or not self.capsule_id
            or len(self.capsule_id) > 255
            or "/" in self.capsule_id
            or "\x00" in self.capsule_id
        ):
            raise ValueError("capsule status id is invalid")
        if not isinstance(self.state, MigrationState):
            raise TypeError("capsule status state must be MigrationState")


@dataclass(frozen=True)
class MigrationStatus:
    capsules: tuple[CapsuleStatus, ...]
    truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.capsules, tuple) or any(
            type(item) is not CapsuleStatus for item in self.capsules
        ):
            raise TypeError("migration status capsules must be a tuple")
        if tuple(sorted(self.capsules, key=lambda item: item.capsule_id)) != self.capsules:
            raise ValueError("migration status capsules must be sorted")
        if type(self.truncated) is not bool:
            raise TypeError("migration status truncated must be boolean")


@dataclass(frozen=True)
class CapsuleValidation:
    status: str
    mismatches: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in {"OK", "BROKEN", "UNKNOWN"}:
            raise ValueError("capsule validation status is invalid")
        if tuple(sorted(set(self.mismatches))) != self.mismatches:
            raise ValueError("capsule validation mismatches must be sorted and unique")


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


def _event_bytes(event: MigrationEvent) -> bytes:
    return _canonical_json({"schema_version": 0, "event": event.value})


def _evidence_sections(assessment: Assessment) -> dict[str, bytes]:
    restricted = [
        {
            "customization_id": record.customization_id,
            "kind": record.kind.value,
            "source_paths": list(record.source_paths),
            "finding": "restricted-content-left-in-place",
        }
        for record in assessment.records
        if record.live.model_readability == "restricted"
    ]
    sections = {
        "customizations": _canonical_json(
            {
                "schema_version": 0,
                "items": [record.to_dict() for record in assessment.records],
            }
        ),
        "dependencies": _canonical_json(
            {
                "schema_version": 0,
                "items": [edge.to_dict() for edge in assessment.edges],
            }
        ),
        "behaviours": _canonical_json({"schema_version": 0, "items": []}),
        "exclusions": _canonical_json(
            {
                "schema_version": 0,
                "items": [item.to_dict() for item in assessment.exclusions],
                "restricted_findings": restricted,
                "secret_archival_policy": SECRET_ARCHIVAL_POLICY,
            }
        ),
        "environment": _canonical_json(
            {
                "schema_version": 0,
                "identity": assessment.identity.to_dict(),
                "baseline_identity_state": assessment.baseline_identity_state,
                "baseline_errors": list(assessment.baseline_errors),
                "completeness": assessment.completeness,
                "verdict": assessment.verdict,
            }
        ),
    }
    if frozenset(sections) != EVIDENCE_SECTIONS_V0:
        raise CapsuleError("capsule evidence sections drifted from the v0 contract")
    return sections


def _manifest_for(
    assessment: Assessment,
    capsule_id: str,
    *,
    created_epoch_seconds: int,
) -> tuple[CapsuleManifest, dict[str, bytes]]:
    sections = _evidence_sections(assessment)
    section_digests = tuple(
        (name, _sha256(raw), len(raw)) for name, raw in sorted(sections.items())
    )
    restricted_count = sum(
        record.live.model_readability == "restricted"
        for record in assessment.records
    )
    manifest = CapsuleManifest(
        schema_version=0,
        capsule_id=capsule_id,
        source_release_version=assessment.identity.release_version or "",
        target_release_version=None,
        created_epoch_seconds=created_epoch_seconds,
        inventory_digest=_sha256(
            _canonical_json(assessment.identity.to_dict())
        ),
        assessment_digest=_sha256(assessment.canonical_assessment_bytes()),
        customization_count=len(assessment.records),
        dependency_count=len(assessment.edges),
        behaviour_contract_count=0,
        restricted_item_count=restricted_count,
        excluded_reasons=tuple(
            sorted({item.reason for item in assessment.exclusions})
        ),
        completeness=assessment.completeness,
        section_digests=section_digests,
    )
    return manifest, sections


def _blob_sources(
    assessment: Assessment,
    capsule_id: str,
) -> tuple[CapsuleBlobSource, ...]:
    result: list[CapsuleBlobSource] = []
    prefix = f"{CAPSULE_ROOT}/{capsule_id}/blobs"
    for record in assessment.records:
        if record.live.model_readability != "readable":
            continue
        assert record.live.sha256 is not None
        assert record.live.byte_size is not None
        for source_path in record.source_paths:
            result.append(
                CapsuleBlobSource(
                    source_path,
                    f"{prefix}/{record.live.sha256}",
                    record.live.byte_size,
                    record.live.sha256,
                )
            )
    return tuple(sorted(result, key=lambda item: item.source_path))


def _planned_files(
    capsule_id: str,
    manifest: CapsuleManifest,
    sections: dict[str, bytes],
    blob_sources: tuple[CapsuleBlobSource, ...],
) -> tuple[PlannedCapsuleFile, ...]:
    prefix = f"{CAPSULE_ROOT}/{capsule_id}"
    materials: dict[str, tuple[int, str]] = {}
    manifest_raw = manifest.canonical_manifest_bytes()
    materials[f"{prefix}/manifest.json"] = (len(manifest_raw), _sha256(manifest_raw))
    for name, raw in sections.items():
        materials[f"{prefix}/evidence/{name}.json"] = (len(raw), _sha256(raw))
    for source in blob_sources:
        materials[source.blob_path] = (source.byte_size, source.sha256)
    assessed = _event_bytes(MigrationEvent.ASSESSED)
    materials[f"{prefix}/journal.jsonl"] = (len(assessed), _sha256(assessed))
    return tuple(
        PlannedCapsuleFile(path, size, digest)
        for path, (size, digest) in sorted(materials.items())
    )


def preview_capsule(
    vault_root: Path,
    *,
    clock: Callable[[], int] = time.time,
    capsule_id: str | None = None,
) -> CapsulePreview:
    """Build a deterministic, integrity-bound plan without writing the vault."""
    assessment = assess(Path(vault_root))
    if assessment.verdict != "OK":
        raise CapsuleError(
            "capsule preview requires a complete VERIFIED assessment with verdict OK"
        )
    if capsule_id is None:
        capsule_id = "cap-" + secrets.token_hex(8)
    elif CAPSULE_ID.fullmatch(capsule_id) is None:
        raise CapsuleError("capsule preview id is not canonical")
    manifest, sections = _manifest_for(
        assessment,
        capsule_id,
        created_epoch_seconds=int(clock()),
    )
    sources = _blob_sources(assessment, capsule_id)
    files = _planned_files(capsule_id, manifest, sections, sources)
    unsigned = CapsulePreview(
        0,
        capsule_id,
        manifest,
        assessment,
        files,
        sources,
        "0" * 64,
    )
    digest = _sha256(unsigned.canonical_preview_bytes())
    return CapsulePreview(
        0,
        capsule_id,
        manifest,
        assessment,
        files,
        sources,
        digest,
    )


def _read_blob_source(root: Path, source: CapsuleBlobSource) -> bytes:
    try:
        raw = bounded_read(root, source.source_path, max_bytes=_MAX_SOURCE_BYTES)
    except FilesystemInspectionError as error:
        raise CapsuleError(f"{source.source_path} drifted or is unreadable") from error
    if (
        len(raw) != source.byte_size
        or _sha256(raw) != source.sha256
    ):
        raise CapsuleError(f"{source.source_path} drifted after capsule preview")
    return raw


def _transaction_id() -> str:
    return time.strftime("%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:8]


def _receipt_for(
    capsule_id: str,
    manifest: CapsuleManifest,
    materials: dict[str, bytes],
    tx_id: str,
) -> CapsuleReceipt:
    file_count = len(materials) + 1
    final_event_bytes = len(_event_bytes(MigrationEvent.CAPSULE_PREVIEWED)) + len(
        _event_bytes(MigrationEvent.CAPSULE_CREATED)
    )
    byte_count = 0
    for _ in range(16):
        receipt = CapsuleReceipt(
            0,
            capsule_id,
            _sha256(manifest.canonical_manifest_bytes()),
            file_count,
            byte_count,
            tx_id,
        )
        actual = (
            sum(len(raw) for raw in materials.values())
            + len(receipt.canonical_bytes())
            + final_event_bytes
        )
        if actual == byte_count:
            return receipt
        byte_count = actual
    raise CapsuleError("capsule receipt byte count did not converge")


def _append_event(path: Path, event: MigrationEvent) -> None:
    raw = _event_bytes(event)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise CapsuleError(f"capsule journal is not a regular file: {path}")
        written = os.write(descriptor, raw)
        if written != len(raw):
            raise CapsuleError(f"short append to capsule journal: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _ensure_layout(capsule_dir: Path) -> None:
    def secure_directory(directory: Path) -> None:
        directory.mkdir(mode=0o700, exist_ok=True)
        descriptor = os.open(
            directory,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise CapsuleError(f"capsule layout path is not a directory: {directory}")
            os.fchmod(descriptor, 0o700)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    capsule_root = capsule_dir.parent
    capsule_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    secure_directory(capsule_root)
    secure_directory(capsule_dir)
    with os.scandir(capsule_dir) as children:
        for child in children:
            if child.is_dir(follow_symlinks=False):
                secure_directory(Path(child.path))


def create_capsule(
    vault_root: Path,
    preview: CapsulePreview,
    preview_sha256: str,
) -> CapsuleReceipt:
    """Create one protected capsule through a single sealed transaction."""
    if type(preview) is not CapsulePreview:
        raise TypeError("preview must be CapsulePreview")
    recomputed = _sha256(preview.canonical_preview_bytes())
    if (
        preview_sha256 != preview.preview_sha256
        or preview_sha256 != recomputed
    ):
        raise CapsuleError("capsule preview digest mismatch")

    root = Path(vault_root).resolve()
    capsule_dir = root / CAPSULE_ROOT / preview.capsule_id
    if capsule_dir.exists() or capsule_dir.is_symlink():
        raise CapsuleError(f"capsule already exists: {preview.capsule_id}")

    manifest, sections = _manifest_for(
        preview.assessment,
        preview.capsule_id,
        created_epoch_seconds=preview.manifest.created_epoch_seconds,
    )
    if manifest != preview.manifest:
        raise CapsuleError("capsule preview manifest drifted")
    expected_files = _planned_files(
        preview.capsule_id,
        manifest,
        sections,
        preview.blob_sources,
    )
    if expected_files != preview.files:
        raise CapsuleError("capsule preview file plan drifted")

    # The preview binds to this vault solely through these per-blob re-read hash
    # checks; a preview built against a different vault fails here.
    blobs: dict[str, bytes] = {}
    for source in preview.blob_sources:
        raw = _read_blob_source(root, source)
        previous = blobs.setdefault(source.blob_path, raw)
        if previous != raw:
            raise CapsuleError(f"content-address collision for {source.blob_path}")

    prefix = f"{CAPSULE_ROOT}/{preview.capsule_id}"
    materials: dict[str, bytes] = {
        f"{prefix}/manifest.json": manifest.canonical_manifest_bytes(),
        f"{prefix}/journal.jsonl": _event_bytes(MigrationEvent.ASSESSED),
    }
    materials.update(
        {f"{prefix}/evidence/{name}.json": raw for name, raw in sections.items()}
    )
    materials.update(blobs)
    for planned in preview.files:
        raw = materials.get(planned.path)
        if (
            raw is None
            or len(raw) != planned.byte_size
            or _sha256(raw) != planned.sha256
        ):
            raise CapsuleError(f"planned capsule bytes drifted: {planned.path}")

    tx_id = _transaction_id()
    receipt = _receipt_for(
        preview.capsule_id,
        manifest,
        materials,
        tx_id,
    )
    materials[f"{prefix}/receipts/capsule.json"] = receipt.canonical_bytes()
    plan = [
        PlanEntry(path, raw, mode=0o600)
        for path, raw in sorted(materials.items())
    ]
    transaction = Transaction._begin_with_id(
        root,
        plan,
        allow_empty=False,
        operation="customization-migration",
        tx_id=tx_id,
    )

    journal_path = capsule_dir / "journal.jsonl"

    def finalize_capsule() -> None:
        _ensure_layout(capsule_dir)
        _capsule_stop_seam("capsule-after-layout")
        _append_event(journal_path, MigrationEvent.CAPSULE_PREVIEWED)
        _capsule_stop_seam("capsule-mid-finalize")
        _append_event(journal_path, MigrationEvent.CAPSULE_CREATED)

    transaction.run(before_commit=finalize_capsule)
    return receipt


def _read_events(path: Path) -> tuple[str, ...]:
    try:
        raw = _read_regular_nofollow(path, _MAX_JOURNAL_BYTES)
    except OSError as error:
        raise CapsuleError("capsule journal is missing") from error
    if not raw.endswith(b"\n"):
        raise CapsuleError("capsule journal has a torn final record")
    lines = raw.splitlines()
    if len(lines) > _MAX_JOURNAL_EVENTS:
        raise CapsuleError("capsule journal exceeds the event bound")
    events: list[str] = []
    for line in lines:
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CapsuleError("capsule journal is malformed") from error
        if (
            not isinstance(record, dict)
            or frozenset(record) != _EVENT_RECORD_KEYS
            or record.get("schema_version") != 0
            or not isinstance(record.get("event"), str)
            or _canonical_json(record).rstrip(b"\n") != line
        ):
            raise CapsuleError("capsule journal record is not canonical")
        events.append(record["event"])
    return tuple(events)


def read_capsule_status(vault_root: Path) -> MigrationStatus:
    """Project bounded journal evidence; malformed evidence never becomes empty."""
    root = Path(vault_root).resolve()
    capsule_root = root / CAPSULE_ROOT
    if not capsule_root.exists():
        return MigrationStatus(())
    if capsule_root.is_symlink() or not capsule_root.is_dir():
        return MigrationStatus(
            (CapsuleStatus("<capsule-root>", MigrationState.RECOVERY_REQUIRED),)
        )
    candidates: list[Path] = []
    with os.scandir(capsule_root) as iterator:
        for entry in iterator:
            candidates.append(Path(entry.path))
            if len(candidates) > _MAX_CAPSULES:
                break
    truncated = len(candidates) > _MAX_CAPSULES
    candidates = sorted(
        candidates[:_MAX_CAPSULES],
        key=lambda item: item.name,
    )
    statuses: list[CapsuleStatus] = []
    for candidate in candidates[:_MAX_CAPSULES]:
        state = MigrationState.RECOVERY_REQUIRED
        try:
            metadata = candidate.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or candidate.is_symlink():
                raise CapsuleError("capsule entry is not a real directory")
            events = _read_events(candidate / "journal.jsonl")
            state = project_state(events)
        except (OSError, CapsuleError):
            pass
        statuses.append(CapsuleStatus(candidate.name, state))
    return MigrationStatus(tuple(statuses), truncated)


def abandon_capsule(vault_root: Path, capsule_id: str) -> None:
    """Append an allowed abandonment event without deleting capsule evidence."""
    if not isinstance(capsule_id, str) or CAPSULE_ID.fullmatch(capsule_id) is None:
        raise CapsuleError("capsule_id is not canonical")
    root = Path(vault_root).resolve()
    capsule_dir = root / CAPSULE_ROOT / capsule_id
    try:
        current = next(
            item.state
            for item in read_capsule_status(root).capsules
            if item.capsule_id == capsule_id
        )
    except StopIteration as error:
        raise CapsuleError(f"capsule does not exist: {capsule_id}") from error
    validate_transition(current, MigrationState.ABANDONED)
    release = acquire_owned_lock(root, f"customization-abandon:{capsule_id}")
    try:
        current_locked = project_state(_read_events(capsule_dir / "journal.jsonl"))
        validate_transition(current_locked, MigrationState.ABANDONED)
        _append_event(capsule_dir / "journal.jsonl", MigrationEvent.ABANDONED)
    finally:
        release()


def _read_regular_nofollow(path: Path, limit: int) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise CapsuleError(f"not a bounded regular file: {path}")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > limit:
            raise CapsuleError(f"bounded read exceeded: {path}")
        return raw
    finally:
        os.close(descriptor)


def _bounded_capsule_bytes(root: Path, relative: str, limit: int) -> bytes:
    try:
        return bounded_read(root, relative, max_bytes=limit)
    except FilesystemInspectionError as error:
        raise CapsuleError(f"unsafe capsule read: {relative}") from error


def _manifest_from_bytes(raw: bytes) -> CapsuleManifest:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CapsuleError("manifest is unreadable") from error
    if not isinstance(value, dict):
        raise CapsuleError("manifest is not an object")
    expected = {
        "schema_version",
        "capsule_id",
        "source_release_version",
        "target_release_version",
        "created_epoch_seconds",
        "inventory_digest",
        "assessment_digest",
        "customization_count",
        "dependency_count",
        "behaviour_contract_count",
        "restricted_item_count",
        "excluded_reasons",
        "completeness",
        "section_digests",
    }
    if set(value) != expected or not isinstance(value.get("section_digests"), list):
        raise CapsuleError("manifest shape is not the closed v0 schema")
    try:
        manifest = CapsuleManifest(
            schema_version=value["schema_version"],
            capsule_id=value["capsule_id"],
            source_release_version=value["source_release_version"],
            target_release_version=value["target_release_version"],
            created_epoch_seconds=value["created_epoch_seconds"],
            inventory_digest=value["inventory_digest"],
            assessment_digest=value["assessment_digest"],
            customization_count=value["customization_count"],
            dependency_count=value["dependency_count"],
            behaviour_contract_count=value["behaviour_contract_count"],
            restricted_item_count=value["restricted_item_count"],
            excluded_reasons=tuple(value["excluded_reasons"]),
            completeness=value["completeness"],
            section_digests=tuple(
                (
                    item["section_name"],
                    item["sha256"],
                    item["byte_size"],
                )
                for item in value["section_digests"]
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CapsuleError("manifest fails v0 validation") from error
    if manifest.canonical_manifest_bytes() != raw:
        raise CapsuleError("manifest is not canonical")
    return manifest


def _receipt_from_bytes(raw: bytes) -> CapsuleReceipt:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CapsuleError("capsule receipt is unreadable") from error
    expected = {
        "schema_version",
        "capsule_id",
        "manifest_sha256",
        "file_count",
        "byte_count",
        "transaction_id",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise CapsuleError("capsule receipt shape is not the closed v0 schema")
    try:
        receipt = CapsuleReceipt(
            value["schema_version"],
            value["capsule_id"],
            value["manifest_sha256"],
            value["file_count"],
            value["byte_count"],
            value["transaction_id"],
        )
    except (TypeError, ValueError) as error:
        raise CapsuleError("capsule receipt fails v0 validation") from error
    if receipt.canonical_bytes() != raw:
        raise CapsuleError("capsule receipt is not canonical")
    return receipt


def validate_capsule(vault_root: Path, capsule_id: str) -> CapsuleValidation:
    """Recompute manifest, section, and blob integrity for one capsule."""
    if not isinstance(capsule_id, str) or CAPSULE_ID.fullmatch(capsule_id) is None:
        return CapsuleValidation("UNKNOWN", ())
    root = Path(vault_root).resolve()
    capsule_dir = root / CAPSULE_ROOT / capsule_id
    if not capsule_dir.exists() or capsule_dir.is_symlink() or not capsule_dir.is_dir():
        return CapsuleValidation("UNKNOWN", ())
    mismatches: set[str] = set()
    try:
        manifest_raw = _bounded_capsule_bytes(
            capsule_dir,
            "manifest.json",
            _MAX_MANIFEST_BYTES,
        )
        manifest = _manifest_from_bytes(manifest_raw)
        if manifest.capsule_id != capsule_id:
            mismatches.add("manifest.json:capsule-id")
    except (OSError, CapsuleError):
        return CapsuleValidation("BROKEN", ("manifest.json",))

    try:
        receipt = _receipt_from_bytes(
            _bounded_capsule_bytes(
                capsule_dir,
                "receipts/capsule.json",
                _MAX_MANIFEST_BYTES,
            )
        )
        if receipt.capsule_id != capsule_id or receipt.manifest_sha256 != _sha256(
            manifest_raw
        ):
            mismatches.add("receipts/capsule.json")
    except (OSError, CapsuleError):
        mismatches.add("receipts/capsule.json")

    section_payloads: dict[str, bytes] = {}
    for name, expected_digest, expected_size in manifest.section_digests:
        relative = f"evidence/{name}.json"
        try:
            raw = _bounded_capsule_bytes(
                capsule_dir,
                relative,
                _MAX_MANIFEST_BYTES,
            )
        except (OSError, CapsuleError):
            mismatches.add(relative)
            continue
        section_payloads[name] = raw
        if len(raw) != expected_size or _sha256(raw) != expected_digest:
            mismatches.add(relative)

    customizations = section_payloads.get("customizations")
    expected_blobs: set[str] = set()
    if customizations is not None:
        try:
            payload = json.loads(customizations.decode("utf-8"))
            items = payload["items"]
            if not isinstance(items, list):
                raise TypeError
            for item in items:
                live = item["live"]
                if live["model_readability"] == "readable":
                    digest = live["sha256"]
                    if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
                        raise ValueError
                    expected_blobs.add(digest)
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            mismatches.add("evidence/customizations.json")
    for digest in sorted(expected_blobs):
        relative = f"blobs/{digest}"
        try:
            raw = _bounded_capsule_bytes(
                capsule_dir,
                relative,
                _MAX_SOURCE_BYTES,
            )
        except (OSError, CapsuleError):
            mismatches.add(relative)
            continue
        if _sha256(raw) != digest:
            mismatches.add(relative)
    return CapsuleValidation(
        "BROKEN" if mismatches else "OK",
        tuple(sorted(mismatches)),
    )


__all__ = [
    "CAPSULE_ROOT",
    "CapsuleBlobSource",
    "CapsuleError",
    "CapsulePreview",
    "CapsuleReceipt",
    "CapsuleStatus",
    "CapsuleValidation",
    "MigrationStatus",
    "PlannedCapsuleFile",
    "abandon_capsule",
    "create_capsule",
    "preview_capsule",
    "read_capsule_status",
    "validate_capsule",
]
