"""Closed, write-free validation for regeneration proposals.

This module deliberately accepts *proposals*, not file-system authority.  A
candidate can be complete, deterministic, and ready for staging without
granting the model (or this module) a route to write either a live extension
or a capsule.  Staging and activation remain later lifecycle operations.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Iterable

from core import portable_contract
from core.customization_migration.behaviour import (
    BEHAVIOUR_ID,
    BehaviouralContract,
)
from core.customization_migration.capsule_model import CAPSULE_ID
from core.customization_migration.model import (
    CUSTOMIZATION_ID,
    EDGE_ID,
    Assessment,
    validate_native_witness_target,
)

SHA256 = re.compile(r"^[0-9a-f]{64}$")
PROPOSAL_ID = re.compile(r"^prop-[0-9a-f]{16}$")
RELEASE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_CANDIDATE_BYTES = 1024 * 1024
MAX_TEXT_CHARS = 2000
_PROTECTED_ARTIFACT_PREFIX = "System/.dex/customization-migrations/"


def _canonical_path(value: str, *, name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty canonical vault-relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{name} must be a canonical vault-relative path")
    return value


def _bounded_text(value: str, *, name: str, allow_empty: bool = False) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if (
        (not allow_empty and not value)
        or len(value) > MAX_TEXT_CHARS
        or "\x00" in value
    ):
        qualifier = "possibly empty" if allow_empty else "non-empty"
        raise ValueError(
            f"{name} must be a {qualifier} string of at most "
            f"{MAX_TEXT_CHARS} characters without NUL"
        )


class Disposition(str, Enum):
    CARRY_FORWARD = "carry-forward"
    REWRITE = "rewrite"
    COMPATIBILITY_SHIM = "compatibility-shim"
    NATIVE_REPLACEMENT = "native-replacement"
    KEEP_DISABLED = "keep-disabled"
    MANUAL_REVIEW = "manual-review"
    BLOCKED = "blocked"


class DependencyResolution(str, Enum):
    """The only ways a captured dependency may be handled by a candidate."""

    PRESERVE = "preserve"
    REMAP = "remap"


class RequirementKind(str, Enum):
    PERMISSION = "permission"
    TRUST = "trust"


@dataclass(frozen=True)
class DispositionPlanItem:
    customization_id: str
    disposition: Disposition
    assessment_digest: str
    native_witness: str | None = None
    evidence_edge_ids: tuple[str, ...] = ()
    behaviour_contract_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.customization_id, str)
            or CUSTOMIZATION_ID.fullmatch(self.customization_id) is None
        ):
            raise ValueError("customization_id is not canonical")
        if not isinstance(self.disposition, Disposition):
            raise TypeError("disposition must be a closed Disposition value")
        if (
            not isinstance(self.assessment_digest, str)
            or SHA256.fullmatch(self.assessment_digest) is None
        ):
            raise ValueError("assessment_digest must be canonical SHA-256")
        if self.native_witness is not None:
            validate_native_witness_target(self.native_witness)
        for name, values, pattern in (
            ("evidence_edge_ids", self.evidence_edge_ids, EDGE_ID),
            ("behaviour_contract_ids", self.behaviour_contract_ids, BEHAVIOUR_ID),
        ):
            if (
                not isinstance(values, tuple)
                or tuple(sorted(set(values))) != values
                or any(pattern.fullmatch(value) is None for value in values)
            ):
                raise ValueError(f"{name} must be sorted unique canonical identifiers")

    def to_dict(self) -> dict[str, object]:
        return {
            "customization_id": self.customization_id,
            "disposition": self.disposition.value,
            "assessment_digest": self.assessment_digest,
            "native_witness": self.native_witness,
            "evidence_edge_ids": list(self.evidence_edge_ids),
            "behaviour_contract_ids": list(self.behaviour_contract_ids),
        }


@dataclass(frozen=True)
class CandidateFile:
    """One complete proposed file, bound to the customizations it combines."""

    target_path: str
    content: bytes
    sha256: str
    customization_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _canonical_path(self.target_path, name="candidate target_path")
        if self.target_path.startswith(_PROTECTED_ARTIFACT_PREFIX):
            raise ValueError("candidate targets cannot be protected migration artifacts")
        verdict = portable_contract.update_write_verdict(
            self.target_path,
            exists=False,
            operation="customization-migration",
        )
        if not verdict.allowed:
            raise ValueError("candidate target is not a supported customization seam")
        if (
            not isinstance(self.content, bytes)
            or not self.content
            or len(self.content) > MAX_CANDIDATE_BYTES
        ):
            raise ValueError(
                "candidate content must be non-empty bytes within the write-free bound"
            )
        if (
            not isinstance(self.sha256, str)
            or SHA256.fullmatch(self.sha256) is None
            or hashlib.sha256(self.content).hexdigest() != self.sha256
        ):
            raise ValueError("candidate sha256 must bind the exact candidate bytes")
        if (
            not isinstance(self.customization_ids, tuple)
            or not self.customization_ids
            or tuple(sorted(set(self.customization_ids))) != self.customization_ids
            or any(CUSTOMIZATION_ID.fullmatch(value) is None for value in self.customization_ids)
        ):
            raise ValueError("candidate customization_ids must be sorted known-shaped ids")

    @classmethod
    def create(
        cls,
        target_path: str,
        content: bytes,
        customization_ids: tuple[str, ...],
    ) -> CandidateFile:
        return cls(
            target_path,
            content,
            hashlib.sha256(content).hexdigest(),
            tuple(sorted(set(customization_ids))),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "target_path": self.target_path,
            "content_base64": base64.b64encode(self.content).decode("ascii"),
            "sha256": self.sha256,
            "customization_ids": list(self.customization_ids),
        }


@dataclass(frozen=True)
class DependencyRemapping:
    edge_id: str
    resolution: DependencyResolution
    target_path: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.edge_id, str) or EDGE_ID.fullmatch(self.edge_id) is None:
            raise ValueError("edge_id is not canonical")
        if not isinstance(self.resolution, DependencyResolution):
            raise TypeError("resolution must be a closed DependencyResolution value")
        if self.resolution is DependencyResolution.PRESERVE:
            if self.target_path is not None:
                raise ValueError("preserved dependencies cannot provide a target path")
        else:
            if self.target_path is None:
                raise ValueError("remapped dependencies require a target path")
            _canonical_path(self.target_path, name="dependency target_path")

    def to_dict(self) -> dict[str, object]:
        return {
            "edge_id": self.edge_id,
            "resolution": self.resolution.value,
            "target_path": self.target_path,
        }


@dataclass(frozen=True)
class DeclaredRequirement:
    kind: RequirementKind
    description: str
    customization_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RequirementKind):
            raise TypeError("kind must be a closed RequirementKind value")
        _bounded_text(self.description, name="requirement description")
        if (
            not isinstance(self.customization_ids, tuple)
            or not self.customization_ids
            or tuple(sorted(set(self.customization_ids))) != self.customization_ids
            or any(CUSTOMIZATION_ID.fullmatch(value) is None for value in self.customization_ids)
        ):
            raise ValueError("requirement customization_ids must be sorted canonical ids")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "description": self.description,
            "customization_ids": list(self.customization_ids),
        }


@dataclass(frozen=True)
class ShimExpiry:
    customization_id: str
    review_release: str
    removal_condition: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.customization_id, str)
            or CUSTOMIZATION_ID.fullmatch(self.customization_id) is None
        ):
            raise ValueError("shim customization_id is not canonical")
        if (
            not isinstance(self.review_release, str)
            or RELEASE_LABEL.fullmatch(self.review_release) is None
        ):
            raise ValueError("shim review_release is not a canonical release label")
        _bounded_text(self.removal_condition, name="shim removal_condition")

    def to_dict(self) -> dict[str, str]:
        return {
            "customization_id": self.customization_id,
            "review_release": self.review_release,
            "removal_condition": self.removal_condition,
        }


@dataclass(frozen=True)
class RegenerationCandidate:
    """A schema-closed proposal whose candidate bytes are still write-free."""

    schema_version: int
    proposal_id: str
    capsule_id: str
    evidence_digest: str
    dispositions: tuple[DispositionPlanItem, ...]
    files: tuple[CandidateFile, ...]
    dependency_remappings: tuple[DependencyRemapping, ...]
    behaviour_contracts: tuple[BehaviouralContract, ...]
    declared_requirements: tuple[DeclaredRequirement, ...]
    confidence: int
    unresolved_questions: tuple[str, ...]
    shim_expiries: tuple[ShimExpiry, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 0:
            raise ValueError("unsupported regeneration candidate schema_version")
        if not isinstance(self.proposal_id, str) or PROPOSAL_ID.fullmatch(self.proposal_id) is None:
            raise ValueError("proposal_id is not canonical")
        if not isinstance(self.capsule_id, str) or CAPSULE_ID.fullmatch(self.capsule_id) is None:
            raise ValueError("capsule_id is not canonical")
        if not isinstance(self.evidence_digest, str) or SHA256.fullmatch(self.evidence_digest) is None:
            raise ValueError("evidence_digest must be canonical SHA-256")
        for name, values, value_type, key in (
            ("dispositions", self.dispositions, DispositionPlanItem, lambda value: value.customization_id),
            ("files", self.files, CandidateFile, lambda value: value.target_path),
            ("dependency_remappings", self.dependency_remappings, DependencyRemapping, lambda value: value.edge_id),
            ("behaviour_contracts", self.behaviour_contracts, BehaviouralContract, lambda value: value.contract_id),
            ("declared_requirements", self.declared_requirements, DeclaredRequirement, lambda value: (value.kind.value, value.description, value.customization_ids)),
            ("shim_expiries", self.shim_expiries, ShimExpiry, lambda value: value.customization_id),
        ):
            if not isinstance(values, tuple) or any(type(value) is not value_type for value in values):
                raise TypeError(f"{name} must be a tuple of {value_type.__name__}")
            if tuple(sorted(values, key=key)) != values or len({key(value) for value in values}) != len(values):
                raise ValueError(f"{name} must be sorted and unique")
        if type(self.confidence) is not int or not 0 <= self.confidence <= 100:
            raise ValueError("confidence must be an integer from 0 through 100")
        if (
            not isinstance(self.unresolved_questions, tuple)
            or tuple(sorted(set(self.unresolved_questions))) != self.unresolved_questions
        ):
            raise ValueError("unresolved_questions must be sorted and unique")
        for question in self.unresolved_questions:
            _bounded_text(question, name="unresolved question")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "proposal_id": self.proposal_id,
            "capsule_id": self.capsule_id,
            "evidence_digest": self.evidence_digest,
            "dispositions": [item.to_dict() for item in self.dispositions],
            "files": [item.to_dict() for item in self.files],
            "dependency_remappings": [item.to_dict() for item in self.dependency_remappings],
            "behaviour_contracts": [item.to_dict() for item in self.behaviour_contracts],
            "declared_requirements": [item.to_dict() for item in self.declared_requirements],
            "confidence": self.confidence,
            "unresolved_questions": list(self.unresolved_questions),
            "shim_expiries": [item.to_dict() for item in self.shim_expiries],
        }

    def canonical_bytes(self) -> bytes:
        return (
            json.dumps(
                self._unsigned_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    @property
    def candidate_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def to_dict(self) -> dict[str, object]:
        result = self._unsigned_dict()
        result["candidate_sha256"] = self.candidate_sha256
        return result


@dataclass(frozen=True)
class PlanValidation:
    accepted: bool
    verdict: str
    errors: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.accepted) is not bool:
            raise TypeError("accepted must be a boolean")
        if self.verdict not in {"OK", "BROKEN"}:
            raise ValueError("plan validation verdict must be OK or BROKEN")
        if not isinstance(self.errors, tuple):
            raise TypeError("plan validation errors must be a tuple")
        if self.accepted != (self.verdict == "OK" and not self.errors):
            raise ValueError("plan validation fields are contradictory")


@dataclass(frozen=True)
class CandidateValidation:
    accepted: bool
    verdict: str
    candidate_sha256: str
    errors: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.accepted) is not bool:
            raise TypeError("accepted must be a boolean")
        if self.verdict not in {"OK", "BROKEN"}:
            raise ValueError("candidate validation verdict must be OK or BROKEN")
        if not isinstance(self.candidate_sha256, str) or SHA256.fullmatch(self.candidate_sha256) is None:
            raise ValueError("candidate_sha256 must be canonical SHA-256")
        if not isinstance(self.errors, tuple):
            raise TypeError("candidate validation errors must be a tuple")
        if self.accepted != (self.verdict == "OK" and not self.errors):
            raise ValueError("candidate validation fields are contradictory")


def _assessment_digest(assessment: Assessment) -> str:
    return hashlib.sha256(assessment.canonical_assessment_bytes()).hexdigest()


def validate_disposition_plan(
    assessment: Assessment,
    plan_items: Iterable[DispositionPlanItem],
) -> PlanValidation:
    """Refuse any plan whose ids are not exact or whose evidence drifted."""
    if not isinstance(assessment, Assessment):
        raise TypeError("assessment must be Assessment")
    items = tuple(plan_items)
    if any(type(item) is not DispositionPlanItem for item in items):
        raise TypeError("plan_items must contain DispositionPlanItem records")
    if (
        assessment.baseline_identity_state != "VERIFIED"
        or assessment.completeness != "OK"
        or assessment.verdict != "OK"
    ):
        return PlanValidation(
            False,
            "BROKEN",
            ("assessment is not a verified complete evidence set",),
        )
    expected_ids = {record.customization_id for record in assessment.records}
    records_by_id = {record.customization_id: record for record in assessment.records}
    edge_ids = {edge.edge_id for edge in assessment.edges}
    edge_ids_by_record = {
        record.customization_id: {
            edge.edge_id
            for edge in assessment.edges
            if edge.source_path in record.source_paths
        }
        for record in assessment.records
    }
    counts = Counter(item.customization_id for item in items)
    actual_digest = _assessment_digest(assessment)
    errors: list[str] = []
    for customization_id in sorted(expected_ids - counts.keys()):
        errors.append(f"missing customization id: {customization_id}")
    for customization_id in sorted(
        customization_id for customization_id, count in counts.items() if count > 1
    ):
        errors.append(f"duplicate customization id: {customization_id}")
    for customization_id in sorted(counts.keys() - expected_ids):
        errors.append(f"unknown customization id: {customization_id}")
    for item in items:
        if item.assessment_digest != actual_digest:
            errors.append(f"assessment digest mismatch for {item.customization_id}")
        if (
            item.disposition is Disposition.NATIVE_REPLACEMENT
            and item.native_witness is None
        ):
            errors.append(
                "native-replacement requires a deterministic witness: "
                f"{item.customization_id}"
            )
        elif (
            item.disposition is not Disposition.NATIVE_REPLACEMENT
            and item.native_witness is not None
        ):
            errors.append(
                "only native-replacement accepts a deterministic witness: "
                f"{item.customization_id}"
            )
        if item.disposition is Disposition.REWRITE and not item.evidence_edge_ids:
            errors.append(
                "rewrite requires captured dependency evidence: "
                f"{item.customization_id}"
            )
        for edge_id in item.evidence_edge_ids:
            if edge_id not in edge_ids:
                errors.append(f"unknown evidence edge: {edge_id}")
            elif (
                item.customization_id in records_by_id
                and edge_id not in edge_ids_by_record[item.customization_id]
            ):
                errors.append(
                    "evidence edge does not belong to customization: "
                    f"{item.customization_id}:{edge_id}"
                )
    ordered_errors = tuple(dict.fromkeys(errors))
    return PlanValidation(
        not ordered_errors,
        "OK" if not ordered_errors else "BROKEN",
        ordered_errors,
    )


def validate_regeneration_candidate(
    assessment: Assessment,
    candidate: RegenerationCandidate,
    *,
    expected_capsule_id: str | None = None,
) -> CandidateValidation:
    """Validate a full candidate without staging it or touching the vault.

    ``expected_capsule_id`` is intentionally supplied by the capsule-owning
    adapter.  A bare assessment has no authority to assert which on-disk
    capsule it came from, so callers that have a capsule must bind it here.
    """
    if not isinstance(assessment, Assessment):
        raise TypeError("assessment must be Assessment")
    if type(candidate) is not RegenerationCandidate:
        raise TypeError("candidate must be RegenerationCandidate")
    if expected_capsule_id is not None and (
        not isinstance(expected_capsule_id, str)
        or CAPSULE_ID.fullmatch(expected_capsule_id) is None
    ):
        raise ValueError("expected_capsule_id must be canonical when provided")

    errors = list(validate_disposition_plan(assessment, candidate.dispositions).errors)
    actual_digest = _assessment_digest(assessment)
    if candidate.evidence_digest != actual_digest:
        errors.append("candidate evidence digest does not match assessment")
    if expected_capsule_id is not None and candidate.capsule_id != expected_capsule_id:
        errors.append("candidate capsule id does not match the selected capsule")

    records_by_id = {record.customization_id: record for record in assessment.records}
    plans_by_id = {item.customization_id: item for item in candidate.dispositions}
    files_by_target = {item.target_path: item for item in candidate.files}
    files_by_customization: dict[str, list[CandidateFile]] = defaultdict(list)
    for item in candidate.files:
        for customization_id in item.customization_ids:
            if customization_id not in records_by_id:
                errors.append(f"candidate file names unknown customization: {customization_id}")
                continue
            files_by_customization[customization_id].append(item)

    generated_dispositions = {
        Disposition.REWRITE,
        Disposition.COMPATIBILITY_SHIM,
    }
    for customization_id, files in sorted(files_by_customization.items()):
        plan = plans_by_id.get(customization_id)
        if plan is not None and plan.disposition not in generated_dispositions:
            errors.append(
                "disposition may not propose candidate content: "
                f"{customization_id}"
            )
        if len({item.target_path for item in files}) != len(files):
            errors.append(f"candidate target collision: {customization_id}")
    for customization_id, plan in plans_by_id.items():
        if plan.disposition in generated_dispositions and not files_by_customization.get(
            customization_id
        ):
            errors.append(f"generated disposition has no candidate content: {customization_id}")

    contracts_by_id = {item.contract_id: item for item in candidate.behaviour_contracts}
    for contract in candidate.behaviour_contracts:
        if contract.customization_id not in records_by_id:
            errors.append(
                "behaviour contract names unknown customization: "
                f"{contract.customization_id}"
            )
    for plan in candidate.dispositions:
        for contract_id in plan.behaviour_contract_ids:
            contract = contracts_by_id.get(contract_id)
            if contract is None:
                errors.append(f"unknown behaviour contract: {contract_id}")
            elif contract.customization_id != plan.customization_id:
                errors.append(
                    "behaviour contract does not belong to customization: "
                    f"{plan.customization_id}:{contract_id}"
                )

    expected_shims = {
        item.customization_id
        for item in candidate.dispositions
        if item.disposition is Disposition.COMPATIBILITY_SHIM
    }
    actual_shims = {item.customization_id for item in candidate.shim_expiries}
    for customization_id in sorted(expected_shims - actual_shims):
        errors.append(f"compatibility-shim needs expiry: {customization_id}")
    for customization_id in sorted(actual_shims - expected_shims):
        errors.append(f"shim expiry without compatibility-shim: {customization_id}")

    for requirement in candidate.declared_requirements:
        for customization_id in requirement.customization_ids:
            if customization_id not in records_by_id:
                errors.append(
                    "declared requirement names unknown customization: "
                    f"{customization_id}"
                )

    edges_by_id = {edge.edge_id: edge for edge in assessment.edges}
    edge_owner: dict[str, str] = {}
    for record in assessment.records:
        for edge in assessment.edges:
            if edge.source_path in record.source_paths:
                edge_owner[edge.edge_id] = record.customization_id
    remappings_by_id = {
        item.edge_id: item for item in candidate.dependency_remappings
    }
    for remapping in candidate.dependency_remappings:
        edge = edges_by_id.get(remapping.edge_id)
        if edge is None:
            errors.append(f"unknown dependency edge: {remapping.edge_id}")
            continue
        owner = edge_owner.get(remapping.edge_id)
        plan = plans_by_id.get(owner) if owner is not None else None
        if plan is None or plan.disposition not in generated_dispositions:
            errors.append(
                "dependency remapping is only valid for generated content: "
                f"{remapping.edge_id}"
            )
            continue
        if remapping.resolution is DependencyResolution.PRESERVE:
            if edge.target.startswith(("unresolved:", "outside-vault:")):
                errors.append(
                    "cannot preserve an unresolved or outside-vault dependency: "
                    f"{remapping.edge_id}"
                )
        else:
            target = files_by_target.get(remapping.target_path or "")
            if target is None:
                errors.append(
                    "dependency remap target is not a candidate file: "
                    f"{remapping.edge_id}"
                )
            elif owner not in target.customization_ids:
                errors.append(
                    "dependency remap target is not owned by customization: "
                    f"{owner}:{remapping.edge_id}"
                )
    for record in assessment.records:
        plan = plans_by_id.get(record.customization_id)
        if plan is None or plan.disposition not in generated_dispositions:
            continue
        for edge in assessment.edges:
            if edge.source_path in record.source_paths and edge.edge_id not in remappings_by_id:
                errors.append(
                    "generated customization has unresolved dependency: "
                    f"{record.customization_id}:{edge.edge_id}"
                )

    ordered_errors = tuple(dict.fromkeys(errors))
    return CandidateValidation(
        not ordered_errors,
        "OK" if not ordered_errors else "BROKEN",
        candidate.candidate_sha256,
        ordered_errors,
    )


__all__ = [
    "CandidateFile",
    "CandidateValidation",
    "DeclaredRequirement",
    "DependencyRemapping",
    "DependencyResolution",
    "Disposition",
    "DispositionPlanItem",
    "PlanValidation",
    "RegenerationCandidate",
    "RequirementKind",
    "ShimExpiry",
    "validate_disposition_plan",
    "validate_regeneration_candidate",
]
