"""Strict, deterministic typed model for the release catalog."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from core import portable_contract

CATALOG_VERSION = 1
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
ITEM_ID = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
TAG = re.compile(
    r"^dist/(?P<channel>release(?:-beta)?)/v(?P<version>[^/]+)-(?P<short>[0-9a-f]{7,40})$"
)


class CatalogError(ValueError):
    """Base class for fail-closed catalog failures."""


class CatalogModelError(CatalogError):
    """A document cannot be represented without guessing."""


def _unknown(message: str) -> CatalogModelError:
    return CatalogModelError(f"catalog state is UNKNOWN: {message}")


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _unknown(f"{context} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise _unknown(f"{context} has a non-string field name")
    return value


def _closed_fields(
    value: Mapping[str, Any], *, required: set[str], optional: set[str] = frozenset(), context: str
) -> None:
    fields = set(value)
    missing = required - fields
    unknown = fields - required - optional
    if missing:
        raise _unknown(f"{context} is missing required fields: {', '.join(sorted(missing))}")
    if unknown:
        raise _unknown(f"{context} has unknown fields: {', '.join(sorted(unknown))}")


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise _unknown(f"{context} must be a non-empty string")
    return value


def _sha256(value: object, context: str) -> str:
    digest = _string(value, context)
    if HEX_SHA256.fullmatch(digest) is None:
        raise _unknown(f"{context} must be a lowercase sha256 digest")
    return digest


def _item_id(value: object, context: str) -> str:
    candidate = _string(value, context)
    if ITEM_ID.fullmatch(candidate) is None:
        raise _unknown(f"{context} is not a canonical item id")
    return candidate


def _version(value: object, context: str) -> str:
    candidate = _string(value, context)
    if SEMVER.fullmatch(candidate) is None:
        raise _unknown(f"{context} is not strict SemVer")
    return candidate


def _relative_path(value: object, context: str) -> str:
    candidate = _string(value, context)
    if "\\" in candidate or candidate.startswith("/") or any(ord(char) < 32 for char in candidate):
        raise _unknown(f"{context} must be a release-relative POSIX path")
    normalized = posixpath.normpath(candidate)
    if normalized != candidate or normalized in ("", ".", "..") or normalized.startswith("../"):
        raise _unknown(f"{context} is not a canonical release-relative path")
    return candidate


class AdoptionState(str, Enum):
    """Closed receipt vocabulary from the lifecycle program."""

    APPLIED = "applied"
    ADOPTED = "adopted"
    REWOUND = "rewound"
    HELD_FOR_REVIEW = "held-for-review"
    CUSTOMIZATION_REVIEW_REQUIRED = "customization-review-required"
    EXTERNAL_RECONCILIATION_PENDING = "external-reconciliation-pending"
    NEEDS_RECHECK = "needs-recheck"
    SKIPPED_BY_USER = "skipped-by-user"
    FAILED_ROLLED_BACK = "failed-rolled-back"


@dataclass(frozen=True)
class CatalogFile:
    path: str
    sha256: str
    ownership_class: str

    @classmethod
    def from_dict(cls, raw: object) -> "CatalogFile":
        value = _mapping(raw, "catalog file")
        _closed_fields(
            value,
            required={"path", "sha256", "ownership_class"},
            context="catalog file",
        )
        path = _relative_path(value["path"], "catalog file path")
        ownership = _string(value["ownership_class"], "catalog file ownership_class")
        if ownership not in portable_contract.OWNERSHIP_CLASSES:
            raise _unknown(f"catalog file {path} has unknown ownership class {ownership!r}")
        return cls(path, _sha256(value["sha256"], f"catalog file {path} sha256"), ownership)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "ownership_class": self.ownership_class,
        }


@dataclass(frozen=True)
class CatalogDependency:
    item_id: str
    version: str

    @classmethod
    def from_dict(cls, raw: object) -> "CatalogDependency":
        value = _mapping(raw, "catalog dependency")
        _closed_fields(value, required={"item_id", "version"}, context="catalog dependency")
        return cls(
            _item_id(value["item_id"], "dependency item_id"),
            _version(value["version"], "dependency version"),
        )

    def to_dict(self) -> dict[str, object]:
        return {"item_id": self.item_id, "version": self.version}


@dataclass(frozen=True)
class RewindAcknowledgement:
    acknowledgement_required: bool
    token: str

    @classmethod
    def from_dict(cls, raw: object, *, item_id: str, version: str) -> "RewindAcknowledgement":
        value = _mapping(raw, "rewind acknowledgement")
        _closed_fields(
            value,
            required={"acknowledgement_required", "token"},
            context="rewind acknowledgement",
        )
        if value["acknowledgement_required"] is not True:
            raise _unknown(f"rewind for {item_id} must require per-item acknowledgement")
        token = _string(value["token"], f"rewind token for {item_id}")
        expected = f"rewind:{item_id}@{version}"
        if token != expected:
            raise _unknown(f"rewind token for {item_id} must be exactly {expected!r}")
        return cls(True, token)

    def to_dict(self) -> dict[str, object]:
        return {
            "acknowledgement_required": self.acknowledgement_required,
            "token": self.token,
        }


@dataclass(frozen=True)
class CatalogItem:
    id: str
    kind: str
    version: str
    files: tuple[CatalogFile, ...]
    dependencies: tuple[CatalogDependency, ...]
    capabilities: tuple[str, ...]
    rewind: RewindAcknowledgement

    @classmethod
    def from_dict(cls, raw: object) -> "CatalogItem":
        value = _mapping(raw, "catalog item")
        _closed_fields(
            value,
            required={
                "id",
                "kind",
                "version",
                "files",
                "dependencies",
                "capabilities",
                "rewind",
            },
            context="catalog item",
        )
        item_id = _item_id(value["id"], "catalog item id")
        version = _version(value["version"], f"catalog item {item_id} version")
        kind = _item_id(value["kind"], f"catalog item {item_id} kind")
        if not isinstance(value["files"], list) or not value["files"]:
            raise _unknown(f"catalog item {item_id} needs at least one file")
        if not isinstance(value["dependencies"], list):
            raise _unknown(f"catalog item {item_id} dependencies must be an array")
        if not isinstance(value["capabilities"], list):
            raise _unknown(f"catalog item {item_id} capabilities must be an array")
        files = tuple(CatalogFile.from_dict(entry) for entry in value["files"])
        dependencies = tuple(CatalogDependency.from_dict(entry) for entry in value["dependencies"])
        capabilities = tuple(
            _item_id(entry, f"catalog item {item_id} capability") for entry in value["capabilities"]
        )
        if len({entry.path for entry in files}) != len(files):
            raise _unknown(f"catalog item {item_id} repeats a file path")
        if len({entry.item_id for entry in dependencies}) != len(dependencies):
            raise _unknown(f"catalog item {item_id} repeats a dependency")
        if len(set(capabilities)) != len(capabilities):
            raise _unknown(f"catalog item {item_id} repeats a capability")
        unknown_capabilities = set(capabilities) - set(portable_contract.CAPABILITIES)
        if unknown_capabilities:
            raise _unknown(
                f"catalog item {item_id} links unknown capabilities: "
                + ", ".join(sorted(unknown_capabilities))
            )
        return cls(
            item_id,
            kind,
            version,
            files,
            dependencies,
            capabilities,
            RewindAcknowledgement.from_dict(value["rewind"], item_id=item_id, version=version),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "version": self.version,
            "files": [entry.to_dict() for entry in self.files],
            "dependencies": [entry.to_dict() for entry in self.dependencies],
            "capabilities": list(self.capabilities),
            "rewind": self.rewind.to_dict(),
        }


@dataclass(frozen=True)
class ManifestBinding:
    path: str
    sha256: str

    @classmethod
    def from_dict(cls, raw: object) -> "ManifestBinding":
        value = _mapping(raw, "release manifest binding")
        _closed_fields(value, required={"path", "sha256"}, context="release manifest binding")
        path = _relative_path(value["path"], "release manifest path")
        if path != "System/.installed-files.manifest":
            raise _unknown("release manifest path is not the immutable installed-files manifest")
        return cls(path, _sha256(value["sha256"], "release manifest sha256"))

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(frozen=True)
class ReleaseIdentity:
    version: str
    channel: str
    immutable_distribution_tag: str
    source_commit: str
    manifest: ManifestBinding

    @classmethod
    def from_dict(cls, raw: object) -> "ReleaseIdentity":
        value = _mapping(raw, "release identity")
        _closed_fields(
            value,
            required={
                "version",
                "channel",
                "immutable_distribution_tag",
                "source_commit",
                "manifest",
            },
            context="release identity",
        )
        version = _version(value["version"], "release version")
        channel = _string(value["channel"], "release channel")
        if channel not in ("release", "release-beta"):
            raise _unknown(f"release channel {channel!r} is unsupported")
        tag = _string(value["immutable_distribution_tag"], "immutable distribution tag")
        commit = _string(value["source_commit"], "release source_commit")
        if FULL_COMMIT.fullmatch(commit) is None:
            raise _unknown("release source_commit must be a full lowercase 40-character git commit")
        match = TAG.fullmatch(tag)
        if match is None:
            raise _unknown("immutable distribution tag does not use the closed dist tag form")
        if match.group("channel") != channel or match.group("version") != version:
            raise _unknown("immutable distribution tag disagrees with release channel or version")
        if not commit.startswith(match.group("short")):
            raise _unknown("immutable distribution tag disagrees with the source commit")
        return cls(version, channel, tag, commit, ManifestBinding.from_dict(value["manifest"]))

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "channel": self.channel,
            "immutable_distribution_tag": self.immutable_distribution_tag,
            "source_commit": self.source_commit,
            "manifest": self.manifest.to_dict(),
        }


@dataclass(frozen=True)
class CatalogSignature:
    """Opaque signature envelope bound to the catalog hash.

    B1 models the envelope and rejects hash disagreement. Publisher-key trust
    and cryptographic verification remain a later release-verifier concern.
    """

    algorithm: str
    key_id: str
    signed_sha256: str
    value: str

    @classmethod
    def from_dict(cls, raw: object) -> "CatalogSignature":
        value = _mapping(raw, "catalog signature")
        _closed_fields(
            value,
            required={"algorithm", "key_id", "signed_sha256", "value"},
            context="catalog signature",
        )
        algorithm = _string(value["algorithm"], "catalog signature algorithm")
        if algorithm != "ed25519":
            raise _unknown(f"catalog signature algorithm {algorithm!r} is unsupported")
        return cls(
            algorithm,
            _string(value["key_id"], "catalog signature key_id"),
            _sha256(value["signed_sha256"], "catalog signature signed_sha256"),
            _string(value["value"], "catalog signature value"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "signed_sha256": self.signed_sha256,
            "value": self.value,
        }


@dataclass(frozen=True)
class CatalogIntegrity:
    catalog_sha256: str
    signatures: tuple[CatalogSignature, ...]

    @classmethod
    def from_dict(cls, raw: object) -> "CatalogIntegrity":
        value = _mapping(raw, "catalog integrity")
        _closed_fields(value, required={"catalog_sha256", "signatures"}, context="catalog integrity")
        if not isinstance(value["signatures"], list):
            raise _unknown("catalog integrity signatures must be an array")
        return cls(
            _sha256(value["catalog_sha256"], "catalog_sha256"),
            tuple(CatalogSignature.from_dict(entry) for entry in value["signatures"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "catalog_sha256": self.catalog_sha256,
            "signatures": [entry.to_dict() for entry in self.signatures],
        }


@dataclass(frozen=True)
class ReleaseCatalog:
    catalog_version: int
    release: ReleaseIdentity
    items: tuple[CatalogItem, ...]
    integrity: CatalogIntegrity

    @classmethod
    def from_dict(cls, raw: object) -> "ReleaseCatalog":
        value = _mapping(raw, "release catalog")
        _closed_fields(
            value,
            required={"catalog_version", "release", "items", "integrity"},
            context="release catalog",
        )
        if type(value["catalog_version"]) is not int or value["catalog_version"] != CATALOG_VERSION:
            raise _unknown(f"catalog_version must be exactly {CATALOG_VERSION}")
        if not isinstance(value["items"], list):
            raise _unknown("release catalog items must be an array")
        items = tuple(CatalogItem.from_dict(entry) for entry in value["items"])
        integrity = CatalogIntegrity.from_dict(value["integrity"])
        catalog = cls(
            CATALOG_VERSION,
            ReleaseIdentity.from_dict(value["release"]),
            items,
            integrity,
        )
        catalog._validate_relationships()
        return catalog

    def _validate_relationships(self) -> None:
        by_id = {item.id: item for item in self.items}
        if len(by_id) != len(self.items):
            raise _unknown("release catalog repeats an item id")
        all_paths = [entry.path for item in self.items for entry in item.files]
        if len(set(all_paths)) != len(all_paths):
            raise _unknown("release catalog assigns one file path to multiple items")
        for item in self.items:
            for dependency in item.dependencies:
                target = by_id.get(dependency.item_id)
                if target is None:
                    raise _unknown(f"catalog item {item.id} depends on missing item {dependency.item_id}")
                if target.version != dependency.version:
                    raise _unknown(
                        f"catalog item {item.id} requires {dependency.item_id}@{dependency.version}, "
                        f"but the catalog contains {target.version}"
                    )
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(item_id: str) -> None:
            if item_id in visiting:
                raise _unknown(f"catalog dependency cycle includes {item_id}")
            if item_id in visited:
                return
            visiting.add(item_id)
            for dependency in by_id[item_id].dependencies:
                visit(dependency.item_id)
            visiting.remove(item_id)
            visited.add(item_id)

        for item_id in by_id:
            visit(item_id)
        for signature in self.integrity.signatures:
            if signature.signed_sha256 != self.integrity.catalog_sha256:
                raise _unknown("catalog signature is bound to a different catalog_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "catalog_version": self.catalog_version,
            "release": self.release.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "integrity": self.integrity.to_dict(),
        }
