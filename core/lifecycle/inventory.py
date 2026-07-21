"""Deterministic, read-only installed-vault inventory and classifier."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from core import portable_contract
from core.lifecycle.customizations import (
    CustomizationReport,
    ReleaseBaseline,
    classify_release_state,
    detect_customizations,
    load_release_baseline,
)
from core.lifecycle.filesystem import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_READ_BYTES,
    FilesystemInspectionError,
    normalize_relative_path,
    sha256_file,
    walk_read_only,
)
from core.lifecycle.machine_state import MachineStateReport, probe_machine_state
from core.lifecycle.model import ReleaseCatalog
from core.lifecycle.secrets import assert_no_denied_metadata, redact_document

FOLDER_MAP_PATH = "System/folder-paths.yaml"
MAX_FOLDER_MAP_BYTES = 256 * 1024
FOLDER_KEY = re.compile(r"^[a-z][a-z0-9_]*$")

# Semantic keys and their contract-canonical defaults.  Unknown extension keys
# are allowed in the YAML but cannot change contract classification.
DEFAULT_FOLDER_PATHS: dict[str, str] = {
    "inbox": "00-Inbox",
    "meetings": "00-Inbox/Meetings",
    "goals": "01-Quarter_Goals",
    "priorities": "02-Week_Priorities",
    "tasks": "03-Tasks",
    "projects": "04-Projects",
    "people_internal": "05-Areas/People/Internal",
    "people_external": "05-Areas/People/External",
    "companies": "05-Areas/Companies",
    "career": "05-Areas/Career",
    "content": "05-Areas/Content",
    "accounts": "05-Areas/Relationships/Key_Accounts",
    "resources": "06-Resources",
    "archives": "07-Archives",
    "archived_projects": "07-Archives/Projects",
    "archived_plans": "07-Archives/Plans",
    "archived_reviews": "07-Archives/Reviews",
    "system": "System",
    "templates": "System/Templates",
}


@dataclass(frozen=True)
class FolderMap:
    state: str
    mappings: tuple[tuple[str, str, str], ...]
    errors: tuple[str, ...] = ()

    def canonicalize(self, actual_path: str) -> str:
        candidate = normalize_relative_path(actual_path)
        for _semantic, actual, canonical in self.mappings:
            if candidate == actual:
                return canonical
            if candidate.startswith(actual + "/"):
                return canonical + candidate[len(actual) :]
        return candidate

    def materialize(self, canonical_path: str) -> str:
        candidate = normalize_relative_path(canonical_path)
        ordered = sorted(self.mappings, key=lambda row: (-len(row[2].split("/")), row[2], row[1]))
        for _semantic, actual, canonical in ordered:
            if candidate == canonical:
                return actual
            if candidate.startswith(canonical + "/"):
                return actual + candidate[len(canonical) :]
        return candidate

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "mappings": [
                {"semantic_type": semantic, "actual_path": actual, "canonical_path": canonical}
                for semantic, actual, canonical in self.mappings
                if actual != canonical
            ],
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class InventoryEntry:
    actual_path: str
    canonical_path: str
    kind: str
    ownership_class: str | None
    contract_rule: str | None
    denied: bool
    release_state: str
    write_allowed: bool
    write_action: str
    size: int | None = None
    sha256: str | None = None
    redacted: bool = False

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "path": self.actual_path,
            "canonical_path": self.canonical_path,
            "kind": self.kind,
            "ownership_class": self.ownership_class,
            "contract_rule": self.contract_rule,
            "denied": self.denied,
            "release_state": self.release_state,
            "write_allowed": self.write_allowed,
            "write_action": self.write_action,
            "size": self.size,
            "sha256": self.sha256,
        }
        if self.redacted:
            value["redacted"] = True
        redacted = redact_document(value)
        assert isinstance(redacted, dict)
        return redacted


@dataclass(frozen=True)
class InventoryReport:
    folder_map: FolderMap
    baseline: ReleaseBaseline
    entries: tuple[InventoryEntry, ...]
    unknown_paths: tuple[str, ...]
    unproven_paths: tuple[str, ...]
    canonical_collisions: tuple[tuple[str, ...], ...]
    errors: tuple[str, ...]
    complete: bool
    machine_state: MachineStateReport
    customizations: CustomizationReport

    def _document_without_hash(self) -> dict[str, object]:
        ownership_counts = Counter(entry.ownership_class or "unclassified" for entry in self.entries)
        release_counts = Counter(entry.release_state for entry in self.entries)
        kind_counts = Counter(entry.kind for entry in self.entries)
        return {
            "inventory_version": 1,
            "complete": self.complete,
            "folder_map": self.folder_map.to_dict(),
            "release_baseline": self.baseline.to_dict(),
            "counts": {
                "paths": len(self.entries),
                "ownership_classes": dict(sorted(ownership_counts.items())),
                "release_states": dict(sorted(release_counts.items())),
                "kinds": dict(sorted(kind_counts.items())),
                "unknown_paths": len(self.unknown_paths),
                "tracked_despite_ignored": len(self.machine_state.tracked_despite_ignored.paths),
            },
            "entries": [entry.to_dict() for entry in self.entries],
            "unknowns": list(self.unknown_paths),
            "unproven_release_identity": list(self.unproven_paths),
            "case_collisions": [list(paths) for paths in self.machine_state.case_collisions],
            "canonical_collisions": [list(paths) for paths in self.canonical_collisions],
            "tracked_despite_ignored": self.machine_state.tracked_despite_ignored.to_dict(),
            "customizations": self.customizations.to_dict(),
            "errors": list(self.errors),
        }

    def to_dict(self) -> dict[str, object]:
        raw = self._document_without_hash()
        redacted = redact_document(raw)
        assert_no_denied_metadata(redacted)
        assert isinstance(redacted, dict)
        encoded = json.dumps(
            redacted,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        redacted["inventory_sha256"] = hashlib.sha256(encoded).hexdigest()
        return redacted


def load_folder_map(vault_root: Path) -> FolderMap:
    root = Path(vault_root)
    path = root / FOLDER_MAP_PATH
    if not path.exists():
        return FolderMap("DEFAULT", ())
    try:
        from core.lifecycle.filesystem import bounded_read

        raw = bounded_read(root, FOLDER_MAP_PATH, max_bytes=MAX_FOLDER_MAP_BYTES)
        payload = _parse_flat_folder_map(raw)
        mappings: list[tuple[str, str, str]] = []
        actual_owners: dict[str, str] = {}
        for semantic, canonical in DEFAULT_FOLDER_PATHS.items():
            actual_value = payload.get(semantic, canonical)
            if not isinstance(actual_value, str):
                raise ValueError(f"folder map value for {semantic} must be a path string")
            actual = normalize_relative_path(actual_value)
            folded = actual.casefold()
            previous = actual_owners.get(folded)
            if previous is not None and previous != canonical:
                raise ValueError(f"folder map aliases two semantic roots onto {actual}")
            actual_owners[folded] = canonical
            mappings.append((semantic, actual, canonical))
        mappings.sort(key=lambda row: (-len(row[1].split("/")), row[1].casefold(), row[0]))
        return FolderMap("LOADED", tuple(mappings))
    except (FilesystemInspectionError, UnicodeDecodeError, ValueError) as error:
        return FolderMap("UNKNOWN", (), (str(error),))


def _parse_flat_folder_map(raw: bytes) -> dict[str, str]:
    """Parse the contract's deliberately flat ``semantic: path`` YAML form.

    Folder paths are scalar strings only; accepting YAML graphs or nested
    values would add ambiguity to an authority-bearing path map.  Quoted JSON
    strings and ordinary unquoted paths cover the documented file format.
    """
    if len(raw) > MAX_FOLDER_MAP_BYTES:
        raise ValueError("folder map exceeds its configured byte bound")
    text = raw.decode("utf-8")
    result: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in raw_line or ":" not in line or any(token in line for token in ("&", "*", "<<")):
            raise ValueError(f"folder map line {line_number} is not a flat scalar mapping")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if FOLDER_KEY.fullmatch(key) is None or key in result:
            raise ValueError(f"folder map line {line_number} has an invalid or duplicate key")
        if value.startswith('"'):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as error:
                raise ValueError(f"folder map line {line_number} has an invalid quoted path") from error
            if not isinstance(parsed, str):
                raise ValueError(f"folder map line {line_number} path must be a string")
            value = parsed
        elif value.startswith("'"):
            if len(value) < 2 or not value.endswith("'"):
                raise ValueError(f"folder map line {line_number} has an invalid quoted path")
            value = value[1:-1].replace("''", "'")
        else:
            value = value.split(" #", 1)[0].rstrip()
            if not value or value[0] in "[{!":
                raise ValueError(f"folder map line {line_number} path must be a scalar string")
        result[key] = value
    return result


def _contract_facts(canonical_path: str, *, exists: bool) -> tuple[str | None, str | None, bool, bool, str]:
    try:
        resolution = portable_contract.resolve(canonical_path)
        ownership = resolution.ownership
        rule = resolution.rule_id
        denied = resolution.denied
    except portable_contract.ContractViolation:
        ownership = None
        rule = None
        denied = False
    verdict = portable_contract.update_write_verdict(canonical_path, exists=exists)
    return ownership, rule, denied, verdict.allowed, verdict.action


def build_inventory(
    vault_root: Path,
    *,
    catalog: ReleaseCatalog | None = None,
    catalog_path: str | None = None,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_hash_bytes: int = DEFAULT_MAX_READ_BYTES,
) -> InventoryReport:
    """Classify every observed path, reporting rather than guessing unknowns."""
    root = Path(vault_root)
    folder_map = load_folder_map(root)
    baseline = load_release_baseline(root, catalog=catalog, catalog_path=catalog_path)
    walked = walk_read_only(root, max_entries=max_entries)
    machine = probe_machine_state(root, max_entries=max_entries, walk=walked)
    entries: list[InventoryEntry] = []
    errors = list(folder_map.errors) + list(baseline.errors) + list(walked.errors)
    canonical_to_actual: dict[str, list[str]] = {}

    for observed in walked.entries:
        canonical = folder_map.canonicalize(observed.path)
        canonical_to_actual.setdefault(canonical.casefold(), []).append(observed.path)
        ownership, rule, denied, write_allowed, write_action = _contract_facts(canonical, exists=True)
        digest: str | None = None
        if (
            observed.kind == "file"
            and not denied
            and baseline.expected_sha256(canonical) is not None
        ):
            try:
                digest = sha256_file(root, observed.path, max_bytes=max_hash_bytes)
            except FilesystemInspectionError as error:
                errors.append(str(error))
        release_state = classify_release_state(
            canonical_path=canonical,
            kind=observed.kind,
            ownership_class=ownership,
            denied=denied,
            actual_sha256=digest,
            baseline=baseline,
        )
        entries.append(
            InventoryEntry(
                observed.path,
                canonical,
                observed.kind,
                ownership,
                rule,
                denied,
                release_state,
                write_allowed,
                write_action,
                None if denied else observed.size,
                None if denied else digest,
                denied,
            )
        )

    present_canonical = {entry.canonical_path for entry in entries}
    for expected_path in baseline.expected_hashes:
        if expected_path in present_canonical:
            continue
        actual = folder_map.materialize(expected_path)
        ownership, rule, denied, write_allowed, write_action = _contract_facts(expected_path, exists=False)
        entries.append(
            InventoryEntry(
                actual,
                expected_path,
                "missing",
                ownership,
                rule,
                denied,
                "stock-missing",
                write_allowed,
                write_action,
                redacted=denied,
            )
        )

    entries.sort(key=lambda entry: (entry.actual_path, entry.kind, entry.canonical_path))
    canonical_collisions = tuple(
        tuple(sorted(paths))
        for _, paths in sorted(canonical_to_actual.items())
        if len(paths) > 1
    )
    if canonical_collisions:
        errors.append("multiple real paths map to the same canonical contract path")
    if machine.case_collisions:
        errors.append("case-fold path collisions make filesystem identity ambiguous")
    if walked.truncated:
        errors.append("filesystem inventory reached its configured entry bound")
    unknown_paths = tuple(entry.actual_path for entry in entries if entry.ownership_class is None)
    unproven = tuple(entry.actual_path for entry in entries if entry.release_state == "unknown")
    customization_report = detect_customizations(tuple(entries))
    complete = (
        not walked.truncated
        and folder_map.state != "UNKNOWN"
        and not canonical_collisions
        and not machine.case_collisions
    )
    return InventoryReport(
        folder_map,
        baseline,
        tuple(entries),
        tuple(sorted(set(unknown_paths))),
        tuple(sorted(set(unproven))),
        canonical_collisions,
        tuple(sorted(set(errors))),
        complete,
        machine,
        customization_report,
    )


def canonical_inventory_bytes(report: InventoryReport) -> bytes:
    """Stable JSON bytes for receipts/tests; contains no wall-clock fields."""
    return (
        json.dumps(
            report.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


__all__ = [
    "DEFAULT_FOLDER_PATHS",
    "FOLDER_MAP_PATH",
    "FolderMap",
    "InventoryEntry",
    "InventoryReport",
    "build_inventory",
    "canonical_inventory_bytes",
    "load_folder_map",
]
