"""Read-only customization discovery built on lifecycle inventory authority."""

from __future__ import annotations

import hashlib
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from core import portable_contract
from core.customization_migration.model import (
    AssessmentAssignment,
    AssessmentExclusion,
    AssessmentGroup,
    BaselineInfo,
    CustomizationEvidence,
    CustomizationKind,
    CustomizationRecord,
    LiveInfo,
    ReferenceEdge,
)
from core.customization_migration.references import (
    MAX_SOURCE_BYTES,
    extract_reference_edges,
)
from core.lifecycle.customizations import detect_customizations
from core.lifecycle.filesystem import FilesystemInspectionError, bounded_read
from core.lifecycle.inventory import InventoryEntry, InventoryReport, build_inventory

SCRIPT_SUFFIXES = frozenset({".py", ".js", ".cjs", ".mjs", ".sh", ".bash", ".zsh"})
CONFIG_SUFFIXES = frozenset({".json", ".yaml", ".yml", ".toml"})
USER_CONFIG_PATHS = frozenset(
    {
        ".claude/settings.json",
        ".claude/settings.local.json",
        "System/folder-paths.yaml",
        "System/pillars.yaml",
        "System/user-profile.yaml",
    }
)
DEPENDENCY_PARTS = frozenset(
    {
        ".cache",
        ".git",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "vendor",
        "venv",
    }
)
ARCHIVE_SUFFIXES = (
    ".7z",
    ".bz2",
    ".gz",
    ".rar",
    ".tar",
    ".tgz",
    ".xz",
    ".zip",
)
SECRET_ASSIGNMENT = re.compile(
    rb"(?im)^\s*(?:export\s+)?"
    rb"[A-Z0-9_-]*(?:api[_-]?key|access[_-]?token|auth(?:orization)?|"
    rb"secret|password)[A-Z0-9_-]*\s*(?::|=)\s*"
    rb"(?:\"([^\"]+)\"|'([^']+)'|([^\s#]+))"
)
HIGH_CONFIDENCE_SECRET = re.compile(
    rb"(?i)\bsk-[A-Za-z0-9_-]{16,}\b|"
    rb"\bgh[pousr]_[A-Za-z0-9_]{20,}\b|"
    rb"\bAKIA[A-Z0-9]{16}\b|"
    rb"\bBearer[ \t]+[A-Za-z0-9._~+/-]{20,}\b|"
    rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
ENV_REFERENCE = re.compile(rb"^(?:\$[A-Z][A-Z0-9_]*|\$\{[A-Z][A-Z0-9_]*\})$")
PLACEHOLDER = re.compile(
    rb"(?i)^(?:change[-_]?me|example|placeholder|replace[-_]?me|todo|your[-_].*)$"
)


@dataclass(frozen=True)
class DiscoveryResult:
    inventory: InventoryReport
    records: tuple[CustomizationRecord, ...]
    edges: tuple[ReferenceEdge, ...]
    groups: tuple[AssessmentAssignment, ...]
    exclusions: tuple[AssessmentExclusion, ...]
    complete: bool


def _is_custom_skill_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if len(parts) >= 3 and parts[:2] == (".claude", "skills-custom"):
        return True
    return (
        len(parts) >= 4
        and parts[:2] == (".claude", "skills")
        and parts[2].endswith("-custom")
    )


def _is_customization_bearing(path: str) -> bool:
    return (
        path == "CLAUDE-custom.md"
        or path == ".mcp.json"
        or path == "System/folder-paths.yaml"
        or _is_custom_skill_path(path)
        or path.startswith(".claude/hooks/")
        or path.startswith("core/mcp-custom/")
    )


def _dependency_root(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    for index, part in enumerate(parts):
        if part in DEPENDENCY_PARTS:
            return PurePosixPath(*parts[: index + 1]).as_posix()
    if path.lower().endswith(ARCHIVE_SUFFIXES):
        return path
    return None


def _is_behavior_addition(entry: InventoryEntry, manifest_paths: frozenset[str]) -> bool:
    path = entry.actual_path
    if entry.kind not in {"file", "symlink"}:
        return False
    if _dependency_root(path) is not None:
        return False
    if _is_customization_bearing(path) or path in USER_CONFIG_PATHS:
        return True
    if path in manifest_paths:
        return False
    return (
        path.startswith((".scripts/", "scripts/", ".obsidian/", "System/Templates/"))
        or entry.ownership_class is None
    )


def _contains_embedded_secret(raw: bytes) -> bool:
    if HIGH_CONFIDENCE_SECRET.search(raw) is not None:
        return True
    for match in SECRET_ASSIGNMENT.finditer(raw):
        value = next(group for group in match.groups() if group is not None).strip()
        if (
            len(value) >= 8
            and ENV_REFERENCE.fullmatch(value) is None
            and PLACEHOLDER.fullmatch(value) is None
            and re.fullmatch(rb"[A-Z][A-Z0-9_]*", value) is None
        ):
            return True
    return False


def _is_secret_adjacent_path(path: str) -> bool:
    """Mirror Doctor's credential-sensitive path refusal before any byte read."""
    return any(
        part.lower() == ".env"
        or part.lower().startswith(".env.")
        or "credential" in part.lower()
        for part in PurePosixPath(path).parts
    )


def _kind_for(entry: InventoryEntry) -> CustomizationKind:
    path = entry.actual_path
    if entry.release_state == "stock-missing":
        return CustomizationKind.DELETED_SHIPPED_FILE
    if entry.release_state == "stock-modified":
        if path.startswith(".claude/skills/") and path.endswith("/SKILL.md"):
            return CustomizationKind.MODIFIED_SKILL
        return CustomizationKind.MODIFIED_SHIPPED_FILE
    if path == "CLAUDE-custom.md":
        return CustomizationKind.CUSTOM_INSTRUCTIONS
    if path == ".mcp.json" or path.startswith("core/mcp-custom/"):
        return CustomizationKind.CUSTOM_MCP
    if path.startswith(".claude/hooks/"):
        return CustomizationKind.CUSTOM_HOOK
    if _is_custom_skill_path(path) and path.endswith("/SKILL.md"):
        return CustomizationKind.CUSTOM_SKILL
    if PurePosixPath(path).suffix.lower() in SCRIPT_SUFFIXES:
        return CustomizationKind.CUSTOM_SCRIPT
    if path == "System/folder-paths.yaml" or PurePosixPath(path).suffix.lower() in CONFIG_SUFFIXES:
        return CustomizationKind.CUSTOM_CONFIG
    return CustomizationKind.UNKNOWN_ADDITION


def _safe_live(
    root: Path,
    entry: InventoryEntry,
) -> tuple[LiveInfo, bytes | None, AssessmentExclusion | None]:
    if entry.release_state == "stock-missing":
        return LiveInfo(None, None, "missing"), None, None
    if (
        entry.denied
        or portable_contract.is_denied(entry.actual_path)
        or _is_secret_adjacent_path(entry.actual_path)
    ):
        return (
            LiveInfo(None, None, "restricted"),
            None,
            AssessmentExclusion(entry.actual_path, "restricted"),
        )
    if entry.kind == "symlink":
        return (
            LiveInfo(None, None, "restricted"),
            None,
            AssessmentExclusion(entry.actual_path, "symlink-refused"),
        )
    if entry.kind != "file":
        return (
            LiveInfo(None, entry.size, "excluded"),
            None,
            AssessmentExclusion(entry.actual_path, "read-error"),
        )
    if entry.size is not None and entry.size > MAX_SOURCE_BYTES:
        return (
            LiveInfo(None, entry.size, "excluded"),
            None,
            AssessmentExclusion(entry.actual_path, "read-bound-exceeded"),
        )
    try:
        raw = bounded_read(root, entry.actual_path, max_bytes=MAX_SOURCE_BYTES)
    except FilesystemInspectionError:
        return (
            LiveInfo(None, entry.size, "excluded"),
            None,
            AssessmentExclusion(entry.actual_path, "read-error"),
        )
    if _contains_embedded_secret(raw):
        return (
            LiveInfo(None, None, "restricted"),
            None,
            AssessmentExclusion(entry.actual_path, "embedded-secret"),
        )
    return LiveInfo(hashlib.sha256(raw).hexdigest(), len(raw), "readable"), raw, None


def _skill_paths(entries: tuple[InventoryEntry, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in entries:
        if entry.kind != "file" or not entry.actual_path.endswith("/SKILL.md"):
            continue
        parts = PurePosixPath(entry.actual_path).parts
        if len(parts) >= 4 and parts[0] == ".claude" and parts[1] in {
            "skills",
            "skills-custom",
        }:
            result[parts[2]] = entry.actual_path
    return dict(sorted(result.items()))


def _target_resolves(
    root: Path,
    source_path: str,
    target: str,
    skill_paths: Mapping[str, str],
    actual_by_canonical: Mapping[str, str],
    ambiguous_canonical_paths: frozenset[str],
) -> bool:
    if target.startswith("outside-vault:"):
        return False
    if target.startswith("env:"):
        return True
    if target.startswith("python-relative:"):
        relative = target.removeprefix("python-relative:")
        level_text, _, module_name = relative.partition(":")
        if not level_text.isdigit() or not module_name:
            return False
        level = int(level_text)
        module = module_name.split(".", 1)[0]
        actual_source = actual_by_canonical.get(source_path, source_path)
        parent = PurePosixPath(actual_source).parent
        for _ in range(max(level - 1, 0)):
            parent = parent.parent
        sibling = (parent / f"{module}.py").as_posix()
        sibling_package = (parent / module / "__init__.py").as_posix()
        return _path_exists_without_symlinks(
            root,
            sibling,
        ) or _path_exists_without_symlinks(root, sibling_package)
    if target.startswith("python:"):
        module = target.removeprefix("python:").split(".", 1)[0]
        if module in sys.stdlib_module_names:
            return True
        actual_source = actual_by_canonical.get(source_path, source_path)
        sibling = (
            PurePosixPath(actual_source).parent / f"{module}.py"
        ).as_posix()
        sibling_package = (
            PurePosixPath(actual_source).parent / module / "__init__.py"
        ).as_posix()
        return (
            _path_exists_without_symlinks(root, sibling)
            or _path_exists_without_symlinks(root, sibling_package)
            or _path_exists_without_symlinks(root, f"{module}.py")
            or _path_exists_without_symlinks(root, f"{module}/__init__.py")
        )
    if target.startswith("skill:"):
        return target.removeprefix("skill:") in skill_paths
    if target in ambiguous_canonical_paths:
        return False
    return _path_exists_without_symlinks(
        root,
        actual_by_canonical.get(target, target),
    )


def _path_exists_without_symlinks(root: Path, relative: str) -> bool:
    current = root
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        current /= part
        try:
            metadata = current.lstat()
        except OSError:
            return False
        if current.is_symlink():
            return False
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            return False
    return bool(parts) and (
        stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)
    )


def _load_trusted_registry(root: Path):
    path = root / "System/trusted-mcps.yaml"
    if not path.exists() and not path.is_symlink():
        return None
    from core.utils.trust_registry import load_trusted_mcp_registry

    return load_trusted_mcp_registry(root)


def _assign_groups(
    root: Path,
    records: tuple[CustomizationRecord, ...],
    edges: tuple[ReferenceEdge, ...],
    skill_paths: Mapping[str, str],
    actual_by_canonical: Mapping[str, str],
    ambiguous_canonical_paths: frozenset[str],
) -> tuple[AssessmentAssignment, ...]:
    edges_by_source: dict[str, list[ReferenceEdge]] = {}
    for edge in edges:
        edges_by_source.setdefault(edge.source_path, []).append(edge)
    assignments: list[AssessmentAssignment] = []
    for record in records:
        primary = record.source_paths[0]
        outgoing = edges_by_source.get(primary, [])
        missing_target = any(
            not _target_resolves(
                root,
                edge.source_path,
                edge.target,
                skill_paths,
                actual_by_canonical,
                ambiguous_canonical_paths,
            )
            for edge in outgoing
        )
        write_verdict = portable_contract.update_write_verdict(
            primary,
            exists=record.kind is not CustomizationKind.DELETED_SHIPPED_FILE,
        )
        if (
            record.live.model_readability in {"restricted", "excluded"}
            or missing_target
            or write_verdict.action == "deny"
        ):
            group = AssessmentGroup.BLOCKED
        elif write_verdict.action == "unclassified-never-write":
            group = AssessmentGroup.NEEDS_INTERPRETATION
        elif write_verdict.allowed:
            group = AssessmentGroup.UPDATE_REPLACEABLE_LOCATION
        else:
            group = AssessmentGroup.UPDATE_UNTOUCHED_LOCATION
        assignments.append(AssessmentAssignment(record.customization_id, group))
    return tuple(sorted(assignments, key=lambda item: item.customization_id))


def discover(vault_root: Path) -> DiscoveryResult:
    """Discover customizations without following links, caching, or writing."""
    root = Path(vault_root)
    inventory = build_inventory(root, max_hash_bytes=MAX_SOURCE_BYTES)
    customization_report = detect_customizations(inventory.entries)
    if inventory.baseline.identity_state != "VERIFIED":
        return DiscoveryResult(inventory, (), (), (), (), False)

    entries_by_path = {entry.actual_path: entry for entry in inventory.entries}
    exclusions: dict[tuple[str, str], AssessmentExclusion] = {}
    for entry in inventory.entries:
        dependency_root = _dependency_root(entry.actual_path)
        if dependency_root is not None:
            exclusion = AssessmentExclusion(
                dependency_root,
                "dependency-tree-excluded",
            )
            exclusions[(exclusion.path, exclusion.reason)] = exclusion
    candidate_paths = {
        divergence.path
        for divergence in customization_report.divergences
        if divergence.state in {"stock-modified", "stock-missing"}
    }
    candidate_paths.update(
        entry.actual_path
        for entry in inventory.entries
        if _is_behavior_addition(entry, inventory.baseline.manifest_paths)
    )
    candidate_paths = {
        path for path in candidate_paths if _dependency_root(path) is None
    }

    registry = _load_trusted_registry(root)
    trusted_hashes: dict[str, str] = {}
    if registry is not None and registry.invalid_reason is None:
        for entry in registry.entries.values():
            trusted_hashes[entry.file] = entry.sha256
            if entry.file in entries_by_path:
                candidate_paths.add(entry.file)
    elif registry is not None and registry.invalid_reason is not None:
        exclusion = AssessmentExclusion(
            "System/trusted-mcps.yaml",
            "invalid-trust-registry",
        )
        exclusions[(exclusion.path, exclusion.reason)] = exclusion

    actuals_by_canonical: dict[str, list[str]] = {}
    for entry in inventory.entries:
        actuals_by_canonical.setdefault(entry.canonical_path, []).append(
            entry.actual_path
        )
    colliding_canonical_paths = frozenset(
        canonical
        for canonical, actuals in actuals_by_canonical.items()
        if len(set(actuals)) > 1
    )
    for canonical in colliding_canonical_paths:
        exclusion = AssessmentExclusion(canonical, "canonical-path-collision")
        exclusions[(exclusion.path, exclusion.reason)] = exclusion
    candidate_paths = {
        path
        for path in candidate_paths
        if entries_by_path[path].canonical_path not in colliding_canonical_paths
    }

    skill_paths = _skill_paths(inventory.entries)
    raw_by_path: dict[str, bytes] = {}
    live_by_path: dict[str, LiveInfo] = {}

    def inspect(path: str) -> None:
        if path in live_by_path:
            return
        entry = entries_by_path.get(path)
        if entry is None:
            return
        if entry.canonical_path in colliding_canonical_paths:
            return
        live, raw, exclusion = _safe_live(root, entry)
        if path in trusted_hashes and live.model_readability == "readable":
            if live.sha256 == trusted_hashes[path]:
                live = LiveInfo(live.sha256, None, "hash-only")
            else:
                live = LiveInfo(None, live.byte_size, "excluded")
                exclusion = AssessmentExclusion(path, "trust-hash-mismatch")
                raw = None
        live_by_path[path] = live
        if raw is not None:
            raw_by_path[path] = raw
        if exclusion is not None:
            exclusions[(exclusion.path, exclusion.reason)] = exclusion

    for path in sorted(candidate_paths):
        inspect(path)

    all_edges: dict[str, ReferenceEdge] = {}
    processed: set[str] = set()
    while True:
        pending = sorted(set(candidate_paths) - processed)
        if not pending:
            break
        for path in pending:
            processed.add(path)
            raw = raw_by_path.get(path)
            if raw is None:
                continue
            for edge in extract_reference_edges(path, raw, skill_paths=skill_paths):
                all_edges[edge.edge_id] = edge
                target_entry = entries_by_path.get(edge.target)
                if (
                    target_entry is not None
                    and target_entry.kind in {"file", "symlink"}
                    and PurePosixPath(edge.target).suffix.lower() in SCRIPT_SUFFIXES
                ):
                    candidate_paths.add(edge.target)
                    inspect(edge.target)

    edges = tuple(sorted(all_edges.values(), key=lambda edge: edge.edge_id))
    canonical_by_actual = {
        entry.actual_path: entry.canonical_path for entry in inventory.entries
    }
    canonical_edges_by_id: dict[str, ReferenceEdge] = {}
    for edge in edges:
        canonical = ReferenceEdge.create(
            canonical_by_actual.get(edge.source_path, edge.source_path),
            canonical_by_actual.get(edge.target, edge.target),
            edge.edge_kind,
            edge.confidence,
        )
        canonical_edges_by_id[canonical.edge_id] = canonical
    canonical_edges = tuple(
        sorted(canonical_edges_by_id.values(), key=lambda edge: edge.edge_id)
    )
    edge_ids_by_source: dict[str, list[str]] = {}
    for edge in canonical_edges:
        edge_ids_by_source.setdefault(edge.source_path, []).append(edge.edge_id)

    records: list[CustomizationRecord] = []
    for path in sorted(candidate_paths):
        entry = entries_by_path.get(path)
        live = live_by_path.get(path)
        if entry is None or live is None:
            continue
        kind = (
            CustomizationKind.CUSTOM_MCP
            if path in trusted_hashes
            else _kind_for(entry)
        )
        records.append(
            CustomizationRecord.create(
                kind,
                (entry.canonical_path,),
                BaselineInfo(
                    inventory.baseline.release_version,
                    inventory.baseline.expected_sha256(entry.canonical_path),
                ),
                live,
                CustomizationEvidence(
                    entry.release_state,
                    tuple(sorted(edge_ids_by_source.get(entry.canonical_path, []))),
                ),
            )
        )
    ordered_records = tuple(sorted(records, key=lambda record: record.source_paths))

    groups = _assign_groups(
        root,
        ordered_records,
        canonical_edges,
        skill_paths,
        {
            entry.canonical_path: entry.actual_path
            for entry in inventory.entries
            if entry.canonical_path not in colliding_canonical_paths
        },
        colliding_canonical_paths,
    )
    accounted_paths = set(candidate_paths)
    for entry in inventory.entries:
        if (
            entry.kind in {"file", "symlink"}
            and entry.actual_path in inventory.unproven_paths
            and entry.actual_path not in accounted_paths
        ):
            exclusion = AssessmentExclusion(
                entry.actual_path,
                "release-identity-unproved",
            )
            exclusions[(exclusion.path, exclusion.reason)] = exclusion
    complete = (
        inventory.complete
        and not exclusions
        and not inventory.errors
        and (registry is None or registry.invalid_reason is None)
    )
    return DiscoveryResult(
        inventory,
        ordered_records,
        canonical_edges,
        groups,
        tuple(sorted(exclusions.values(), key=lambda item: (item.path, item.reason))),
        complete,
    )


__all__ = ["DiscoveryResult", "discover"]
