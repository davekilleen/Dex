"""Safe in-process write primitives for Dex entity pages.

The optimistic concurrency guard re-reads and compares content immediately before
the atomic replacement. It intentionally skips on a mismatch. A residual
read-to-replace TOCTOU window remains; this module does not claim transactional
exclusion from another writer during that final window.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

from core.paths import COMPANIES_DIR, PEOPLE_DIR

from .contract import (
    RELATIONSHIP_TYPES,
    _normalise_relationships,
    _split_frontmatter,
    ensure_region,
    merge_frontmatter_text,
    ordered_region_slugs,
    render_relationships,
    render_update_log,
    replace_machine_region,
)

_UTF8_BOM = b"\xef\xbb\xbf"
ResultStatus = Literal[
    "updated",
    "noop",
    "conflict",
    "quarantined",
    "missing",
    "created",
    "exists",
    "unsafe_path",
]


@dataclass(frozen=True, slots=True)
class Result:
    """Outcome of one entity-page write attempt."""

    status: ResultStatus
    changed: bool
    fingerprint: str | None = None


def _fingerprint(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def fingerprint_page(path: str | Path) -> str:
    """Return the SHA-256 fingerprint of the page's exact on-disk bytes."""
    return _fingerprint(Path(path).read_bytes())


def _has_symlink_component(path: Path) -> bool:
    candidate = path
    while True:
        if candidate.is_symlink():
            return True
        if candidate.parent == candidate:
            return False
        candidate = candidate.parent


def _safe_within(path: Path, allowed_root: Path | None) -> bool:
    if allowed_root is None:
        return not _has_symlink_component(Path(os.path.abspath(path)))
    absolute_path = Path(os.path.abspath(path))
    absolute_root = Path(os.path.abspath(allowed_root))
    try:
        absolute_path.relative_to(absolute_root)
        path.resolve(strict=False).relative_to(
            allowed_root.resolve(strict=False)
        )
    except ValueError:
        return False
    candidate = absolute_path
    while True:
        if candidate.is_symlink():
            return False
        if candidate == absolute_root:
            return True
        candidate = candidate.parent


def _safe_mutation_path(path: Path) -> bool:
    """Reject symlinks while tolerating aliases above a canonical entity root."""
    for root in (PEOPLE_DIR, COMPANIES_DIR):
        if _safe_within(path, root):
            return True
    return _safe_within(path, None)


def _decode_page(content: bytes) -> tuple[str, bool]:
    had_bom = content.startswith(_UTF8_BOM)
    payload = content[len(_UTF8_BOM) :] if had_bom else content
    return payload.decode("utf-8"), had_bom


def _encode_page(text: str, *, bom: bool) -> bytes:
    payload = text.encode("utf-8")
    return _UTF8_BOM + payload if bom else payload


def _atomic_replace(path: Path, content: bytes) -> None:
    """Replace an existing page atomically while preserving its file mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.chmod(temporary_name, existing_mode)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _replace_if_fingerprint_matches(
    path: Path,
    expected_fingerprint: str,
    content: bytes,
) -> bool:
    """Re-read just before replacement and skip if the page changed."""
    try:
        latest = path.read_bytes()
    except FileNotFoundError:
        return False
    if _fingerprint(latest) != expected_fingerprint:
        return False
    _atomic_replace(path, content)
    return True


def _build_mutation(
    page_path: Path,
    original_bytes: bytes,
    *,
    replacement_content: str | None,
    field_changes: Mapping[str, Any] | None,
    ensure_regions: Iterable[str] | None,
    region_projections: Mapping[str, str] | None,
) -> tuple[bytes | None, bool]:
    text, had_bom = _decode_page(original_bytes)
    _frontmatter, _body, _had_frontmatter, quarantined = _split_frontmatter(
        text
    )
    if quarantined:
        return None, True

    updated = text if replacement_content is None else replacement_content
    if updated.startswith("\ufeff"):
        updated = updated[1:]
    if field_changes:
        merged = merge_frontmatter_text(page_path, updated, field_changes)
        if merged is None:
            return None, True
        updated = merged
    for slug in ordered_region_slugs(ensure_regions or ()):
        updated = ensure_region(updated, slug)
    for slug in ordered_region_slugs((region_projections or {}).keys()):
        updated = replace_machine_region(
            updated,
            slug,
            (region_projections or {})[slug],
        )
    return _encode_page(updated, bom=had_bom), False


def mutate_page(
    path: str | Path,
    base_fingerprint: str,
    *,
    replacement_content: str | None = None,
    field_changes: Mapping[str, Any] | None = None,
    ensure_regions: Iterable[str] | None = None,
    region_projections: Mapping[str, str] | None = None,
) -> Result:
    """Apply one composite mutation and perform at most one atomic replacement.

    The page is read once as the transformation snapshot. Field changes, ordered
    region insertion, and region projections all build one final byte string.
    A separate guard re-read immediately before replacement detects intervening
    edits and returns ``conflict`` instead of knowingly overwriting them.
    """
    page_path = Path(path)
    if not _safe_mutation_path(page_path):
        return Result("unsafe_path", False)
    try:
        original_bytes = page_path.read_bytes()
    except FileNotFoundError:
        return Result("missing", False)
    current_fingerprint = _fingerprint(original_bytes)
    if current_fingerprint != base_fingerprint:
        return Result("conflict", False, current_fingerprint)

    updated_bytes, quarantined = _build_mutation(
        page_path,
        original_bytes,
        replacement_content=replacement_content,
        field_changes=field_changes,
        ensure_regions=ensure_regions,
        region_projections=region_projections,
    )
    if quarantined:
        return Result("quarantined", False, current_fingerprint)
    assert updated_bytes is not None
    if updated_bytes == original_bytes:
        return Result("noop", False, current_fingerprint)
    if not _replace_if_fingerprint_matches(
        page_path,
        current_fingerprint,
        updated_bytes,
    ):
        return Result("conflict", False)
    return Result("updated", True, _fingerprint(updated_bytes))


def _region_content(text: str, slug: str) -> str:
    start = f"<!-- dex:auto:{slug} -->"
    end = "<!-- /dex:auto -->"
    start_index = text.find(start)
    if start_index < 0:
        return ""
    content_start = start_index + len(start)
    end_index = text.find(end, content_start)
    if end_index < 0:
        return ""
    return text[content_start:end_index].strip("\r\n")


def _persisted_relationships(
    intent: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if intent.get("kind") != "relationship":
        raise ValueError("relationship intent kind must be relationship")
    candidates = intent.get("relationships")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("relationship intent requires relationships")

    persisted = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("relationship intent entries must be objects")
        if candidate.get("confidence") != "suggested":
            raise ValueError("relationship confidence must be suggested")
        source = candidate.get("source")
        if not isinstance(source, Mapping):
            raise ValueError("relationship source must be an object")
        persisted.append(
            {
                "type": candidate.get("type"),
                "target": candidate.get("target_ref"),
                "status": "suggested",
                "source": {
                    "kind": source.get("kind"),
                    "id": source.get("id"),
                },
                "date": source.get("date"),
            }
        )
    normalised = _normalise_relationships(persisted, strict=True)
    assert normalised is not None
    return normalised


def _relationships_from_text(text: str) -> list[dict[str, Any]]:
    frontmatter, _body, _had_frontmatter, quarantined = _split_frontmatter(
        text
    )
    if quarantined or frontmatter is None:
        return []
    return (
        _normalise_relationships(frontmatter.get("relationships"))
        or []
    )


def _relationship_sort_key(
    relationship: Mapping[str, Any],
) -> tuple[int, str, str, str]:
    return (
        RELATIONSHIP_TYPES.index(str(relationship["type"])),
        str(relationship["target"]).casefold(),
        str(relationship["target"]),
        str(relationship["date"]),
    )


def mutate_relationships(
    path: str | Path,
    base_fingerprint: str,
    intent: Mapping[str, Any],
) -> Result:
    """Materialize one relationship intent through the canonical page CAS."""
    page_path = Path(path)
    original_bytes = page_path.read_bytes()
    original, _had_bom = _decode_page(original_bytes)
    current = _relationships_from_text(original)
    incoming = _persisted_relationships(intent)

    by_edge = {
        (relationship["type"], relationship["target"].casefold()):
        relationship
        for relationship in current
    }
    for relationship in incoming:
        key = (
            relationship["type"],
            relationship["target"].casefold(),
        )
        by_edge.setdefault(key, relationship)
    proposed = sorted(by_edge.values(), key=_relationship_sort_key)

    preview = merge_frontmatter_text(
        page_path,
        original,
        {"relationships": proposed},
    )
    if preview is None:
        return mutate_page(
            page_path,
            base_fingerprint,
            field_changes={"relationships": proposed},
        )
    effective = _relationships_from_text(preview)
    current_edges = {
        (relationship["type"], relationship["target"].casefold())
        for relationship in current
    }
    newly_written = [
        relationship
        for relationship in effective
        if (
            relationship["type"],
            relationship["target"].casefold(),
        )
        not in current_edges
    ]

    existing_update_lines = _region_content(
        original,
        "update-log",
    ).splitlines()
    provenance = render_update_log(
        relationship_provenance=[
            {
                "date": relationship["date"],
                "type": relationship["type"],
                "target_ref": relationship["target"],
            }
            for relationship in newly_written
        ]
    )
    update_lines = sorted(
        {
            line
            for line in [*existing_update_lines, *provenance.splitlines()]
            if line
        }
    )
    return mutate_page(
        page_path,
        base_fingerprint,
        field_changes={"relationships": proposed},
        ensure_regions=("relationships", "update-log"),
        region_projections={
            "relationships": render_relationships(effective),
            "update-log": "\n".join(update_lines),
        },
    )


def create_page_if_absent(
    path: str | Path,
    content: str,
    *,
    allowed_root: str | Path | None = None,
) -> Result:
    """Create a complete UTF-8 page exclusively, never replacing an existing path."""
    page_path = Path(path)
    root = Path(allowed_root) if allowed_root is not None else None
    if not _safe_within(page_path, root):
        return Result("unsafe_path", False)
    page_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    payload = content.encode("utf-8")
    try:
        descriptor = os.open(page_path, flags, 0o666)
    except FileExistsError:
        return Result("exists", False)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
    except BaseException:
        try:
            page_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return Result("created", True, _fingerprint(payload))


def upsert_frontmatter(
    path: str | Path,
    fields: dict[str, Any],
    *,
    dry_run: bool = False,
) -> bool:
    """Compatibility wrapper for the pre-engine boolean upsert API."""
    page_path = Path(path)
    original_bytes = page_path.read_bytes()
    if dry_run:
        updated, quarantined = _build_mutation(
            page_path,
            original_bytes,
            replacement_content=None,
            field_changes=fields,
            ensure_regions=None,
            region_projections=None,
        )
        return not quarantined and updated != original_bytes
    result = mutate_page(
        page_path,
        _fingerprint(original_bytes),
        field_changes=fields,
    )
    return result.changed


def replace_machine_region_in_file(
    path: str | Path,
    slug: str,
    new_content: str,
) -> bool:
    """Compatibility wrapper for the pre-engine boolean region-write API."""
    page_path = Path(path)
    base_fingerprint = fingerprint_page(page_path)
    return mutate_page(
        page_path,
        base_fingerprint,
        region_projections={slug: new_content},
    ).changed
