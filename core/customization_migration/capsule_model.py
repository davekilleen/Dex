"""Pure schema validation for v0 customization capsule manifests."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from core.customization_migration.model import EXCLUSION_REASONS, SHA256

CAPSULE_ID = re.compile(r"^cap-[0-9a-f]{16}$")
CAPSULE_LAYOUT_V0 = (
    "manifest.json",
    "journal.jsonl",
    "evidence/",
    "blobs/",
    "restricted/",
    "interpretations/",
    "candidates/",
    "verification/",
    "receipts/",
    "report.md",
)
EVIDENCE_SECTIONS_V0 = frozenset(
    {
        "customizations",
        "dependencies",
        "behaviours",
        "exclusions",
        "environment",
    }
)


@dataclass(frozen=True)
class CapsuleManifest:
    schema_version: int
    capsule_id: str
    source_release_version: str
    target_release_version: str | None
    created_epoch_seconds: int
    inventory_digest: str
    assessment_digest: str
    customization_count: int
    dependency_count: int
    behaviour_contract_count: int
    restricted_item_count: int
    excluded_reasons: tuple[str, ...]
    completeness: str
    section_digests: tuple[tuple[str, str, int], ...]

    def __post_init__(self) -> None:
        if self.schema_version != 0:
            raise ValueError("unsupported capsule manifest schema_version")
        if (
            not isinstance(self.capsule_id, str)
            or CAPSULE_ID.fullmatch(self.capsule_id) is None
        ):
            raise ValueError("capsule_id is not canonical")
        if (
            not isinstance(self.source_release_version, str)
            or not self.source_release_version
        ):
            raise ValueError("source_release_version must be a non-empty string")
        if self.target_release_version is not None and (
            not isinstance(self.target_release_version, str)
            or not self.target_release_version
        ):
            raise ValueError(
                "target_release_version must be a non-empty string or null"
            )
        if (
            type(self.created_epoch_seconds) is not int
            or self.created_epoch_seconds <= 0
        ):
            raise ValueError("created_epoch_seconds must be a positive integer")
        for name, value in (
            ("inventory_digest", self.inventory_digest),
            ("assessment_digest", self.assessment_digest),
        ):
            if not isinstance(value, str) or SHA256.fullmatch(value) is None:
                raise ValueError(f"{name} must be canonical SHA-256")
        for name, value in (
            ("customization_count", self.customization_count),
            ("dependency_count", self.dependency_count),
            ("behaviour_contract_count", self.behaviour_contract_count),
            ("restricted_item_count", self.restricted_item_count),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if (
            not isinstance(self.excluded_reasons, tuple)
            or tuple(sorted(set(self.excluded_reasons))) != self.excluded_reasons
            or any(reason not in EXCLUSION_REASONS for reason in self.excluded_reasons)
        ):
            raise ValueError(
                "excluded_reasons must be a sorted unique tuple of closed reason codes"
            )
        if self.completeness not in {"OK", "UNKNOWN"}:
            raise ValueError("completeness must be OK or UNKNOWN")
        if not isinstance(self.section_digests, tuple):
            raise TypeError("section_digests must be a tuple")
        names: list[str] = []
        for entry in self.section_digests:
            if not isinstance(entry, tuple) or len(entry) != 3:
                raise ValueError(
                    "section digest entries must be (section_name, sha256, byte_size)"
                )
            section_name, digest, byte_size = entry
            if section_name not in EVIDENCE_SECTIONS_V0:
                raise ValueError("section_name is not in the closed v0 vocabulary")
            if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
                raise ValueError("section sha256 must be canonical SHA-256")
            if type(byte_size) is not int or byte_size < 0:
                raise ValueError("section byte_size must be a non-negative integer")
            names.append(section_name)
        if tuple(sorted(set(names))) != tuple(names):
            raise ValueError("section_digests must be sorted and unique by name")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capsule_id": self.capsule_id,
            "source_release_version": self.source_release_version,
            "target_release_version": self.target_release_version,
            "created_epoch_seconds": self.created_epoch_seconds,
            "inventory_digest": self.inventory_digest,
            "assessment_digest": self.assessment_digest,
            "customization_count": self.customization_count,
            "dependency_count": self.dependency_count,
            "behaviour_contract_count": self.behaviour_contract_count,
            "restricted_item_count": self.restricted_item_count,
            "excluded_reasons": list(self.excluded_reasons),
            "completeness": self.completeness,
            "section_digests": [
                {
                    "section_name": section_name,
                    "sha256": digest,
                    "byte_size": byte_size,
                }
                for section_name, digest, byte_size in self.section_digests
            ],
        }

    def canonical_manifest_bytes(self) -> bytes:
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
    "CAPSULE_ID",
    "CAPSULE_LAYOUT_V0",
    "EVIDENCE_SECTIONS_V0",
    "CapsuleManifest",
]
