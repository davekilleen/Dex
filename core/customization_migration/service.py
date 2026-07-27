"""Deterministic customization-migration service shared by human and MCP adapters."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path

from core.customization_migration.capsule_model import (
    CAPSULE_ID,
    EVIDENCE_SECTIONS_V0,
)
from core.customization_migration.inventory import discover
from core.customization_migration.model import Assessment, AssessmentIdentity

_MAX_EVIDENCE_BYTES = 1024 * 1024
_MAX_CANDIDATE_BYTES = 16 * 1024 * 1024


class MigrationServiceError(RuntimeError):
    """A stable adapter-safe refusal with no ambient filesystem details."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_json_bytes(value: object) -> bytes:
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


def resolve_vault_root(value: str | Path | None) -> Path:
    if value is None or not str(value).strip():
        raise MigrationServiceError("invalid-vault-root", "VAULT_PATH is required.")
    supplied = Path(value).expanduser()
    try:
        metadata = supplied.lstat()
    except OSError as error:
        raise MigrationServiceError(
            "invalid-vault-root", "The configured vault does not exist."
        ) from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise MigrationServiceError(
            "invalid-vault-root", "The configured vault must be a real directory."
        )
    return supplied.resolve(strict=True)


def assess(vault_root: Path) -> Assessment:
    """Assess one vault entirely in memory; never cache or mutate it."""
    discovery = discover(Path(vault_root))
    inventory = discovery.inventory
    folder_map_state = getattr(
        getattr(inventory, "folder_map", None),
        "state",
        "DEFAULT",
    )
    walk_truncated = (
        "filesystem inventory reached its configured entry bound"
        in inventory.errors
    )
    reasons: set[str] = set()
    if inventory.baseline.identity_state != "VERIFIED":
        reasons.add("baseline-not-verified")
    if not inventory.complete:
        reasons.add("inventory-incomplete")
    if folder_map_state == "UNKNOWN":
        reasons.add("folder-map-unknown")
    if walk_truncated:
        reasons.add("walk-truncated")
    if any(
        exclusion.reason != "embedded-secret"
        for exclusion in discovery.exclusions
    ):
        reasons.add("assessment-exclusions")
    if inventory.errors and inventory.baseline.identity_state == "VERIFIED":
        reasons.add("inventory-errors")
    proved_complete = (
        inventory.baseline.identity_state == "VERIFIED"
        and inventory.complete
        and folder_map_state != "UNKNOWN"
        and not walk_truncated
        and discovery.complete
    )
    if not proved_complete and not reasons:
        reasons.add("inventory-incomplete")
    completeness = "OK" if proved_complete else "UNKNOWN"
    public_records = discovery.records if completeness == "OK" else ()
    public_edges = discovery.edges if completeness == "OK" else ()
    public_groups = discovery.groups if completeness == "OK" else ()
    return Assessment(
        0,
        AssessmentIdentity(
            inventory.baseline.release_version,
            len(inventory.entries) if completeness == "OK" else 0,
            len(public_records),
            len(public_edges),
        ),
        inventory.baseline.identity_state,
        inventory.baseline.errors,
        tuple(sorted(reasons)),
        public_records,
        public_edges,
        public_groups,
        discovery.exclusions,
        completeness,
        "OK" if completeness == "OK" else "UNKNOWN",
    )


def assessment_to_dict(assessment: Assessment) -> dict[str, object]:
    if not isinstance(assessment, Assessment):
        raise TypeError("assessment must be Assessment")
    return assessment.to_dict()


def assess_to_dict(vault_root: Path) -> dict[str, object]:
    return assessment_to_dict(assess(resolve_vault_root(vault_root)))


def _confirmation_preview(vault_root: Path):
    from core.customization_migration.capsule import preview_capsule

    root = resolve_vault_root(vault_root)
    assessment = assess(root)
    raw = assessment.canonical_assessment_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    capsule_id = "cap-" + digest[:16]
    created_epoch_seconds = max(1, int(digest[16:24], 16))
    return preview_capsule(
        root,
        clock=lambda: created_epoch_seconds,
        capsule_id=capsule_id,
    )


def preview_to_dict(vault_root: Path) -> dict[str, object]:
    return _confirmation_preview(vault_root).to_dict()


def create_confirmed_capsule(vault_root: Path, preview_sha256: str):
    from core.customization_migration.capsule import create_capsule

    root = resolve_vault_root(vault_root)
    preview = _confirmation_preview(root)
    return create_capsule(root, preview, preview_sha256)


def load_regeneration_candidate(candidate_path: str | Path):
    """Read one canonical, schema-closed regeneration candidate."""
    from core.customization_migration.staging import (
        StagingError,
        _candidate_from_dict,
    )

    try:
        raw = _read_regular_file(
            Path(candidate_path).expanduser(),
            limit=_MAX_CANDIDATE_BYTES,
        )
        value = json.loads(raw.decode("utf-8"))
        if canonical_json_bytes(value) != raw:
            raise ValueError("candidate JSON is not canonical")
        return _candidate_from_dict(value)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        MigrationServiceError,
        StagingError,
        ValueError,
    ) as error:
        raise MigrationServiceError(
            "invalid-candidate",
            "The regeneration candidate is not canonical and valid.",
        ) from error


def preview_staging_to_dict(vault_root: Path, candidate) -> dict[str, object]:
    from core.customization_migration.staging import StagingError, preview_staging

    root = resolve_vault_root(vault_root)
    try:
        return preview_staging(root, candidate.capsule_id, candidate).to_dict()
    except (AttributeError, OSError, StagingError, TypeError, ValueError) as error:
        raise MigrationServiceError(
            "staging-refused",
            "The regeneration candidate could not be previewed safely.",
        ) from error


def stage_confirmed_candidate(
    vault_root: Path,
    candidate,
    preview_sha256: str,
):
    from core.customization_migration.staging import (
        StagingError,
        preview_staging,
        stage_candidate,
    )

    root = resolve_vault_root(vault_root)
    try:
        preview = preview_staging(root, candidate.capsule_id, candidate)
        return stage_candidate(root, preview, preview_sha256)
    except (AttributeError, OSError, StagingError, TypeError, ValueError) as error:
        raise MigrationServiceError(
            "staging-refused",
            "The regeneration candidate was not staged.",
        ) from error


def verify_staging_to_dict(
    vault_root: Path,
    capsule_id: str,
    proposal_id: str,
) -> dict[str, object]:
    from core.customization_migration.staging import StagingError
    from core.customization_migration.verification import (
        VerificationError,
        verify_staging,
        write_verification_report,
    )

    root = resolve_vault_root(vault_root)
    try:
        report = verify_staging(root, capsule_id, proposal_id)
        receipt = write_verification_report(
            root,
            capsule_id,
            proposal_id,
            report,
        )
        return {"report": report.to_dict(), "receipt": receipt.to_dict()}
    except (OSError, StagingError, VerificationError, TypeError, ValueError) as error:
        raise MigrationServiceError(
            "verification-refused",
            "The staged regeneration could not be verified and sealed.",
        ) from error


def staging_status_to_dict(
    vault_root: Path,
    capsule_id: str,
) -> dict[str, object]:
    from core.customization_migration.capsule import CAPSULE_ROOT
    from core.customization_migration.staging import StagingError, read_staging_status
    from core.customization_migration.state import MigrationState
    from core.customization_migration.verification import (
        VerificationError,
        verification_report_from_bytes,
    )

    root = resolve_vault_root(vault_root)
    try:
        status = read_staging_status(root, capsule_id)
    except (OSError, StagingError, TypeError, ValueError) as error:
        raise MigrationServiceError(
            "staging-status-unreadable",
            "The staging status could not be read safely.",
        ) from error
    proposals: list[dict[str, object]] = []
    for item in status.proposals:
        verdict = "UNKNOWN"
        if item.state is not MigrationState.RECOVERY_REQUIRED:
            report_path = (
                root
                / CAPSULE_ROOT
                / capsule_id
                / "verification"
                / f"{item.proposal_id}.json"
            )
            try:
                report = verification_report_from_bytes(
                    _read_regular_file(report_path)
                )
                if (
                    report.capsule_id == capsule_id
                    and report.proposal_id == item.proposal_id
                ):
                    verdict = report.verdict
            except (OSError, VerificationError):
                pass
        proposals.append(
            {
                "proposal_id": item.proposal_id,
                "state": item.state.value,
                "verification_verdict": verdict,
            }
        )
    return {
        "capsule_id": status.capsule_id,
        "proposals": proposals,
        "truncated": status.truncated,
    }


def preview_activation_to_dict(
    vault_root: Path,
    capsule_id: str,
    proposal_id: str,
) -> dict[str, object]:
    from core.customization_migration.activation import ActivationError, preview_activation
    from core.customization_migration.staging import StagingError, load_staged_candidate
    from core.customization_migration.verification import VerificationError

    root = resolve_vault_root(vault_root)
    try:
        candidate, _receipt, _staging = load_staged_candidate(
            root,
            capsule_id,
            proposal_id,
        )
        result = preview_activation(root, capsule_id, proposal_id).to_dict()
        if candidate.candidate_sha256 != result["candidate_sha256"]:
            raise ActivationError(
                "activation preview candidate changed while it was being read"
            )
        result["dispositions"] = [
            item.to_dict() for item in candidate.dispositions
        ]
        return result
    except (
        OSError,
        ActivationError,
        StagingError,
        VerificationError,
        TypeError,
        ValueError,
    ) as error:
        raise MigrationServiceError(
            "activation-refused",
            "The activation could not be previewed safely.",
        ) from error


def activate_confirmed(
    vault_root: Path,
    capsule_id: str,
    proposal_id: str,
    approval_token: str,
):
    from core.customization_migration.activation import (
        ActivationError,
        activate,
        preview_activation,
    )
    from core.customization_migration.staging import StagingError
    from core.customization_migration.verification import VerificationError

    root = resolve_vault_root(vault_root)
    try:
        preview = preview_activation(root, capsule_id, proposal_id)
        return activate(root, preview, approval_token)
    except (
        OSError,
        ActivationError,
        StagingError,
        VerificationError,
        TypeError,
        ValueError,
    ) as error:
        raise MigrationServiceError(
            "activation-refused",
            "The verified regeneration was not activated.",
        ) from error


def _persisted_activation_receipt(root: Path, capsule_id: str):
    from core.customization_migration.activation import _load_activation_receipt

    return _load_activation_receipt(root, capsule_id)


def _rewind_preview_to_dict(preview) -> dict[str, object]:
    return {
        "schema_version": preview.schema_version,
        "capsule_id": preview.capsule_id,
        "proposal_id": preview.proposal_id,
        "activation_transaction_id": preview.activation_transaction_id,
        "status": preview.status,
        "reason": preview.reason,
        "files": [item.to_dict() for item in preview.files],
        "acknowledgement_token": preview.acknowledgement_token,
    }


def preview_rewind_to_dict(
    vault_root: Path,
    capsule_id: str,
) -> dict[str, object]:
    from core.customization_migration.activation import ActivationError, preview_rewind
    from core.customization_migration.staging import StagingError

    root = resolve_vault_root(vault_root)
    try:
        receipt = _persisted_activation_receipt(root, capsule_id)
        return _rewind_preview_to_dict(preview_rewind(root, receipt))
    except (OSError, ActivationError, StagingError, TypeError, ValueError) as error:
        raise MigrationServiceError(
            "rewind-refused",
            "The activation could not be previewed for rewind.",
        ) from error


def rewind_acknowledged(
    vault_root: Path,
    capsule_id: str,
    acknowledgement_token: str,
):
    from core.customization_migration.activation import ActivationError, rewind
    from core.customization_migration.staging import StagingError

    root = resolve_vault_root(vault_root)
    try:
        receipt = _persisted_activation_receipt(root, capsule_id)
        return rewind(root, receipt, acknowledgement_token)
    except (OSError, ActivationError, StagingError, TypeError, ValueError) as error:
        raise MigrationServiceError(
            "rewind-refused",
            "The activation was not rewound.",
        ) from error


def activation_status_to_dict(
    vault_root: Path,
    capsule_id: str,
) -> dict[str, object]:
    from core.customization_migration.activation import (
        ActivationError,
        preview_rewind,
        read_activation_status,
    )
    from core.customization_migration.capsule import CAPSULE_ROOT
    from core.customization_migration.staging import StagingError
    from core.customization_migration.state import MigrationState

    root = resolve_vault_root(vault_root)
    try:
        status = read_activation_status(root, capsule_id)
    except (OSError, ActivationError, StagingError, TypeError, ValueError) as error:
        raise MigrationServiceError(
            "activation-status-unreadable",
            "The activation status could not be read safely.",
        ) from error
    receipt_path = (
        root
        / CAPSULE_ROOT
        / capsule_id
        / "receipts"
        / "activation.json"
    )
    receipt_present = receipt_path.exists() or receipt_path.is_symlink()
    rewindable = False
    if status.state is MigrationState.ACTIVATED:
        try:
            receipt = _persisted_activation_receipt(root, capsule_id)
            preview = preview_rewind(root, receipt)
            rewindable = (
                preview.status == "OK"
                and preview.acknowledgement_token is not None
            )
        except (OSError, ActivationError, StagingError, TypeError, ValueError):
            pass
    return {
        "capsule_id": status.capsule_id,
        "proposal_id": status.proposal_id,
        "state": status.state.value,
        "reason": status.reason,
        "activation_receipt_present": receipt_present,
        "rewindable": rewindable,
    }


def abandon_existing_capsule(vault_root: Path, capsule_id: str) -> None:
    from core.customization_migration.capsule import abandon_capsule

    abandon_capsule(resolve_vault_root(vault_root), capsule_id)


def migration_status_to_dict(vault_root: Path) -> dict[str, object]:
    from core.customization_migration.capsule import (
        read_capsule_status,
        validate_capsule,
    )

    root = resolve_vault_root(vault_root)
    status = read_capsule_status(root)
    capsules = []
    for item in status.capsules:
        if CAPSULE_ID.fullmatch(item.capsule_id) is None:
            validation_payload = {
                "status": "UNKNOWN",
                "mismatches": ["capsule-entry"],
            }
        else:
            validation = validate_capsule(root, item.capsule_id)
            validation_payload = {
                "status": validation.status,
                "mismatches": list(validation.mismatches),
            }
        capsules.append(
            {
                "capsule_id": item.capsule_id,
                "state": item.state.value,
                "validation": validation_payload,
            }
        )
        if CAPSULE_ID.fullmatch(item.capsule_id) is not None:
            try:
                staging = staging_status_to_dict(root, item.capsule_id)
                activation = activation_status_to_dict(root, item.capsule_id)
            except MigrationServiceError:
                staging = {
                    "capsule_id": item.capsule_id,
                    "proposals": [],
                    "truncated": False,
                }
                activation = {
                    "capsule_id": item.capsule_id,
                    "proposal_id": None,
                    "state": "recovery-required",
                    "reason": "status-unreadable",
                    "activation_receipt_present": False,
                    "rewindable": False,
                }
            verification_verdicts = {
                "OK": 0,
                "BLOCKED": 0,
                "UNKNOWN": 0,
            }
            for proposal in staging["proposals"]:
                verdict = proposal["verification_verdict"]
                if verdict not in verification_verdicts:
                    verdict = "UNKNOWN"
                verification_verdicts[verdict] += 1
            capsules[-1].update(
                {
                    "staging": staging,
                    "verification_verdicts": verification_verdicts,
                    "pending_rebuild": (
                        item.state.value == "capsule-created"
                        and activation["state"] not in {"activated", "rewound"}
                    ),
                    "activation": activation,
                    "activation_receipt_present": activation[
                        "activation_receipt_present"
                    ],
                    "rewindable": activation["rewindable"],
                }
            )
    return {"capsules": capsules, "truncated": status.truncated}


def _read_regular_file(path: Path, *, limit: int = _MAX_EVIDENCE_BYTES) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise MigrationServiceError(
                "invalid-capsule", "Capsule evidence is not a bounded regular file."
            )
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > limit:
            raise MigrationServiceError(
                "invalid-capsule", "Capsule evidence exceeds the read limit."
            )
        return raw
    finally:
        os.close(descriptor)


def read_section_records(
    vault_root: Path,
    capsule_id: str,
    section: str,
) -> tuple[list[object], str]:
    from core.customization_migration.capsule import CAPSULE_ROOT, validate_capsule

    if not isinstance(capsule_id, str) or CAPSULE_ID.fullmatch(capsule_id) is None:
        raise MigrationServiceError(
            "malformed-arguments", "capsule_id is not canonical."
        )
    if section not in EVIDENCE_SECTIONS_V0:
        raise MigrationServiceError("invalid-section", "section is not supported.")
    root = resolve_vault_root(vault_root)
    capsule_dir = root / CAPSULE_ROOT / capsule_id
    if not capsule_dir.exists():
        raise MigrationServiceError("unknown-capsule", "The capsule does not exist.")
    for directory in (capsule_dir, capsule_dir / "evidence"):
        try:
            metadata = directory.lstat()
        except OSError as error:
            raise MigrationServiceError(
                "invalid-capsule", "Capsule evidence is incomplete."
            ) from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise MigrationServiceError(
                "invalid-capsule", "Capsule evidence is not a real directory."
            )
    if validate_capsule(root, capsule_id).status != "OK":
        raise MigrationServiceError(
            "invalid-capsule", "Capsule validation did not pass."
        )
    try:
        payload = json.loads(
            _read_regular_file(capsule_dir / "evidence" / f"{section}.json")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MigrationServiceError(
            "invalid-capsule", "Capsule evidence could not be read."
        ) from error
    if not isinstance(payload, Mapping):
        raise MigrationServiceError("invalid-capsule", "Capsule evidence is malformed.")
    items = payload.get("items")
    if isinstance(items, list):
        records: list[object] = list(items)
        if section == "exclusions":
            restricted = payload.get("restricted_findings", [])
            if isinstance(restricted, list):
                records.extend(
                    {"record_type": "restricted-finding", "value": item}
                    for item in restricted
                )
            records.append(
                {
                    "record_type": "secret-archival-policy",
                    "value": payload.get("secret_archival_policy"),
                }
            )
    else:
        records = [dict(payload)]
    return records, hashlib.sha256(canonical_json_bytes(records)).hexdigest()


__all__ = [
    "MigrationServiceError",
    "activate_confirmed",
    "activation_status_to_dict",
    "abandon_existing_capsule",
    "assess",
    "assessment_to_dict",
    "assess_to_dict",
    "canonical_json_bytes",
    "create_confirmed_capsule",
    "load_regeneration_candidate",
    "migration_status_to_dict",
    "preview_activation_to_dict",
    "preview_rewind_to_dict",
    "preview_staging_to_dict",
    "preview_to_dict",
    "read_section_records",
    "resolve_vault_root",
    "rewind_acknowledged",
    "stage_confirmed_candidate",
    "staging_status_to_dict",
    "verify_staging_to_dict",
]
