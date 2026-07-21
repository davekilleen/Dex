"""Release-relative divergence detection with honest UNKNOWN outcomes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Protocol

from core.lifecycle.catalog import CatalogError, loads_catalog
from core.lifecycle.filesystem import FilesystemInspectionError, bounded_read, normalize_relative_path
from core.lifecycle.model import ReleaseCatalog

MANIFEST_PATH = "System/.installed-files.manifest"
CATALOG_CANDIDATES = (
    "System/.release-catalog.json",
    "core/lifecycle/catalog/release.json",
)
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_CATALOG_BYTES = 16 * 1024 * 1024

RELEASE_STATES = (
    "stock-unmodified",
    "stock-modified",
    "stock-missing",
    "canonical-customization",
    "unknown",
    "durable-state",
    "cache",
    "machine-projection",
    "forbidden",
)


@dataclass(frozen=True)
class ReleaseBaseline:
    identity_state: str
    release_version: str | None
    manifest_paths: frozenset[str]
    expected_hashes: Mapping[str, str]
    errors: tuple[str, ...]

    def expected_sha256(self, canonical_path: str) -> str | None:
        return self.expected_hashes.get(canonical_path)

    def to_dict(self) -> dict[str, object]:
        return {
            "identity_state": self.identity_state,
            "release_version": self.release_version,
            "manifest_path_count": len(self.manifest_paths),
            "catalog_hash_count": len(self.expected_hashes),
            "errors": list(self.errors),
        }


class InventoryLike(Protocol):
    actual_path: str
    canonical_path: str
    ownership_class: str | None
    release_state: str


@dataclass(frozen=True)
class Divergence:
    path: str
    canonical_path: str
    state: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "canonical_path": self.canonical_path,
            "state": self.state,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CustomizationReport:
    state: str
    divergences: tuple[Divergence, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "count": len(self.divergences),
            "divergences": [entry.to_dict() for entry in self.divergences],
        }


def _parse_manifest(raw: bytes) -> frozenset[str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FilesystemInspectionError("installed manifest is not UTF-8") from error
    if not text.endswith("\n") or "\r" in text or "\x00" in text:
        raise FilesystemInspectionError("installed manifest is not canonical newline text")
    paths = text.splitlines()
    if paths != sorted(set(paths)):
        raise FilesystemInspectionError("installed manifest paths are not sorted and unique")
    return frozenset(normalize_relative_path(path) for path in paths)


def _catalog_from_disk(root: Path, relative: str, manifest_bytes: bytes) -> ReleaseCatalog:
    raw = bounded_read(root, relative, max_bytes=MAX_CATALOG_BYTES)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FilesystemInspectionError("release catalog is not UTF-8") from error
    return loads_catalog(text, manifest_bytes=manifest_bytes)


def load_release_baseline(
    vault_root: Path,
    *,
    catalog: ReleaseCatalog | None = None,
    catalog_path: str | None = None,
) -> ReleaseBaseline:
    """Load only provable installed-release evidence; never infer clean state."""
    root = Path(vault_root)
    errors: list[str] = []
    manifest_bytes: bytes | None = None
    manifest_paths: frozenset[str] = frozenset()
    try:
        manifest_bytes = bounded_read(root, MANIFEST_PATH, max_bytes=MAX_MANIFEST_BYTES)
        manifest_paths = _parse_manifest(manifest_bytes)
    except FilesystemInspectionError as error:
        errors.append(str(error))

    selected_catalog = catalog
    if selected_catalog is None and manifest_bytes is not None:
        candidates = [catalog_path] if catalog_path is not None else [
            path for path in CATALOG_CANDIDATES if (root / path).is_file()
        ]
        if len(candidates) > 1:
            errors.append("multiple installed release catalogs are present; identity is ambiguous")
        elif candidates:
            try:
                selected_catalog = _catalog_from_disk(root, normalize_relative_path(candidates[0]), manifest_bytes)
            except (CatalogError, FilesystemInspectionError) as error:
                errors.append(str(error))

    expected_hashes: Mapping[str, str] = MappingProxyType({})
    release_version: str | None = None
    identity_state = "UNKNOWN"
    if selected_catalog is not None and manifest_bytes is not None:
        actual_manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        if selected_catalog.release.manifest.sha256 != actual_manifest_hash:
            errors.append("catalog manifest binding does not match the installed manifest")
        else:
            catalog_hashes = {
                file.path: file.sha256
                for item in selected_catalog.items
                for file in item.files
            }
            if not set(catalog_hashes).issubset(manifest_paths):
                errors.append("catalog names files absent from the installed release manifest")
            else:
                expected_hashes = MappingProxyType(dict(sorted(catalog_hashes.items())))
                release_version = selected_catalog.release.version
                identity_state = "VERIFIED"
    elif manifest_bytes is not None:
        identity_state = "MANIFEST_ONLY"

    return ReleaseBaseline(
        identity_state,
        release_version,
        manifest_paths,
        expected_hashes,
        tuple(sorted(set(errors))),
    )


def is_machine_projection(path: str) -> bool:
    lower = path.casefold()
    return lower == ".mcp.json" or lower.endswith((".db", ".sqlite", ".sqlite3", "-wal", "-shm"))


def is_cache(path: str) -> bool:
    lower = path.casefold()
    parts = lower.split("/")
    return (
        lower.startswith(".logs/")
        or "cache" in parts
        or "caches" in parts
        or lower.endswith((".log", ".tmp"))
    )


def classify_release_state(
    *,
    canonical_path: str,
    kind: str,
    ownership_class: str | None,
    denied: bool,
    actual_sha256: str | None,
    baseline: ReleaseBaseline,
) -> str:
    """Layer byte/release state on top of the contract ownership class."""
    if denied:
        return "forbidden"
    if kind == "missing":
        return "stock-missing"
    if ownership_class is None:
        return "unknown"
    expected = baseline.expected_sha256(canonical_path)
    if expected is not None and kind == "file":
        if actual_sha256 is None:
            return "unknown"
        return "stock-unmodified" if actual_sha256 == expected else "stock-modified"
    if ownership_class == "brain":
        return "unknown"
    if ownership_class == "generated":
        return "cache"
    if is_machine_projection(canonical_path):
        return "machine-projection"
    if ownership_class in {"vault", "seed"}:
        return "canonical-customization"
    if ownership_class == "runtime":
        return "cache" if is_cache(canonical_path) else "durable-state"
    return "unknown"


def detect_customizations(entries: tuple[InventoryLike, ...]) -> CustomizationReport:
    """Report user divergence and unprovable release-owned identity separately."""
    divergences: list[Divergence] = []
    for entry in entries:
        if entry.release_state == "stock-modified":
            reason = "installed bytes differ from the verified release catalog"
        elif entry.release_state == "stock-missing":
            reason = "a verified release-catalog file is absent"
        elif entry.release_state == "unknown" and entry.ownership_class == "brain":
            reason = "release-owned identity cannot be proven from available evidence"
        else:
            continue
        divergences.append(
            Divergence(entry.actual_path, entry.canonical_path, entry.release_state, reason)
        )
    ordered = tuple(sorted(divergences, key=lambda entry: (entry.canonical_path, entry.path)))
    state = "DIVERGED" if any(entry.state.startswith("stock-") for entry in ordered) else (
        "UNKNOWN" if ordered else "CLEAN"
    )
    return CustomizationReport(state, ordered)


__all__ = [
    "CATALOG_CANDIDATES",
    "CustomizationReport",
    "Divergence",
    "MANIFEST_PATH",
    "RELEASE_STATES",
    "ReleaseBaseline",
    "classify_release_state",
    "detect_customizations",
    "is_cache",
    "is_machine_projection",
    "load_release_baseline",
]
