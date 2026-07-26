"""Consent-agnostic private staging for regeneration candidates.

This module has no authority to write a live customization seam. Every
mutation is confined to an existing capsule and passes through one sealed
``customization-migration`` transaction. ``preview_sha256`` binds integrity;
it is non-secret by construction and is never evidence of consent (A1).
"""

from __future__ import annotations

import base64
import hashlib
import itertools
import json
import os
import stat
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from core import portable_contract
from core.customization_migration.behaviour import (
    BehaviouralContract,
    ContractProvenance,
    VerificationClass,
)
from core.customization_migration.capsule import (
    CAPSULE_ROOT,
    CapsuleError,
    _manifest_from_bytes,
    validate_capsule,
)
from core.customization_migration.capsule_model import CAPSULE_ID
from core.customization_migration.model import (
    SHA256,
    Assessment,
    AssessmentAssignment,
    AssessmentExclusion,
    AssessmentGroup,
    AssessmentIdentity,
    BaselineInfo,
    CustomizationEvidence,
    CustomizationKind,
    CustomizationRecord,
    EdgeKind,
    LiveInfo,
    ReferenceConfidence,
    ReferenceEdge,
)
from core.customization_migration.planning import (
    PROPOSAL_ID,
    CandidateFile,
    DeclaredRequirement,
    DependencyRemapping,
    DependencyResolution,
    Disposition,
    DispositionPlanItem,
    RegenerationCandidate,
    RequirementKind,
    ShimExpiry,
    validate_regeneration_candidate,
)
from core.customization_migration.state import (
    MigrationEvent,
    MigrationState,
    project_state,
)
from core.transaction.engine import PlanEntry, Transaction

STAGING_SUBDIR = "candidates/{proposal_id}/staging"
_MAX_JSON_BYTES = 1024 * 1024
_MAX_STAGED_BYTES = 8 * 1024 * 1024
_MAX_STAGED_FILES = 1024
_MAX_PROPOSALS = 256
_EVENT_KEYS = frozenset({"schema_version", "event"})
_VERIFICATION_EVENT_KEYS = frozenset(
    {
        "schema_version",
        "event",
        "candidate_sha256",
        "report_path",
        "report_sha256",
    }
)


class StagingError(RuntimeError):
    """The candidate could not safely enter or leave private staging."""


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
        raise ValueError(f"{name} must be a non-empty canonical relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{name} must be a canonical relative path")
    return value


def _open_directory_beneath(root: Path, relative: str) -> int:
    normalized = _canonical_relative(relative, name="private directory")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(root, flags)
    try:
        for part in PurePosixPath(normalized).parts:
            next_descriptor = os.open(
                part,
                flags,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_regular_beneath(
    root: Path,
    relative: str,
    limit: int = _MAX_JSON_BYTES,
) -> bytes:
    normalized = _canonical_relative(relative, name="private file")
    parts = PurePosixPath(normalized).parts
    parent_relative = PurePosixPath(*parts[:-1]).as_posix()
    parent = _open_directory_beneath(root, parent_relative)
    try:
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent,
        )
    finally:
        os.close(parent)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise StagingError(f"not a bounded regular file: {relative}")
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
            raise StagingError(f"bounded read exceeded: {relative}")
        return raw
    finally:
        os.close(descriptor)


def _scan_directory_beneath(
    root: Path,
    relative: str,
    *,
    limit: int,
) -> dict[str, os.stat_result]:
    descriptor = _open_directory_beneath(root, relative)
    result: dict[str, os.stat_result] = {}
    try:
        with os.scandir(descriptor) as iterator:
            for entry in iterator:
                if len(result) >= limit:
                    raise StagingError(
                        f"private directory exceeds its entry bound: {relative}"
                    )
                result[entry.name] = entry.stat(follow_symlinks=False)
    finally:
        os.close(descriptor)
    return result


@dataclass(frozen=True)
class PlannedStagedFile:
    target_path: str
    staging_path: str
    sha256: str
    byte_size: int
    mode: int = 0o600

    def __post_init__(self) -> None:
        _canonical_relative(self.target_path, name="planned target_path")
        _canonical_relative(self.staging_path, name="planned staging_path")
        if not self.staging_path.endswith("/files/" + self.sha256):
            raise ValueError("planned staging path is not content-addressed")
        if not isinstance(self.sha256, str) or SHA256.fullmatch(self.sha256) is None:
            raise ValueError("planned staged sha256 must be canonical")
        if type(self.byte_size) is not int or self.byte_size <= 0:
            raise ValueError("planned staged byte_size must be positive")
        if self.mode != 0o600:
            raise ValueError("staged files must remain mode 0600")

    def to_dict(self) -> dict[str, object]:
        return {
            "target_path": self.target_path,
            "staging_path": self.staging_path,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "mode": self.mode,
        }


@dataclass(frozen=True)
class StagingPreview:
    schema_version: int
    capsule_id: str
    proposal_id: str
    candidate: RegenerationCandidate
    files: tuple[PlannedStagedFile, ...]
    preview_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != 0:
            raise ValueError("unsupported staging preview schema_version")
        if not isinstance(self.capsule_id, str) or CAPSULE_ID.fullmatch(self.capsule_id) is None:
            raise ValueError("staging preview capsule_id is not canonical")
        if not isinstance(self.proposal_id, str) or PROPOSAL_ID.fullmatch(self.proposal_id) is None:
            raise ValueError("staging preview proposal_id is not canonical")
        if type(self.candidate) is not RegenerationCandidate:
            raise TypeError("staging preview candidate must be RegenerationCandidate")
        if (
            self.candidate.capsule_id != self.capsule_id
            or self.candidate.proposal_id != self.proposal_id
        ):
            raise ValueError("staging preview identity does not match candidate")
        if not isinstance(self.files, tuple) or any(
            type(item) is not PlannedStagedFile for item in self.files
        ):
            raise TypeError("staging preview files must be PlannedStagedFile records")
        if tuple(sorted(self.files, key=lambda item: item.target_path)) != self.files:
            raise ValueError("staging preview files must be sorted")
        if len({item.target_path for item in self.files}) != len(self.files):
            raise ValueError("staging preview target paths must be unique")
        if not isinstance(self.preview_sha256, str) or SHA256.fullmatch(
            self.preview_sha256
        ) is None:
            raise ValueError("staging preview digest must be canonical")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capsule_id": self.capsule_id,
            "proposal_id": self.proposal_id,
            "candidate": self.candidate.to_dict(),
            "files": [item.to_dict() for item in self.files],
        }

    def canonical_preview_bytes(self) -> bytes:
        return _canonical_json(self._unsigned_dict())

    def to_dict(self) -> dict[str, object]:
        result = self._unsigned_dict()
        result["preview_sha256"] = self.preview_sha256
        return result


@dataclass(frozen=True)
class StagingReceipt:
    schema_version: int
    capsule_id: str
    proposal_id: str
    staged_file_count: int
    staged_byte_count: int
    staging_digest: str
    transaction_id: str

    def __post_init__(self) -> None:
        if self.schema_version != 0:
            raise ValueError("unsupported staging receipt schema_version")
        if not isinstance(self.capsule_id, str) or CAPSULE_ID.fullmatch(self.capsule_id) is None:
            raise ValueError("staging receipt capsule_id is not canonical")
        if not isinstance(self.proposal_id, str) or PROPOSAL_ID.fullmatch(self.proposal_id) is None:
            raise ValueError("staging receipt proposal_id is not canonical")
        if type(self.staged_file_count) is not int or self.staged_file_count < 0:
            raise ValueError("staged_file_count must be non-negative")
        if type(self.staged_byte_count) is not int or self.staged_byte_count < 0:
            raise ValueError("staged_byte_count must be non-negative")
        if not isinstance(self.staging_digest, str) or SHA256.fullmatch(
            self.staging_digest
        ) is None:
            raise ValueError("staging_digest must be canonical")
        if (
            not isinstance(self.transaction_id, str)
            or not self.transaction_id
            or "/" in self.transaction_id
            or "\x00" in self.transaction_id
        ):
            raise ValueError("staging receipt transaction_id is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capsule_id": self.capsule_id,
            "proposal_id": self.proposal_id,
            "staged_file_count": self.staged_file_count,
            "staged_byte_count": self.staged_byte_count,
            "staging_digest": self.staging_digest,
            "transaction_id": self.transaction_id,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True)
class ProposalStagingStatus:
    proposal_id: str
    state: MigrationState

    def __post_init__(self) -> None:
        if (
            not isinstance(self.proposal_id, str)
            or not self.proposal_id
            or "/" in self.proposal_id
            or "\x00" in self.proposal_id
        ):
            raise ValueError("proposal status id is invalid")
        if not isinstance(self.state, MigrationState):
            raise TypeError("proposal status state must be MigrationState")


@dataclass(frozen=True)
class StagingStatus:
    capsule_id: str
    proposals: tuple[ProposalStagingStatus, ...]
    truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.capsule_id, str) or CAPSULE_ID.fullmatch(self.capsule_id) is None:
            raise ValueError("staging status capsule_id is not canonical")
        if not isinstance(self.proposals, tuple) or any(
            type(item) is not ProposalStagingStatus for item in self.proposals
        ):
            raise TypeError("staging status proposals must be a tuple")
        if tuple(sorted(self.proposals, key=lambda item: item.proposal_id)) != self.proposals:
            raise ValueError("staging status proposals must be sorted")
        if type(self.truncated) is not bool:
            raise TypeError("staging status truncated must be boolean")


@dataclass(frozen=True)
class StagingValidation:
    status: str
    mismatches: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in {"OK", "BROKEN", "UNKNOWN"}:
            raise ValueError("staging validation status is invalid")
        if tuple(sorted(set(self.mismatches))) != self.mismatches:
            raise ValueError("staging validation mismatches must be sorted and unique")


def _strict_object(raw: bytes, *, context: str) -> dict[str, object]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StagingError(f"{context} is unreadable") from error
    if not isinstance(value, dict) or _canonical_json(value) != raw:
        raise StagingError(f"{context} is not canonical")
    return value


def _closed_mapping(
    value: object,
    *,
    keys: frozenset[str],
    context: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or frozenset(value) != keys:
        raise StagingError(f"{context} has an invalid shape")
    return value


def _closed_list(value: object, *, context: str) -> list[object]:
    if not isinstance(value, list):
        raise StagingError(f"{context} must be a list")
    return value


def _strings(value: object, *, context: str) -> tuple[str, ...]:
    items = _closed_list(value, context=context)
    if any(not isinstance(item, str) for item in items):
        raise StagingError(f"{context} must contain only strings")
    return tuple(items)


def _record_from_dict(value: object) -> CustomizationRecord:
    item = _closed_mapping(
        value,
        keys=frozenset(
            {
                "customization_id",
                "kind",
                "source_paths",
                "baseline",
                "live",
                "evidence",
                "required_disposition",
            }
        ),
        context="capsule customization record",
    )
    baseline = _closed_mapping(
        item["baseline"],
        keys=frozenset({"release_version", "sha256"}),
        context="capsule baseline",
    )
    live = item["live"]
    if not isinstance(live, dict) or frozenset(live) not in {
        frozenset({"sha256", "byte_size", "model_readability"}),
        frozenset({"sha256", "byte_size", "model_readability", "executable"}),
    }:
        raise StagingError("capsule live evidence has an invalid shape")
    evidence = _closed_mapping(
        item["evidence"],
        keys=frozenset({"release_state", "reference_edge_ids"}),
        context="capsule customization evidence",
    )
    try:
        return CustomizationRecord(
            item["customization_id"],
            CustomizationKind(item["kind"]),
            _strings(item["source_paths"], context="source_paths"),
            BaselineInfo(baseline["release_version"], baseline["sha256"]),
            LiveInfo(
                live["sha256"],
                live["byte_size"],
                live["model_readability"],
                live.get("executable"),
            ),
            CustomizationEvidence(
                evidence["release_state"],
                _strings(evidence["reference_edge_ids"], context="reference_edge_ids"),
            ),
            item["required_disposition"],
        )
    except (TypeError, ValueError) as error:
        raise StagingError("capsule customization record is invalid") from error


def _edge_from_dict(value: object) -> ReferenceEdge:
    item = _closed_mapping(
        value,
        keys=frozenset(
            {"edge_id", "source_path", "target", "edge_kind", "confidence"}
        ),
        context="capsule dependency edge",
    )
    try:
        return ReferenceEdge(
            item["edge_id"],
            item["source_path"],
            item["target"],
            EdgeKind(item["edge_kind"]),
            ReferenceConfidence(item["confidence"]),
        )
    except (TypeError, ValueError) as error:
        raise StagingError("capsule dependency edge is invalid") from error


def _exclusion_from_dict(value: object) -> AssessmentExclusion:
    if not isinstance(value, dict) or frozenset(value) not in {
        frozenset({"path", "reason"}),
        frozenset({"path", "reason", "uninspected_count"}),
    }:
        raise StagingError("capsule exclusion has an invalid shape")
    try:
        return AssessmentExclusion(
            value["path"],
            value["reason"],
            value.get("uninspected_count"),
        )
    except (TypeError, ValueError) as error:
        raise StagingError("capsule exclusion is invalid") from error


def _frozen_group_options(
    records: tuple[CustomizationRecord, ...],
    edges: tuple[ReferenceEdge, ...],
) -> tuple[tuple[CustomizationRecord, tuple[AssessmentGroup, ...]], ...]:
    edges_by_source: dict[str, list[ReferenceEdge]] = {}
    for edge in edges:
        edges_by_source.setdefault(edge.source_path, []).append(edge)
    known_paths = {
        path
        for record in records
        for path in record.source_paths
    }
    result: list[tuple[CustomizationRecord, tuple[AssessmentGroup, ...]]] = []
    for record in records:
        verdict = portable_contract.update_write_verdict(
            record.source_paths[0],
            exists=record.kind is not CustomizationKind.DELETED_SHIPPED_FILE,
        )
        outgoing = tuple(
            edge
            for source in record.source_paths
            for edge in edges_by_source.get(source, ())
        )
        unresolved = any(
            edge.target.startswith(("unresolved:", "outside-vault:"))
            for edge in outgoing
        )
        if (
            record.live.model_readability in {"restricted", "excluded"}
            or unresolved
            or verdict.action == "deny"
        ):
            options = (AssessmentGroup.BLOCKED,)
        elif verdict.action == "unclassified-never-write":
            options = (AssessmentGroup.NEEDS_INTERPRETATION,)
        elif verdict.allowed:
            options = (AssessmentGroup.UPDATE_REPLACEABLE_LOCATION,)
        else:
            options = (AssessmentGroup.UPDATE_UNTOUCHED_LOCATION,)
        # Capsule evidence canonicalizes an unresolved inferred target to
        # ``unresolved:*``. A concrete inferred target was therefore known to
        # resolve at capture time. A proved concrete target can still have
        # been absent (for example a configured folder), and v0 capsules do
        # not store the original group alongside the record. The sealed
        # assessment digest disambiguates that one missing bit without any
        # live-vault read.
        ambiguous_proved_target = any(
            edge.confidence is ReferenceConfidence.PROVED
            and ":" not in edge.target
            and edge.target not in known_paths
            for edge in outgoing
        )
        if (
            ambiguous_proved_target
            and options != (AssessmentGroup.BLOCKED,)
        ):
            options = (*options, AssessmentGroup.BLOCKED)
        result.append((record, options))
    return tuple(result)


def _assessment_from_capsule(root: Path, capsule_id: str) -> tuple[Assessment, str]:
    if validate_capsule(root, capsule_id).status != "OK":
        raise StagingError("selected capsule integrity is not OK")
    capsule_relative = f"{CAPSULE_ROOT}/{capsule_id}"
    try:
        manifest = _manifest_from_bytes(
            _read_regular_beneath(
                root,
                f"{capsule_relative}/manifest.json",
                _MAX_JSON_BYTES,
            )
        )
        customizations = _strict_object(
            _read_regular_beneath(
                root,
                f"{capsule_relative}/evidence/customizations.json",
                _MAX_JSON_BYTES,
            ),
            context="customization evidence",
        )
        dependencies = _strict_object(
            _read_regular_beneath(
                root,
                f"{capsule_relative}/evidence/dependencies.json",
                _MAX_JSON_BYTES,
            ),
            context="dependency evidence",
        )
        exclusions = _strict_object(
            _read_regular_beneath(
                root,
                f"{capsule_relative}/evidence/exclusions.json",
                _MAX_JSON_BYTES,
            ),
            context="exclusion evidence",
        )
        environment = _strict_object(
            _read_regular_beneath(
                root,
                f"{capsule_relative}/evidence/environment.json",
                _MAX_JSON_BYTES,
            ),
            context="environment evidence",
        )
    except (CapsuleError, OSError) as error:
        raise StagingError("selected capsule evidence is unreadable") from error

    for section, name in (
        (customizations, "customization evidence"),
        (dependencies, "dependency evidence"),
    ):
        if frozenset(section) != frozenset({"schema_version", "items"}):
            raise StagingError(f"{name} has an invalid shape")
        if section["schema_version"] != 0:
            raise StagingError(f"{name} schema_version is unsupported")
    if frozenset(exclusions) != frozenset(
        {
            "schema_version",
            "items",
            "restricted_findings",
            "secret_archival_policy",
        }
    ) or exclusions["schema_version"] != 0:
        raise StagingError("exclusion evidence has an invalid shape")
    if (
        not isinstance(exclusions["restricted_findings"], list)
        or not isinstance(exclusions["secret_archival_policy"], str)
    ):
        raise StagingError("exclusion evidence metadata is invalid")
    if frozenset(environment) != frozenset(
        {
            "schema_version",
            "identity",
            "baseline_identity_state",
            "baseline_errors",
            "completeness",
            "verdict",
        }
    ) or environment["schema_version"] != 0:
        raise StagingError("environment evidence has an invalid shape")
    records = tuple(
        _record_from_dict(item)
        for item in _closed_list(customizations["items"], context="customization items")
    )
    edges = tuple(
        _edge_from_dict(item)
        for item in _closed_list(dependencies["items"], context="dependency items")
    )
    exclusion_items = _closed_list(exclusions.get("items"), context="exclusion items")
    identity = _closed_mapping(
        environment.get("identity"),
        keys=frozenset(
            {
                "release_version",
                "inventory_path_count",
                "customization_count",
                "edge_count",
            }
        ),
        context="capsule assessment identity",
    )
    try:
        assessment_identity = AssessmentIdentity(
            identity["release_version"],
            identity["inventory_path_count"],
            identity["customization_count"],
            identity["edge_count"],
        )
        baseline_errors = _strings(
            environment["baseline_errors"],
            context="baseline_errors",
        )
        assessment_exclusions = tuple(
            _exclusion_from_dict(item) for item in exclusion_items
        )
        group_options = _frozen_group_options(records, edges)
    except (KeyError, TypeError, ValueError) as error:
        raise StagingError("capsule evidence cannot rebuild an assessment") from error
    ambiguous_count = sum(len(options) > 1 for _record, options in group_options)
    if ambiguous_count > 16:
        raise StagingError("capsule evidence has too many ambiguous frozen groups")
    for selected in itertools.product(
        *(options for _record, options in group_options)
    ):
        groups = tuple(
            sorted(
                (
                    AssessmentAssignment(record.customization_id, group)
                    for (record, _options), group in zip(
                        group_options,
                        selected,
                        strict=True,
                    )
                ),
                key=lambda item: item.customization_id,
            )
        )
        try:
            assessment = Assessment(
                0,
                assessment_identity,
                environment["baseline_identity_state"],
                baseline_errors,
                (),
                records,
                edges,
                groups,
                assessment_exclusions,
                environment["completeness"],
                environment["verdict"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise StagingError(
                "capsule evidence cannot rebuild an assessment"
            ) from error
        if _sha256(assessment.canonical_assessment_bytes()) == manifest.assessment_digest:
            return assessment, manifest.assessment_digest
    raise StagingError("capsule evidence does not rebuild its assessment digest")


def _planned_files(candidate: RegenerationCandidate) -> tuple[PlannedStagedFile, ...]:
    prefix = STAGING_SUBDIR.format(proposal_id=candidate.proposal_id)
    return tuple(
        PlannedStagedFile(
            item.target_path,
            f"{prefix}/files/{item.sha256}",
            item.sha256,
            len(item.content),
        )
        for item in candidate.files
    )


def _validate_candidate_against_capsule(
    root: Path,
    capsule_id: str,
    candidate: RegenerationCandidate,
) -> None:
    if candidate.capsule_id != capsule_id:
        raise StagingError("candidate capsule id does not match selected capsule")
    assessment, evidence_digest = _assessment_from_capsule(root, capsule_id)
    if candidate.evidence_digest != evidence_digest:
        raise StagingError("candidate evidence digest does not match current capsule")
    validation = validate_regeneration_candidate(
        assessment,
        candidate,
        expected_capsule_id=capsule_id,
    )
    if not validation.accepted:
        raise StagingError("candidate validation failed: " + "; ".join(validation.errors))


def preview_staging(
    vault_root: Path,
    capsule_id: str,
    candidate: RegenerationCandidate,
) -> StagingPreview:
    """Build a deterministic private-staging plan without writing the vault."""
    if not isinstance(capsule_id, str) or CAPSULE_ID.fullmatch(capsule_id) is None:
        raise StagingError("capsule_id is not canonical")
    if type(candidate) is not RegenerationCandidate:
        raise TypeError("candidate must be RegenerationCandidate")
    if len(candidate.files) > _MAX_STAGED_FILES:
        raise StagingError("candidate exceeds the staged-file limit")
    if sum(len(item.content) for item in candidate.files) > _MAX_STAGED_BYTES:
        raise StagingError("candidate exceeds the private staging byte limit")
    root = Path(vault_root).resolve()
    _validate_candidate_against_capsule(root, capsule_id, candidate)
    files = _planned_files(candidate)
    unsigned = StagingPreview(
        0,
        capsule_id,
        candidate.proposal_id,
        candidate,
        files,
        "0" * 64,
    )
    digest = _sha256(unsigned.canonical_preview_bytes())
    return StagingPreview(
        0,
        capsule_id,
        candidate.proposal_id,
        candidate,
        files,
        digest,
    )


def _transaction_id() -> str:
    return time.strftime("%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:8]


def _event_bytes(
    event: MigrationEvent,
    **payload: str,
) -> bytes:
    return _canonical_json(
        {
            "schema_version": 0,
            "event": event.value,
            **payload,
        }
    )


def _staging_stop_seam(name: str) -> None:
    if os.environ.get("DEX_TX_TEST_STOP_AFTER") == name:
        os._exit(137)


def _append_event(
    path: Path,
    event: MigrationEvent,
    **payload: str,
) -> None:
    raw = _event_bytes(event, **payload)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise StagingError(f"staging journal is not a regular file: {path}")
        written = os.write(descriptor, raw)
        if written != len(raw):
            raise StagingError(f"short append to staging journal: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _secure_staging_directories(root: Path, staging_dir: Path) -> None:
    capsule_dir = staging_dir.parents[2]
    current = staging_dir
    directories: list[Path] = []
    while current != capsule_dir:
        directories.append(current)
        current = current.parent
    for directory in reversed(directories):
        descriptor = _open_directory_beneath(
            root,
            directory.relative_to(root).as_posix(),
        )
        try:
            os.fchmod(descriptor, 0o700)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    files_dir = staging_dir / "files"
    if files_dir.exists() and files_dir not in directories:
        descriptor = _open_directory_beneath(
            root,
            files_dir.relative_to(root).as_posix(),
        )
        try:
            os.fchmod(descriptor, 0o700)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def stage_candidate(
    vault_root: Path,
    preview: StagingPreview,
    preview_sha256: str,
) -> StagingReceipt:
    """Commit one candidate under its capsule without touching a live seam.

    This is an internal lifecycle primitive, not a consent adapter. A1 still
    requires its Doctor/CLI caller to collect genuine interactive consent;
    the reproducible preview digest below binds integrity and never consent.
    MCP/read-only surfaces must not expose this write primitive.
    """
    if type(preview) is not StagingPreview:
        raise TypeError("preview must be StagingPreview")
    recomputed = _sha256(preview.canonical_preview_bytes())
    if preview_sha256 != preview.preview_sha256 or preview_sha256 != recomputed:
        raise StagingError("staging preview digest mismatch")
    root = Path(vault_root).resolve()
    refreshed = preview_staging(root, preview.capsule_id, preview.candidate)
    if refreshed != preview:
        raise StagingError("staging preview drifted")
    prefix = f"{CAPSULE_ROOT}/{preview.capsule_id}/" + STAGING_SUBDIR.format(
        proposal_id=preview.proposal_id
    )
    staging_dir = root / prefix
    if staging_dir.exists() or staging_dir.is_symlink():
        raise StagingError(f"staging already exists: {preview.proposal_id}")

    transaction_id = _transaction_id()
    receipt = StagingReceipt(
        0,
        preview.capsule_id,
        preview.proposal_id,
        len(preview.candidate.files),
        sum(len(item.content) for item in preview.candidate.files),
        preview.preview_sha256,
        transaction_id,
    )
    proposed_journal = _event_bytes(MigrationEvent.REGENERATION_PROPOSED)
    materials: dict[str, bytes] = {
        f"{prefix}/manifest.json": _canonical_json(preview.candidate.to_dict()),
        f"{prefix}/journal.jsonl": proposed_journal,
        f"{prefix}/receipt.json": receipt.canonical_bytes(),
    }
    for item in preview.candidate.files:
        relative = f"{prefix}/files/{item.sha256}"
        existing = materials.setdefault(relative, item.content)
        if existing != item.content:
            raise StagingError(f"content-address collision for {item.sha256}")
    plan = [
        PlanEntry(relative, raw, mode=0o600)
        for relative, raw in sorted(materials.items())
    ]
    transaction = Transaction._begin_with_id(
        root,
        plan,
        allow_empty=False,
        operation="customization-migration",
        tx_id=transaction_id,
    )
    journal_path = staging_dir / "journal.jsonl"

    def finalize_staging() -> None:
        _validate_candidate_against_capsule(
            root,
            preview.capsule_id,
            preview.candidate,
        )
        _secure_staging_directories(root, staging_dir)
        _staging_stop_seam("staging-after-layout")
        _append_event(journal_path, MigrationEvent.REGENERATION_STAGED)
        _staging_stop_seam("staging-mid-finalize")
        _validate_candidate_against_capsule(
            root,
            preview.capsule_id,
            preview.candidate,
        )

    transaction.run(before_commit=finalize_staging)
    return receipt


def _event_records(raw: bytes) -> tuple[dict[str, object], ...]:
    if not raw.endswith(b"\n"):
        raise StagingError("staging journal has a torn final record")
    records: list[dict[str, object]] = []
    for line in raw.splitlines():
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StagingError("staging journal is malformed") from error
        if (
            not isinstance(record, dict)
            or record.get("schema_version") != 0
            or not isinstance(record.get("event"), str)
            or _canonical_json(record).rstrip(b"\n") != line
        ):
            raise StagingError("staging journal record is not canonical")
        keys = frozenset(record)
        if keys == _EVENT_KEYS:
            pass
        elif keys == _VERIFICATION_EVENT_KEYS:
            if (
                record["event"]
                not in {
                    MigrationEvent.VERIFICATION_PASSED.value,
                    MigrationEvent.VERIFICATION_BLOCKED.value,
                }
                or not isinstance(record["candidate_sha256"], str)
                or SHA256.fullmatch(record["candidate_sha256"]) is None
                or not isinstance(record["report_sha256"], str)
                or SHA256.fullmatch(record["report_sha256"]) is None
                or not isinstance(record["report_path"], str)
            ):
                raise StagingError(
                    "verification journal record is invalid"
                )
        else:
            raise StagingError("staging journal record has an invalid shape")
        records.append(record)
    return tuple(records)


def _read_event_records_beneath(
    root: Path,
    relative: str,
) -> tuple[dict[str, object], ...]:
    return _event_records(_read_regular_beneath(root, relative))


def _verification_binding_problems(
    root: Path,
    capsule_id: str,
    candidate: RegenerationCandidate,
    binding: dict[str, object],
) -> tuple[set[str], set[str]]:
    missing: set[str] = set()
    mismatches: set[str] = set()
    report_relative = (
        f"{CAPSULE_ROOT}/{capsule_id}/verification/"
        f"{candidate.proposal_id}.json"
    )
    if (
        binding.get("report_path") != report_relative
        or binding.get("candidate_sha256") != candidate.candidate_sha256
    ):
        mismatches.add("verification/report-binding")
        return missing, mismatches
    verification_relative = f"{CAPSULE_ROOT}/{capsule_id}/verification"
    try:
        directory = _open_directory_beneath(root, verification_relative)
    except FileNotFoundError:
        missing.add("verification/report-missing")
        return missing, mismatches
    except OSError:
        mismatches.add("verification/report-mode")
        return missing, mismatches
    try:
        directory_metadata = os.fstat(directory)
        if stat.S_IMODE(directory_metadata.st_mode) != 0o700:
            mismatches.add("verification/report-mode")
        try:
            descriptor = os.open(
                f"{candidate.proposal_id}.json",
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory,
            )
        except FileNotFoundError:
            missing.add("verification/report-missing")
            return missing, mismatches
        except OSError:
            mismatches.add("verification/report-mode")
            return missing, mismatches
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_size > _MAX_JSON_BYTES
            ):
                mismatches.add("verification/report-mode")
            chunks: list[bytes] = []
            remaining = _MAX_JSON_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            report_raw = b"".join(chunks)
            if len(report_raw) > _MAX_JSON_BYTES:
                mismatches.add("verification/report-schema")
                return missing, mismatches
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)
    if _sha256(report_raw) != binding.get("report_sha256"):
        mismatches.add("verification/report-digest")
        return missing, mismatches
    try:
        from core.customization_migration.verification import (
            VerificationError,
            validate_persisted_verification_report,
        )

        validate_persisted_verification_report(
            report_raw,
            candidate,
            binding["event"],
        )
    except (KeyError, TypeError, ValueError, VerificationError):
        mismatches.add("verification/report-schema")
    return missing, mismatches


def read_staging_status(vault_root: Path, capsule_id: str) -> StagingStatus:
    """Project each bounded proposal journal; malformed evidence never raises."""
    if not isinstance(capsule_id, str) or CAPSULE_ID.fullmatch(capsule_id) is None:
        raise StagingError("capsule_id is not canonical")
    root = Path(vault_root).resolve()
    candidates_dir = root / CAPSULE_ROOT / capsule_id / "candidates"
    if not candidates_dir.exists():
        return StagingStatus(capsule_id, ())
    if candidates_dir.is_symlink() or not candidates_dir.is_dir():
        return StagingStatus(
            capsule_id,
            (ProposalStagingStatus("<candidates>", MigrationState.RECOVERY_REQUIRED),),
        )
    entries: list[Path] = []
    with os.scandir(candidates_dir) as iterator:
        for entry in iterator:
            entries.append(Path(entry.path))
            if len(entries) > _MAX_PROPOSALS:
                break
    truncated = len(entries) > _MAX_PROPOSALS
    proposals: list[ProposalStagingStatus] = []
    for proposal_dir in sorted(entries[:_MAX_PROPOSALS], key=lambda item: item.name):
        state = MigrationState.RECOVERY_REQUIRED
        try:
            if proposal_dir.is_symlink() or not proposal_dir.is_dir():
                raise StagingError("proposal entry is unsafe")
            proposal_id = proposal_dir.name
            staging_relative = (
                f"{CAPSULE_ROOT}/{capsule_id}/"
                + STAGING_SUBDIR.format(proposal_id=proposal_id)
            )
            capsule_records = _read_event_records_beneath(
                root,
                f"{CAPSULE_ROOT}/{capsule_id}/journal.jsonl",
            )
            capsule_events = tuple(
                record["event"] for record in capsule_records
            )
            if project_state(capsule_events) is not MigrationState.CAPSULE_CREATED:
                raise StagingError("capsule state is not capsule-created")
            candidate, _receipt, _staging = load_staged_candidate(
                root,
                capsule_id,
                proposal_id,
            )
            _validate_candidate_against_capsule(
                root,
                capsule_id,
                candidate,
            )
            proposal_records = _read_event_records_beneath(
                root,
                f"{staging_relative}/journal.jsonl",
            )
            proposal_events = tuple(
                record["event"] for record in proposal_records
            )
            if len(proposal_records) == 3:
                binding = proposal_records[2]
                report_missing, report_mismatches = (
                    _verification_binding_problems(
                        root,
                        capsule_id,
                        candidate,
                        binding,
                    )
                )
                if report_missing or report_mismatches:
                    raise StagingError(
                        "verification report seal is incomplete"
                    )
            state = project_state(
                (
                    *capsule_events,
                    MigrationEvent.TARGET_VERIFIED.value,
                    *proposal_events,
                )
            )
        except (OSError, StagingError):
            pass
        proposals.append(ProposalStagingStatus(proposal_dir.name, state))
    return StagingStatus(capsule_id, tuple(proposals), truncated)


def _candidate_file_from_dict(value: object) -> CandidateFile:
    item = _closed_mapping(
        value,
        keys=frozenset({"target_path", "content_base64", "sha256", "customization_ids"}),
        context="candidate file",
    )
    encoded = item["content_base64"]
    if not isinstance(encoded, str):
        raise StagingError("candidate content_base64 must be text")
    try:
        content = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as error:
        raise StagingError("candidate content_base64 is invalid") from error
    return CandidateFile(
        item["target_path"],
        content,
        item["sha256"],
        _strings(item["customization_ids"], context="candidate customization_ids"),
    )


def _contract_from_dict(value: object) -> BehaviouralContract:
    item = _closed_mapping(
        value,
        keys=frozenset(
            {
                "contract_id",
                "customization_id",
                "statement",
                "provenance",
                "verification_class",
            }
        ),
        context="candidate behaviour contract",
    )
    return BehaviouralContract(
        item["contract_id"],
        item["customization_id"],
        item["statement"],
        ContractProvenance(item["provenance"]),
        VerificationClass(item["verification_class"]),
    )


def _candidate_from_dict(value: object) -> RegenerationCandidate:
    item = _closed_mapping(
        value,
        keys=frozenset(
            {
                "schema_version",
                "proposal_id",
                "capsule_id",
                "evidence_digest",
                "dispositions",
                "files",
                "dependency_remappings",
                "behaviour_contracts",
                "declared_requirements",
                "confidence",
                "unresolved_questions",
                "shim_expiries",
                "candidate_sha256",
            }
        ),
        context="staging manifest",
    )
    try:
        candidate = RegenerationCandidate(
            item["schema_version"],
            item["proposal_id"],
            item["capsule_id"],
            item["evidence_digest"],
            tuple(
                DispositionPlanItem(
                    part["customization_id"],
                    Disposition(part["disposition"]),
                    part["assessment_digest"],
                    part["native_witness"],
                    _strings(part["evidence_edge_ids"], context="evidence_edge_ids"),
                    _strings(
                        part["behaviour_contract_ids"],
                        context="behaviour_contract_ids",
                    ),
                )
                for part in (
                    _closed_mapping(
                        value,
                        keys=frozenset(
                            {
                                "customization_id",
                                "disposition",
                                "assessment_digest",
                                "native_witness",
                                "evidence_edge_ids",
                                "behaviour_contract_ids",
                            }
                        ),
                        context="candidate disposition",
                    )
                    for value in _closed_list(
                        item["dispositions"],
                        context="candidate dispositions",
                    )
                )
            ),
            tuple(
                _candidate_file_from_dict(part)
                for part in _closed_list(item["files"], context="candidate files")
            ),
            tuple(
                DependencyRemapping(
                    part["edge_id"],
                    DependencyResolution(part["resolution"]),
                    part["target_path"],
                )
                for part in (
                    _closed_mapping(
                        value,
                        keys=frozenset({"edge_id", "resolution", "target_path"}),
                        context="candidate dependency remapping",
                    )
                    for value in _closed_list(
                        item["dependency_remappings"],
                        context="candidate dependency remappings",
                    )
                )
            ),
            tuple(
                _contract_from_dict(part)
                for part in _closed_list(
                    item["behaviour_contracts"],
                    context="candidate behaviour contracts",
                )
            ),
            tuple(
                DeclaredRequirement(
                    RequirementKind(part["kind"]),
                    part["description"],
                    _strings(
                        part["customization_ids"],
                        context="requirement customization_ids",
                    ),
                )
                for part in (
                    _closed_mapping(
                        value,
                        keys=frozenset(
                            {"kind", "description", "customization_ids"}
                        ),
                        context="candidate declared requirement",
                    )
                    for value in _closed_list(
                        item["declared_requirements"],
                        context="candidate declared requirements",
                    )
                )
            ),
            item["confidence"],
            _strings(
                item["unresolved_questions"],
                context="candidate unresolved_questions",
            ),
            tuple(
                ShimExpiry(
                    part["customization_id"],
                    part["review_release"],
                    part["removal_condition"],
                )
                for part in (
                    _closed_mapping(
                        value,
                        keys=frozenset(
                            {
                                "customization_id",
                                "review_release",
                                "removal_condition",
                            }
                        ),
                        context="candidate shim expiry",
                    )
                    for value in _closed_list(
                        item["shim_expiries"],
                        context="candidate shim expiries",
                    )
                )
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise StagingError("staging manifest candidate is invalid") from error
    if item["candidate_sha256"] != candidate.candidate_sha256:
        raise StagingError("candidate_sha256 does not bind the staging manifest")
    return candidate


def load_staged_candidate(
    vault_root: Path,
    capsule_id: str,
    proposal_id: str,
) -> tuple[RegenerationCandidate, StagingReceipt, Path]:
    """Load canonical, receipt-bound staging evidence for verification."""
    if not isinstance(capsule_id, str) or CAPSULE_ID.fullmatch(capsule_id) is None:
        raise StagingError("capsule_id is not canonical")
    if not isinstance(proposal_id, str) or PROPOSAL_ID.fullmatch(proposal_id) is None:
        raise StagingError("proposal_id is not canonical")
    root = Path(vault_root).resolve()
    staging_relative = (
        f"{CAPSULE_ROOT}/{capsule_id}/"
        + STAGING_SUBDIR.format(proposal_id=proposal_id)
    )
    staging = root / staging_relative
    manifest = _strict_object(
        _read_regular_beneath(
            root,
            f"{staging_relative}/manifest.json",
        ),
        context="staging manifest",
    )
    candidate = _candidate_from_dict(manifest)
    receipt_value = _strict_object(
        _read_regular_beneath(
            root,
            f"{staging_relative}/receipt.json",
        ),
        context="staging receipt",
    )
    try:
        receipt = StagingReceipt(
            receipt_value["schema_version"],
            receipt_value["capsule_id"],
            receipt_value["proposal_id"],
            receipt_value["staged_file_count"],
            receipt_value["staged_byte_count"],
            receipt_value["staging_digest"],
            receipt_value["transaction_id"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise StagingError("staging receipt is invalid") from error
    if receipt.canonical_bytes() != _canonical_json(receipt_value):
        raise StagingError("staging receipt is not canonical")
    if (
        candidate.capsule_id != capsule_id
        or candidate.proposal_id != proposal_id
        or receipt.capsule_id != capsule_id
        or receipt.proposal_id != proposal_id
        or receipt.staged_file_count != len(candidate.files)
        or receipt.staged_byte_count != sum(len(item.content) for item in candidate.files)
    ):
        raise StagingError("staging identity or receipt does not match")
    return candidate, receipt, staging


def validate_staging(
    vault_root: Path,
    capsule_id: str,
    proposal_id: str,
) -> StagingValidation:
    """Recompute canonical manifest and blob integrity without executing bytes."""
    root = Path(vault_root).resolve()
    staging_relative = (
        f"{CAPSULE_ROOT}/{capsule_id}/"
        + STAGING_SUBDIR.format(proposal_id=proposal_id)
    )
    staging = root / staging_relative
    try:
        top_entries = _scan_directory_beneath(
            root,
            staging_relative,
            limit=5,
        )
    except FileNotFoundError:
        return StagingValidation("UNKNOWN", ())
    except (OSError, StagingError):
        return StagingValidation("BROKEN", ("staging",))

    missing: set[str] = set()
    mismatches: set[str] = set()
    required_top = {"manifest.json", "journal.jsonl", "receipt.json"}
    for name in required_top - top_entries.keys():
        missing.add(name)
    for name in top_entries.keys() - {
        *required_top,
        "files",
    }:
        mismatches.add(name)
    for name in required_top & top_entries.keys():
        metadata = top_entries[name]
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            mismatches.add(name + ":mode-or-type")
    if "files" in top_entries and (
        not stat.S_ISDIR(top_entries["files"].st_mode)
        or stat.S_IMODE(top_entries["files"].st_mode) != 0o700
    ):
        mismatches.add("files:mode-or-type")
    for directory_relative in (
        f"{CAPSULE_ROOT}/{capsule_id}/candidates",
        f"{CAPSULE_ROOT}/{capsule_id}/candidates/{proposal_id}",
        staging_relative,
    ):
        try:
            descriptor = _open_directory_beneath(root, directory_relative)
            metadata = os.fstat(descriptor)
            os.close(descriptor)
            if stat.S_IMODE(metadata.st_mode) != 0o700:
                mismatches.add(
                    directory_relative.removeprefix(
                        f"{CAPSULE_ROOT}/{capsule_id}/"
                    )
                    + ":mode"
                )
        except OSError:
            mismatches.add("staging:unsafe-parent")
    if missing:
        return StagingValidation("UNKNOWN", tuple(sorted(missing)))
    if mismatches:
        return StagingValidation("BROKEN", tuple(sorted(mismatches)))

    try:
        candidate, receipt, staging = load_staged_candidate(
            root,
            capsule_id,
            proposal_id,
        )
    except (OSError, StagingError):
        return StagingValidation("BROKEN", ("manifest.json",))

    manifest_raw = _read_regular_beneath(
        root,
        f"{staging_relative}/manifest.json",
    )
    preview = StagingPreview(
        0,
        capsule_id,
        proposal_id,
        candidate,
        _planned_files(candidate),
        receipt.staging_digest,
    )
    if _sha256(preview.canonical_preview_bytes()) != receipt.staging_digest:
        mismatches.add("receipt.json:staging-digest")
    if _canonical_json(candidate.to_dict()) != manifest_raw:
        mismatches.add("manifest.json")
    try:
        records = _read_event_records_beneath(
            root,
            f"{staging_relative}/journal.jsonl",
        )
    except (OSError, StagingError):
        mismatches.add("journal.jsonl")
        records = ()
    events = tuple(record["event"] for record in records)
    if events == (MigrationEvent.REGENERATION_PROPOSED.value,):
        missing.add("journal.jsonl:incomplete")
    elif (
        len(events) not in {2, 3}
        or events[:2]
        != (
            MigrationEvent.REGENERATION_PROPOSED.value,
            MigrationEvent.REGENERATION_STAGED.value,
        )
        or (
            len(events) == 3
            and events[2]
            not in {
                MigrationEvent.VERIFICATION_PASSED.value,
                MigrationEvent.VERIFICATION_BLOCKED.value,
            }
        )
    ):
        mismatches.add("journal.jsonl")
    if len(records) == 3:
        report_missing, report_mismatches = _verification_binding_problems(
            root,
            capsule_id,
            candidate,
            records[2],
        )
        missing.update(report_missing)
        mismatches.update(report_mismatches)

    expected_names = {item.sha256 for item in candidate.files}
    if not expected_names:
        if "files" in top_entries:
            mismatches.add("files")
        actual_entries: dict[str, os.stat_result] = {}
    else:
        if "files" not in top_entries:
            missing.add("files")
            actual_entries = {}
        else:
            try:
                actual_entries = _scan_directory_beneath(
                    root,
                    f"{staging_relative}/files",
                    limit=len(expected_names) + 1,
                )
            except (OSError, StagingError):
                mismatches.add("files:entry-bound-or-unsafe")
                actual_entries = {}
    actual_names = set(actual_entries)
    for name in sorted(expected_names - actual_names):
        missing.add(f"files/{name}")
    for name in sorted(actual_names - expected_names):
        mismatches.add(f"files/{name}")
    for item in candidate.files:
        if item.sha256 not in actual_names:
            continue
        relative = f"files/{item.sha256}"
        try:
            metadata = actual_entries[item.sha256]
            raw = _read_regular_beneath(
                root,
                f"{staging_relative}/{relative}",
                _MAX_STAGED_BYTES,
            )
            if _sha256(raw) != item.sha256 or raw != item.content:
                mismatches.add(relative)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                mismatches.add(relative + ":mode")
        except (OSError, StagingError):
            mismatches.add(relative)
    if missing:
        return StagingValidation("UNKNOWN", tuple(sorted(missing)))
    if mismatches:
        return StagingValidation("BROKEN", tuple(sorted(mismatches)))
    return StagingValidation("OK", ())


__all__ = [
    "STAGING_SUBDIR",
    "PlannedStagedFile",
    "ProposalStagingStatus",
    "StagingError",
    "StagingPreview",
    "StagingReceipt",
    "StagingStatus",
    "StagingValidation",
    "load_staged_candidate",
    "preview_staging",
    "read_staging_status",
    "stage_candidate",
    "validate_staging",
]
