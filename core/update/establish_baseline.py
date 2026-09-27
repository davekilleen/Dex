"""Establish a verified release baseline for an UNKNOWN-identity vault.

DEX-135 / davekilleen/dex-feedback#14: older Dex forks whose history
predates the release catalog have no catalog/manifest pair, so
``load_release_baseline`` stays ``UNKNOWN`` and the guided update never
opens. This module is the explicit conversion path:

- The version must be an official ``dist/release/v*`` tag (the release
  catalog of known releases), never a guessed or user-typed identity.
- ``--dry-run`` classifies every official file against that version and
  writes nothing.
- Applying writes only the generated version records (catalog, manifest,
  optional hash table, and an audit receipt). User notes, edits, and
  other content are never in the write set.
- Consent is collected by the CLI; this module never reads a yes from
  flags, environment variables, or tool arguments.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from core import portable_contract
from core.lifecycle.catalog import (
    HASH_TABLE_PATH,
    MAX_HASH_TABLE_BYTES,
    build_release_hash_table_document,
    canonical_catalog_bytes,
    canonical_hash_table_bytes,
    loads_catalog,
    release_bytes_match,
    with_catalog_identity,
)
from core.lifecycle.customizations import (
    CATALOG_CANDIDATES,
    MANIFEST_PATH,
    MAX_CATALOG_BYTES,
    MAX_MANIFEST_BYTES,
)
from core.lifecycle.filesystem import FilesystemInspectionError, bounded_read
from core.update.anchor_generation import (
    AnchorGenerationError,
    VerifiedAnchorSource,
    verify_local_release_tag,
)
from core.update.apply_update import (
    BRAIN_RELATIVE,
    RELEASE_TAG,
    _blob,
    _brain_text,
    _verify_official_origin,
)

CATALOG_RELATIVE = "System/.release-catalog.json"
RECEIPT_RELATIVE = "System/.dex/established-baseline.receipt.json"
RECEIPT_VERSION = 1
MAX_RECEIPT_BYTES = 64 * 1024
_PREVIEW_READ_BYTES = 16 * 1024 * 1024
_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
)


class BaselineEstablishmentError(RuntimeError):
    """No baseline could be resolved or written safely; nothing was mutated."""


@dataclass(frozen=True)
class OfficialBaseline:
    """Official catalog/manifest bytes for one validated release version."""

    version: str
    tag: str
    tag_object: str
    commit: str
    tree: str
    manifest_bytes: bytes
    catalog_bytes: bytes
    hash_table_bytes: bytes | None
    file_hashes: dict[str, str]
    inferred: bool

    @property
    def preview_sha256(self) -> str:
        hasher = hashlib.sha256()
        hasher.update(self.manifest_bytes)
        hasher.update(self.catalog_bytes)
        hasher.update(self.hash_table_bytes or b"")
        return hasher.hexdigest()


@dataclass(frozen=True)
class InventoryRow:
    path: str
    classification: str


@dataclass(frozen=True)
class BaselinePreview:
    version: str
    tag: str
    inferred: bool
    rows: tuple[InventoryRow, ...]
    counts: dict[str, int]
    preview_sha256: str

    @property
    def customization_paths(self) -> tuple[str, ...]:
        return tuple(
            row.path
            for row in self.rows
            if row.classification in {"release-modified", "user-owned-addition"}
        )


def _normalize_version(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("v") or text.startswith("V"):
        text = text[1:]
    if _SEMVER.fullmatch(text) is None:
        raise BaselineEstablishmentError(
            f"{raw!r} is not a Dex version number (use something like 1.64.0)"
        )
    return text


def _evidence_git_dirs(vault_root: Path) -> tuple[Path, ...]:
    """Local stores that may hold official release tags.

    Prefer the split brain store when present; fall back to the vault's own
    ``.git`` so older combined-history forks can still prove a tag. Symlinked
    stores are skipped — the update lane refuses those for the same reason.
    """
    root = Path(vault_root).resolve()
    found: list[Path] = []
    for relative in (BRAIN_RELATIVE, Path(".git")):
        candidate = root / relative
        try:
            if candidate.is_symlink() or not candidate.is_dir():
                continue
        except OSError:
            continue
        found.append(candidate)
    return tuple(found)


def _official_origin_git_dirs(vault_root: Path) -> tuple[Path, ...]:
    trusted: list[Path] = []
    for git_dir in _evidence_git_dirs(vault_root):
        try:
            _verify_official_origin(vault_root, git_dir)
        except Exception:
            continue
        trusted.append(git_dir)
    return tuple(trusted)


def _list_official_tags(vault_root: Path, git_dir: Path) -> tuple[str, ...]:
    try:
        listing = _brain_text(
            vault_root,
            git_dir,
            "for-each-ref",
            "--format=%(refname:strip=2)",
            "refs/tags/dist/release/",
        )
    except (RuntimeError, OSError):
        return ()
    names: list[str] = []
    for line in listing.splitlines():
        if RELEASE_TAG.fullmatch(line) is not None:
            names.append(line)
    return tuple(names)


def list_official_versions(vault_root: Path) -> tuple[str, ...]:
    """Versions that have official local tag evidence (the release catalog)."""
    versions: set[str] = set()
    for git_dir in _official_origin_git_dirs(vault_root):
        for tag in _list_official_tags(vault_root, git_dir):
            match = RELEASE_TAG.fullmatch(tag)
            if match is not None:
                versions.add(match.group("version"))
    return tuple(sorted(versions, key=_version_tuple))


def _version_tuple(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.split(".")
    return int(major), int(minor), int(patch)


def _verify_tag(
    vault_root: Path, git_dir: Path, tag: str, version: str
) -> VerifiedAnchorSource:
    try:
        return verify_local_release_tag(
            vault_root,
            git_dir=git_dir,
            tag=tag,
            claimed_version=version,
            require_installed_manifest_match=False,
        )
    except AnchorGenerationError as error:
        raise BaselineEstablishmentError(str(error)) from error


def _locate_official_source(
    vault_root: Path, version: str
) -> tuple[Path, VerifiedAnchorSource]:
    last_error: str | None = None
    for git_dir in _official_origin_git_dirs(vault_root):
        for tag in _list_official_tags(vault_root, git_dir):
            match = RELEASE_TAG.fullmatch(tag)
            if match is None or match.group("version") != version:
                continue
            try:
                return git_dir, _verify_tag(vault_root, git_dir, tag, version)
            except BaselineEstablishmentError as error:
                last_error = str(error)
                continue
    if last_error:
        raise BaselineEstablishmentError(last_error)
    available = list_official_versions(vault_root)
    if available:
        listed = ", ".join(f"v{item}" for item in available)
        raise BaselineEstablishmentError(
            f"v{version} is not a version Dex has an official record for "
            f"on this computer. Official versions here: {listed}."
        )
    raise BaselineEstablishmentError(
        f"v{version} is not a version Dex has an official record for on "
        "this computer, and no official release records were found locally."
    )


def _blob_bytes(vault_root: Path, git_dir: Path, object_id: str) -> bytes:
    try:
        return _blob(vault_root, git_dir, object_id)
    except (RuntimeError, OSError) as error:
        raise BaselineEstablishmentError(
            f"official release file is unreadable: {error}"
        ) from error


def _brain_file_hashes(
    vault_root: Path, git_dir: Path, source: VerifiedAnchorSource
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for entry in source.entries:
        if entry.path in {CATALOG_RELATIVE, HASH_TABLE_PATH, *CATALOG_CANDIDATES}:
            continue
        try:
            resolution = portable_contract.resolve(entry.path)
        except portable_contract.ContractViolation:
            continue
        if resolution.denied or resolution.ownership != "brain":
            continue
        raw = _blob_bytes(vault_root, git_dir, entry.object_id)
        hashes[entry.path] = hashlib.sha256(raw).hexdigest()
    return dict(sorted(hashes.items()))


def _manifest_bytes_from_paths(paths: set[str]) -> bytes:
    ordered = sorted(paths)
    if ordered != sorted(set(ordered)):
        raise BaselineEstablishmentError("baseline manifest paths are not unique")
    return "".join(f"{path}\n" for path in ordered).encode("utf-8")


def _catalog_and_table_from_source(
    vault_root: Path, git_dir: Path, source: VerifiedAnchorSource
) -> tuple[bytes, bytes, bytes | None, dict[str, str]]:
    """Prefer the tag's own catalog/manifest pair; otherwise derive them."""
    by_path = {entry.path: entry for entry in source.entries}
    file_hashes = _brain_file_hashes(vault_root, git_dir, source)

    official_catalog_entry = by_path.get(CATALOG_RELATIVE) or next(
        (by_path[path] for path in CATALOG_CANDIDATES if path in by_path),
        None,
    )
    official_manifest_entry = by_path.get(MANIFEST_PATH)
    if official_catalog_entry is not None and official_manifest_entry is not None:
        catalog_bytes = _blob_bytes(
            vault_root, git_dir, official_catalog_entry.object_id
        )
        manifest_bytes = _blob_bytes(
            vault_root, git_dir, official_manifest_entry.object_id
        )
        try:
            catalog = loads_catalog(
                catalog_bytes.decode("utf-8"), manifest_bytes=manifest_bytes
            )
        except (Exception, UnicodeDecodeError):
            catalog = None
        if catalog is not None and catalog.release.version == source.version:
            table_bytes: bytes | None = None
            official_hashes = dict(file_hashes)
            for item in catalog.items:
                for file in item.files:
                    official_hashes.setdefault(file.path, file.sha256)
            binding = catalog.release.hash_table
            if binding is not None and binding.path in by_path:
                table_bytes = _blob_bytes(
                    vault_root, git_dir, by_path[binding.path].object_id
                )
            return (
                manifest_bytes,
                catalog_bytes,
                table_bytes,
                dict(sorted(official_hashes.items())),
            )

    if len(source.commit) != 40:
        raise BaselineEstablishmentError(
            "official release commit is not a 40-character identity; "
            "refusing to mint a catalog"
        )
    table_document = build_release_hash_table_document(
        release_version=source.version,
        source_commit=source.commit,
        files=file_hashes,
    )
    table_bytes = canonical_hash_table_bytes(table_document)
    manifest_paths = {entry.path for entry in source.entries}
    manifest_paths.add(MANIFEST_PATH)
    manifest_paths.add(CATALOG_RELATIVE)
    manifest_paths.add(HASH_TABLE_PATH)
    manifest_bytes = _manifest_bytes_from_paths(manifest_paths)
    catalog_document = with_catalog_identity(
        {
            "catalog_version": 2,
            "release": {
                "version": source.version,
                "channel": "release",
                "immutable_distribution_tag_pattern": (
                    f"dist/release/v{source.version}-<release-commit-prefix>"
                ),
                "source_commit": source.commit,
                "manifest": {
                    "path": MANIFEST_PATH,
                    "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                },
                "hash_table": {
                    "path": HASH_TABLE_PATH,
                    "sha256": hashlib.sha256(table_bytes).hexdigest(),
                },
            },
            "items": [],
            "integrity": {"catalog_sha256": "0" * 64, "signatures": []},
        }
    )
    return (
        manifest_bytes,
        canonical_catalog_bytes(catalog_document),
        table_bytes,
        file_hashes,
    )


def resolve_official_baseline(
    vault_root: Path,
    version: str,
    *,
    inferred: bool = False,
) -> OfficialBaseline:
    """Load official bytes for ``version`` or refuse with a named reason."""
    normalized = _normalize_version(version)
    git_dir, source = _locate_official_source(vault_root, normalized)
    manifest_bytes, catalog_bytes, table_bytes, file_hashes = (
        _catalog_and_table_from_source(vault_root, git_dir, source)
    )
    return OfficialBaseline(
        version=source.version,
        tag=source.tag,
        tag_object=source.tag_object,
        commit=source.commit,
        tree=source.tree,
        manifest_bytes=manifest_bytes,
        catalog_bytes=catalog_bytes,
        hash_table_bytes=table_bytes,
        file_hashes=file_hashes,
        inferred=inferred,
    )


def infer_best_match(vault_root: Path) -> OfficialBaseline:
    """Pick the official version whose files match this vault most closely."""
    versions = list_official_versions(vault_root)
    if not versions:
        raise BaselineEstablishmentError(
            "Dex couldn't find an official version record on this computer "
            "to compare these files against."
        )
    scored: list[tuple[int, tuple[int, int, int], OfficialBaseline]] = []
    for version in versions:
        baseline = resolve_official_baseline(vault_root, version, inferred=True)
        matches = sum(
            1
            for path, expected in baseline.file_hashes.items()
            if _disk_matches(vault_root, path, expected)
        )
        scored.append((matches, _version_tuple(version), baseline))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_matches, _version, best = scored[0]
    if best_matches == 0:
        raise BaselineEstablishmentError(
            "Dex compared the official version records on this computer and "
            "none of them match the files here. Pass --baseline VERSION if "
            "you know which official version to start from."
        )
    return best


def _disk_matches(vault_root: Path, relative: str, expected_sha256: str) -> bool:
    try:
        raw = bounded_read(Path(vault_root), relative, max_bytes=_PREVIEW_READ_BYTES)
    except FilesystemInspectionError:
        return False
    return release_bytes_match(expected_sha256, raw)


def _existing_manifest_paths(vault_root: Path) -> frozenset[str]:
    try:
        raw = bounded_read(
            Path(vault_root), MANIFEST_PATH, max_bytes=MAX_MANIFEST_BYTES
        )
    except FilesystemInspectionError:
        return frozenset()
    text = raw.replace(b"\r\n", b"\n").decode("utf-8", errors="replace")
    return frozenset(line for line in text.splitlines() if line and "\\" not in line)


def preview_against_baseline(
    vault_root: Path, baseline: OfficialBaseline
) -> BaselinePreview:
    """Full file-by-file inventory against the official baseline. Read-only."""
    root = Path(vault_root)
    rows: list[InventoryRow] = []
    counts = {
        "release-pristine": 0,
        "release-modified": 0,
        "missing-from-disk": 0,
        "unreadable": 0,
        "user-owned-addition": 0,
    }
    official_paths = set(baseline.file_hashes)
    for path, expected in sorted(baseline.file_hashes.items()):
        target = root / path
        try:
            present = target.is_symlink() or target.exists()
        except OSError:
            present = True
        if not present:
            rows.append(InventoryRow(path, "missing-from-disk"))
            counts["missing-from-disk"] += 1
            continue
        try:
            raw = bounded_read(root, path, max_bytes=_PREVIEW_READ_BYTES)
        except FilesystemInspectionError:
            rows.append(InventoryRow(path, "unreadable"))
            counts["unreadable"] += 1
            continue
        if release_bytes_match(expected, raw):
            rows.append(InventoryRow(path, "release-pristine"))
            counts["release-pristine"] += 1
        else:
            rows.append(InventoryRow(path, "release-modified"))
            counts["release-modified"] += 1

    extra_candidates = _existing_manifest_paths(root) - official_paths
    extra_candidates -= {MANIFEST_PATH, CATALOG_RELATIVE, HASH_TABLE_PATH, *CATALOG_CANDIDATES}
    for path in sorted(extra_candidates):
        try:
            resolution = portable_contract.resolve(path)
        except portable_contract.ContractViolation:
            continue
        if resolution.denied or resolution.ownership != "brain":
            continue
        target = root / path
        try:
            present = (not target.is_symlink()) and target.is_file()
        except OSError:
            continue
        if not present:
            continue
        rows.append(InventoryRow(path, "user-owned-addition"))
        counts["user-owned-addition"] += 1

    return BaselinePreview(
        version=baseline.version,
        tag=baseline.tag,
        inferred=baseline.inferred,
        rows=tuple(rows),
        counts=counts,
        preview_sha256=baseline.preview_sha256,
    )


def _current_file_sha256(vault_root: Path, relative: str, *, max_bytes: int) -> str | None:
    target = Path(vault_root) / relative
    try:
        present = target.is_symlink() or target.exists()
    except OSError:
        present = True
    if not present:
        return None
    try:
        raw = bounded_read(Path(vault_root), relative, max_bytes=max_bytes)
    except FilesystemInspectionError as error:
        raise BaselineEstablishmentError(
            f"existing {relative} cannot be safely replaced: {error}"
        ) from error
    return hashlib.sha256(raw).hexdigest()


def write_established_baseline(
    vault_root: Path,
    baseline: OfficialBaseline,
    *,
    previewed_sha256: str,
    clock=time.time,
) -> dict[str, object]:
    """Persist identity records in one ``establish-baseline`` transaction.

    Writes only generated version paperwork. User files are never planned.
    The written catalog/manifest/hash-table bytes must hash to the preview
    digest; anything else refuses and leaves the vault untouched.
    """
    extras = [
        path
        for path in CATALOG_CANDIDATES
        if path != CATALOG_RELATIVE and (Path(vault_root) / path).is_file()
    ]
    if extras:
        raise BaselineEstablishmentError(
            f"this vault already has a release catalog at {extras[0]}; "
            "Dex won't add a second one"
        )
    if (
        not isinstance(previewed_sha256, str)
        or _HEX_SHA256_RE.fullmatch(previewed_sha256) is None
    ):
        raise BaselineEstablishmentError("previewed baseline digest is malformed")
    digest = baseline.preview_sha256
    if digest != previewed_sha256:
        raise BaselineEstablishmentError(
            "baseline bytes do not match the previewed digest; refusing to write"
        )

    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "kind": "establish-baseline",
        "release": {
            "version": baseline.version,
            "tag": baseline.tag,
            "tag_object": baseline.tag_object,
            "commit": baseline.commit,
            "tree": baseline.tree,
        },
        "catalog_sha256": hashlib.sha256(baseline.catalog_bytes).hexdigest(),
        "manifest_sha256": hashlib.sha256(baseline.manifest_bytes).hexdigest(),
        "hash_table_sha256": (
            hashlib.sha256(baseline.hash_table_bytes).hexdigest()
            if baseline.hash_table_bytes is not None
            else None
        ),
        "preview_sha256": digest,
        "inferred": baseline.inferred,
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock())),
    }
    receipt_bytes = (
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")

    from core.transaction.engine import PlanEntry, Transaction

    planned: list[tuple[str, bytes, int]] = [
        (MANIFEST_PATH, baseline.manifest_bytes, MAX_MANIFEST_BYTES),
        (CATALOG_RELATIVE, baseline.catalog_bytes, MAX_CATALOG_BYTES),
        (RECEIPT_RELATIVE, receipt_bytes, MAX_RECEIPT_BYTES),
    ]
    if baseline.hash_table_bytes is not None:
        planned.append((HASH_TABLE_PATH, baseline.hash_table_bytes, MAX_HASH_TABLE_BYTES))

    caps = {relative: max_bytes for relative, _content, max_bytes in planned}
    entries = []
    for relative, content, max_bytes in planned:
        current = _current_file_sha256(vault_root, relative, max_bytes=max_bytes)
        entries.append(
            PlanEntry(
                relative,
                content,
                mode=0o644 if relative != RECEIPT_RELATIVE else 0o600,
                expected_current_sha256=current,
                expected_absent=current is None,
            )
        )

    transaction = Transaction.begin(
        Path(vault_root),
        entries,
        operation="establish-baseline",
        max_read_bytes_by_relative=caps,
    )
    result = transaction.run()
    result["preview_sha256"] = digest
    result["release_version"] = baseline.version
    return result


__all__ = [
    "BaselineEstablishmentError",
    "BaselinePreview",
    "CATALOG_RELATIVE",
    "InventoryRow",
    "OfficialBaseline",
    "RECEIPT_RELATIVE",
    "infer_best_match",
    "list_official_versions",
    "preview_against_baseline",
    "resolve_official_baseline",
    "write_established_baseline",
]
