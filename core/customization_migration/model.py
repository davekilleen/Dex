"""Deterministic customization-assessment records.

The vocabulary is v0 and may change until the capsule lanes freeze it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath

from core.lifecycle.customizations import RELEASE_STATES

SHA256 = re.compile(r"^[0-9a-f]{64}$")
CUSTOMIZATION_ID = re.compile(r"^cust-[0-9a-f]{12}$")
EDGE_ID = re.compile(r"^dep-[0-9a-f]{12}$")
SKILL_REFERENCE_TARGET = re.compile(r"^skill:[a-z0-9][a-z0-9-]*$")
PACKAGE_REFERENCE_TARGET = re.compile(r"^package:[A-Za-z0-9@/_.-]{1,256}$")
VERDICTS = frozenset({"OK", "OFF", "BROKEN", "UNKNOWN"})
READABILITY = frozenset({"readable", "restricted", "excluded", "missing", "hash-only"})
EXCLUSION_REASONS = frozenset(
    {
        "restricted",
        "symlink-refused",
        "read-bound-exceeded",
        "read-error",
        "embedded-secret",
        "trust-hash-mismatch",
        "release-identity-unproved",
        "dependency-tree-excluded",
        "embedded-repository",
        "canonical-path-collision",
        "invalid-trust-registry",
        "reference-budget-exhausted",
    }
)
EXCLUSION_GUIDANCE = {
    "restricted": "Review this path locally; Dex will not inspect or archive it.",
    "symlink-refused": "Replace the link with a regular file inside the vault, then reassess.",
    "read-bound-exceeded": "Reduce or split the file so it fits the inspection limit, then reassess.",
    "read-error": "Make the file readable and valid for its format, then reassess.",
    "embedded-secret": "Remove the credential or secret before including this file; Dex will not archive it.",
    "trust-hash-mismatch": "Re-authorize the current file through the trust flow, then reassess.",
    # Interim wording (re-anchoring design ruling 5; verbatim wording is
    # founder copy): honest before the re-anchor repair exists. Once that flow
    # ships, this string changes to point at it — see the design's "Guidance
    # correction" section.
    "release-identity-unproved": (
        "Dex can't yet prove these files came from your installed release — "
        "that's a gap in Dex's own records, not a problem with your files. "
        "A guided repair that checks them against the official release record "
        "is coming. Updating will not clear this notice, so don't update just "
        "to fix it."
    ),
    "dependency-tree-excluded": "Move the dependency into a regular supported vault path, then reassess.",
    "embedded-repository": "Keep the nested repository separate and record its dependency manually.",
    "canonical-path-collision": "Rename the colliding path so each canonical vault path is unique.",
    "invalid-trust-registry": "Repair or recreate the trust registry through its setup flow, then reassess.",
    "reference-budget-exhausted": "Reduce the assessed scope or split the dependency set, then reassess.",
}
INCOMPLETE_REASONS = frozenset(
    {
        "assessment-exclusions",
        "baseline-not-verified",
        "folder-map-unknown",
        "inventory-errors",
        "inventory-incomplete",
        "walk-truncated",
    }
)


class CustomizationKind(str, Enum):
    """Closed evidence-level customization vocabulary."""

    MODIFIED_SKILL = "modified-skill"
    MODIFIED_SHIPPED_FILE = "modified-shipped-file"
    DELETED_SHIPPED_FILE = "deleted-shipped-file"
    CUSTOM_SKILL = "custom-skill"
    CUSTOM_INSTRUCTIONS = "custom-instructions"
    CUSTOM_HOOK = "custom-hook"
    CUSTOM_SCRIPT = "custom-script"
    CUSTOM_MCP = "custom-mcp"
    CUSTOM_CONFIG = "custom-config"
    UNKNOWN_ADDITION = "unknown-addition"


class EdgeKind(str, Enum):
    """Closed dependency-edge vocabulary from the approved plan."""

    SKILL_TO_SCRIPT = "skill-to-script"
    INSTRUCTIONS_TO_SKILL = "instructions-to-skill"
    HOOK_TO_SCRIPT = "hook-to-script"
    MCP_TO_SERVER = "mcp-to-server"
    MARKDOWN_LINK = "markdown-link"
    LITERAL_PATH = "literal-path"
    ENV_VAR_NAME = "env-var-name"
    LAUNCH_AGENT_TO_EXECUTABLE = "launch-agent-to-executable"
    PACKAGE_DEPENDENCY = "package-dependency"


class ReferenceConfidence(str, Enum):
    PROVED = "proved"
    INFERRED = "inferred"


class AssessmentGroup(str, Enum):
    """Mechanical location/evidence groups for the v0 assessment."""

    UPDATE_REPLACEABLE_LOCATION = "update-replaceable-location"
    UPDATE_UNTOUCHED_LOCATION = "update-untouched-location"
    NEEDS_INTERPRETATION = "needs-interpretation"
    BLOCKED = "blocked"


def _canonical_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("path must be a non-empty canonical vault-relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"path is not canonical and vault-relative: {value!r}")
    return value


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "\0".join(parts).encode("utf-8")
    return f"{prefix}{hashlib.sha256(payload).hexdigest()[:12]}"


def validate_native_witness_target(value: str) -> str:
    """Validate the deterministic native-replacement witness grammar."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("native witness must be a non-empty string")
    if SKILL_REFERENCE_TARGET.fullmatch(value) is not None:
        return value
    if ":" in value:
        raise ValueError(
            "native witness must be a vault-relative path or skill reference"
        )
    _canonical_path(value)
    return value


@dataclass(frozen=True)
class BaselineInfo:
    release_version: str | None
    expected_sha256: str | None

    def __post_init__(self) -> None:
        if self.release_version is not None and (
            not isinstance(self.release_version, str) or not self.release_version
        ):
            raise ValueError("baseline release_version must be a non-empty string or null")
        if self.expected_sha256 is not None and (
            not isinstance(self.expected_sha256, str)
            or SHA256.fullmatch(self.expected_sha256) is None
        ):
            raise ValueError("baseline expected_sha256 must be canonical SHA-256 or null")

    def to_dict(self) -> dict[str, object]:
        return {
            "release_version": self.release_version,
            "sha256": self.expected_sha256,
        }


@dataclass(frozen=True)
class LiveInfo:
    sha256: str | None
    byte_size: int | None
    model_readability: str
    executable: bool | None = None

    def __post_init__(self) -> None:
        if self.sha256 is not None and (
            not isinstance(self.sha256, str) or SHA256.fullmatch(self.sha256) is None
        ):
            raise ValueError("live sha256 must be canonical SHA-256 or null")
        if self.byte_size is not None and (
            type(self.byte_size) is not int or self.byte_size < 0
        ):
            raise ValueError("live byte_size must be a non-negative integer or null")
        if self.model_readability not in READABILITY:
            raise ValueError("live model_readability is not a closed authority value")
        if self.executable is not None and type(self.executable) is not bool:
            raise ValueError("live executable must be a boolean or null")
        if self.model_readability == "readable" and (
            self.sha256 is None or self.byte_size is None
        ):
            raise ValueError("readable live content requires both hash and byte size")
        if self.model_readability in {"restricted", "missing"} and (
            self.sha256 is not None
            or self.byte_size is not None
            or self.executable is not None
        ):
            raise ValueError(
                "restricted or missing content cannot expose hash, size, or executable mode"
            )
        if self.model_readability == "hash-only" and (
            self.sha256 is None
            or self.byte_size is not None
            or self.executable is not None
        ):
            raise ValueError("hash-only content exposes only a SHA-256")

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "model_readability": self.model_readability,
        }
        if self.executable is not None:
            result["executable"] = self.executable
        return result


@dataclass(frozen=True)
class CustomizationEvidence:
    release_state: str
    reference_edge_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.release_state not in RELEASE_STATES:
            raise ValueError("evidence release_state is not in the lifecycle vocabulary")
        if (
            not isinstance(self.reference_edge_ids, tuple)
            or tuple(sorted(set(self.reference_edge_ids))) != self.reference_edge_ids
            or any(EDGE_ID.fullmatch(value) is None for value in self.reference_edge_ids)
        ):
            raise ValueError("reference_edge_ids must be sorted unique dependency ids")

    def to_dict(self) -> dict[str, object]:
        return {
            "release_state": self.release_state,
            "reference_edge_ids": list(self.reference_edge_ids),
        }


@dataclass(frozen=True)
class CustomizationRecord:
    customization_id: str
    kind: CustomizationKind
    source_paths: tuple[str, ...]
    baseline: BaselineInfo
    live: LiveInfo
    evidence: CustomizationEvidence
    required_disposition: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CustomizationKind):
            raise TypeError("kind must be CustomizationKind")
        if (
            not isinstance(self.source_paths, tuple)
            or not self.source_paths
            or tuple(sorted(set(self.source_paths))) != self.source_paths
        ):
            raise ValueError("source_paths must be a sorted non-empty unique tuple")
        for path in self.source_paths:
            _canonical_path(path)
        expected_id = _stable_id("cust-", self.kind.value, self.source_paths[0])
        if CUSTOMIZATION_ID.fullmatch(self.customization_id) is None:
            raise ValueError("customization_id is not canonical")
        if self.customization_id != expected_id:
            raise ValueError("customization_id does not match kind and primary path")
        if type(self.baseline) is not BaselineInfo:
            raise TypeError("baseline must be BaselineInfo")
        if type(self.live) is not LiveInfo:
            raise TypeError("live must be LiveInfo")
        if type(self.evidence) is not CustomizationEvidence:
            raise TypeError("evidence must be CustomizationEvidence")
        if self.required_disposition is not True:
            raise ValueError("required_disposition must be true in schema version 0")

    @classmethod
    def create(
        cls,
        kind: CustomizationKind,
        source_paths: tuple[str, ...],
        baseline: BaselineInfo,
        live: LiveInfo,
        evidence: CustomizationEvidence,
    ) -> CustomizationRecord:
        ordered = tuple(sorted(set(source_paths)))
        if not ordered:
            raise ValueError("source_paths cannot be empty")
        return cls(
            _stable_id("cust-", kind.value, ordered[0]),
            kind,
            ordered,
            baseline,
            live,
            evidence,
            True,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "customization_id": self.customization_id,
            "kind": self.kind.value,
            "source_paths": list(self.source_paths),
            "baseline": self.baseline.to_dict(),
            "live": self.live.to_dict(),
            "evidence": self.evidence.to_dict(),
            "required_disposition": self.required_disposition,
        }


@dataclass(frozen=True)
class ReferenceEdge:
    edge_id: str
    source_path: str
    target: str
    edge_kind: EdgeKind
    confidence: ReferenceConfidence

    def __post_init__(self) -> None:
        _canonical_path(self.source_path)
        if not isinstance(self.target, str) or not self.target or "\x00" in self.target:
            raise ValueError("reference target must be a non-empty string")
        if (
            self.target.startswith("package:")
            and PACKAGE_REFERENCE_TARGET.fullmatch(self.target) is None
        ):
            raise ValueError("package reference target is not canonical")
        symbolic = (
            re.fullmatch(r"env:[A-Z][A-Z0-9_]*", self.target)
            or re.fullmatch(r"unresolved:[0-9a-f]{12}", self.target)
            or re.fullmatch(
                r"python:(?:[A-Za-z_][A-Za-z0-9_]*)(?:\.[A-Za-z_][A-Za-z0-9_]*)*",
                self.target,
            )
            or re.fullmatch(
                r"python-relative:[1-9][0-9]*:[A-Za-z_][A-Za-z0-9_]*"
                r"(?:\.[A-Za-z_][A-Za-z0-9_]*)*",
                self.target,
            )
            or SKILL_REFERENCE_TARGET.fullmatch(self.target)
            or PACKAGE_REFERENCE_TARGET.fullmatch(self.target)
            or self.target in {"outside-vault:absolute", "outside-vault:escape"}
        )
        if symbolic is None:
            _canonical_path(self.target)
        if not isinstance(self.edge_kind, EdgeKind):
            raise TypeError("edge_kind must be EdgeKind")
        if not isinstance(self.confidence, ReferenceConfidence):
            raise TypeError("confidence must be ReferenceConfidence")
        expected = _stable_id(
            "dep-",
            self.edge_kind.value,
            self.source_path,
            self.target,
        )
        if EDGE_ID.fullmatch(self.edge_id) is None or self.edge_id != expected:
            raise ValueError("edge_id does not match its canonical relationship")

    @classmethod
    def create(
        cls,
        source_path: str,
        target: str,
        edge_kind: EdgeKind,
        confidence: ReferenceConfidence,
    ) -> ReferenceEdge:
        return cls(
            _stable_id("dep-", edge_kind.value, source_path, target),
            source_path,
            target,
            edge_kind,
            confidence,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "edge_id": self.edge_id,
            "source_path": self.source_path,
            "target": self.target,
            "edge_kind": self.edge_kind.value,
            "confidence": self.confidence.value,
        }


@dataclass(frozen=True)
class AssessmentExclusion:
    path: str
    reason: str
    uninspected_count: int | None = None

    def __post_init__(self) -> None:
        _canonical_path(self.path)
        if self.reason not in EXCLUSION_REASONS:
            raise ValueError("exclusion reason is not a closed authority value")
        if self.uninspected_count is not None and (
            type(self.uninspected_count) is not int or self.uninspected_count < 1
        ):
            raise ValueError("uninspected_count must be a positive integer or null")
        if (
            self.reason == "reference-budget-exhausted"
        ) != (self.uninspected_count is not None):
            raise ValueError(
                "only reference budget exclusions carry uninspected_count"
            )

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "path": self.path,
            "reason": self.reason,
            "guidance": EXCLUSION_GUIDANCE[self.reason],
        }
        if self.uninspected_count is not None:
            result["uninspected_count"] = self.uninspected_count
        return result


@dataclass(frozen=True)
class AssessmentAssignment:
    customization_id: str
    group: AssessmentGroup

    def __post_init__(self) -> None:
        if CUSTOMIZATION_ID.fullmatch(self.customization_id) is None:
            raise ValueError("group customization_id is not canonical")
        if not isinstance(self.group, AssessmentGroup):
            raise TypeError("group must be AssessmentGroup")

    def to_dict(self) -> dict[str, str]:
        return {
            "customization_id": self.customization_id,
            "group": self.group.value,
        }


@dataclass(frozen=True)
class AssessmentIdentity:
    release_version: str | None
    inventory_path_count: int
    customization_count: int
    edge_count: int

    def __post_init__(self) -> None:
        if self.release_version is not None and (
            not isinstance(self.release_version, str) or not self.release_version
        ):
            raise ValueError("identity release_version must be a non-empty string or null")
        for value in (
            self.inventory_path_count,
            self.customization_count,
            self.edge_count,
        ):
            if type(value) is not int or value < 0:
                raise ValueError("identity counts must be non-negative integers")

    def to_dict(self) -> dict[str, object]:
        return {
            "release_version": self.release_version,
            "inventory_path_count": self.inventory_path_count,
            "customization_count": self.customization_count,
            "edge_count": self.edge_count,
        }


@dataclass(frozen=True)
class Assessment:
    """One read-only v0 assessment."""

    schema_version: int
    identity: AssessmentIdentity
    baseline_identity_state: str
    baseline_errors: tuple[str, ...]
    incomplete_reasons: tuple[str, ...]
    records: tuple[CustomizationRecord, ...]
    edges: tuple[ReferenceEdge, ...]
    groups: tuple[AssessmentAssignment, ...]
    exclusions: tuple[AssessmentExclusion, ...]
    completeness: str
    verdict: str

    def __post_init__(self) -> None:
        if self.schema_version != 0:
            raise ValueError("unsupported assessment schema_version")
        if type(self.identity) is not AssessmentIdentity:
            raise TypeError("identity must be AssessmentIdentity")
        if self.baseline_identity_state not in {"VERIFIED", "MANIFEST_ONLY", "UNKNOWN"}:
            raise ValueError("baseline identity state is invalid")
        if (
            not isinstance(self.baseline_errors, tuple)
            or tuple(sorted(set(self.baseline_errors))) != self.baseline_errors
        ):
            raise ValueError("baseline_errors must be a sorted unique tuple")
        if (
            not isinstance(self.incomplete_reasons, tuple)
            or tuple(sorted(set(self.incomplete_reasons)))
            != self.incomplete_reasons
            or any(
                reason not in INCOMPLETE_REASONS
                for reason in self.incomplete_reasons
            )
        ):
            raise ValueError("incomplete_reasons must use the closed reason codes")
        if not isinstance(self.records, tuple) or any(
            type(value) is not CustomizationRecord for value in self.records
        ):
            raise TypeError("records must be a tuple of CustomizationRecord")
        if tuple(sorted(self.records, key=lambda item: item.source_paths)) != self.records:
            raise ValueError("records must be ordered by source path")
        if len({record.customization_id for record in self.records}) != len(self.records):
            raise ValueError("record customization ids must be unique")
        if not isinstance(self.edges, tuple) or any(
            type(value) is not ReferenceEdge for value in self.edges
        ):
            raise TypeError("edges must be a tuple of ReferenceEdge")
        if tuple(sorted(self.edges, key=lambda item: item.edge_id)) != self.edges:
            raise ValueError("edges must be ordered by edge id")
        if len({edge.edge_id for edge in self.edges}) != len(self.edges):
            raise ValueError("edge ids must be unique")
        expected_ids = tuple(sorted(record.customization_id for record in self.records))
        if (
            not isinstance(self.groups, tuple)
            or any(type(value) is not AssessmentAssignment for value in self.groups)
            or tuple(item.customization_id for item in self.groups) != expected_ids
        ):
            raise ValueError("groups must account for the exact sorted record-id set")
        if (
            not isinstance(self.exclusions, tuple)
            or any(type(value) is not AssessmentExclusion for value in self.exclusions)
            or tuple(sorted(self.exclusions, key=lambda item: (item.path, item.reason)))
            != self.exclusions
        ):
            raise ValueError("exclusions must be an ordered AssessmentExclusion tuple")
        if self.completeness not in {"OK", "UNKNOWN"}:
            raise ValueError("completeness must be OK or UNKNOWN")
        if self.verdict not in VERDICTS:
            raise ValueError("assessment verdict is invalid")
        expected_verdict = "OK" if self.completeness == "OK" else "UNKNOWN"
        if self.verdict != expected_verdict:
            raise ValueError("assessment verdict must follow completeness")
        if self.completeness == "OK" and self.incomplete_reasons:
            raise ValueError("complete assessment cannot contain incomplete reasons")
        if self.completeness == "UNKNOWN" and not self.incomplete_reasons:
            raise ValueError("unknown assessment requires at least one reason code")
        if self.identity.customization_count != len(self.records):
            raise ValueError("identity customization_count does not match records")
        if self.identity.edge_count != len(self.edges):
            raise ValueError("identity edge_count does not match edges")
        if (
            self.completeness == "UNKNOWN"
            and self.baseline_identity_state != "VERIFIED"
            and (
                self.records
                or self.edges
                or self.groups
                or self.identity.inventory_path_count
                or self.identity.customization_count
                or self.identity.edge_count
            )
        ):
            raise ValueError(
                "an unverified baseline cannot expose partial records, edges, groups, or counts"
            )

    def to_dict(self) -> dict[str, object]:
        if (
            self.completeness == "UNKNOWN"
            and self.baseline_identity_state != "VERIFIED"
        ):
            return {
                "schema_version": self.schema_version,
                "baseline_identity_state": self.baseline_identity_state,
                "incomplete_reasons": list(self.incomplete_reasons),
                "completeness": self.completeness,
                "verdict": self.verdict,
            }
        result = {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "baseline_identity_state": self.baseline_identity_state,
            "baseline_errors": list(self.baseline_errors),
            "incomplete_reasons": list(self.incomplete_reasons),
            "records": [record.to_dict() for record in self.records],
            "edges": [edge.to_dict() for edge in self.edges],
            "groups": [group.to_dict() for group in self.groups],
            "exclusions": [exclusion.to_dict() for exclusion in self.exclusions],
            "completeness": self.completeness,
            "verdict": self.verdict,
        }
        if self.completeness == "UNKNOWN":
            result["partial"] = True
        return result

    def canonical_assessment_bytes(self) -> bytes:
        return (
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")


__all__ = [
    "Assessment",
    "AssessmentAssignment",
    "AssessmentExclusion",
    "AssessmentGroup",
    "AssessmentIdentity",
    "BaselineInfo",
    "CustomizationEvidence",
    "CustomizationKind",
    "CustomizationRecord",
    "EdgeKind",
    "EXCLUSION_GUIDANCE",
    "EXCLUSION_REASONS",
    "LiveInfo",
    "ReferenceConfidence",
    "ReferenceEdge",
    "validate_native_witness_target",
]
