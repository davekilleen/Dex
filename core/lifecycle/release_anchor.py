"""The release anchor: tag-proved per-file release hashes, never trusted on presence.

The anchor is the slice-2 evidence artifact of the customization re-anchoring
design (docs/superpowers/specs/2026-09-04-customization-reanchoring-design.md,
built under the conditions of
docs/superpowers/specs/2026-09-05-anchor-seam-adversarial-review.md). It
carries ``path -> sha256`` rows generated exclusively from a release tree that
an origin-pinned annotated ``dist/release/v*`` tag proved (the generation lane
lives in ``core.update.anchor_generation``); this module owns the document
format and the FAIL-CLOSED consumer half:

- The anchor stores paths and hashes only — never file contents (C11). Its
  size is bounded at read time by :data:`MAX_RELEASE_ANCHOR_BYTES`.
- A present anchor is accepted only when its self-hash, its manifest binding,
  and its catalog binding ALL verify against the installed pair (C7). Any
  failure — oversized, malformed, non-UTF-8, symlinked, mismatched — demotes
  to today's behavior with a named error, never an exception, never a
  promotion.
- Anchor rows are restricted to brain-owned manifest paths at merge time
  (C6): a seed-path or runtime-path row is inert, so the user's living files
  (03-Tasks/Tasks.md, System/usage_log.md, ...) never classify ``stock-*``
  because of an anchor.
- The receipt beside the anchor is audit evidence only (C10): nothing in this
  module — or anywhere else — reads the receipt to establish classification
  trust.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from core import portable_contract
from core.lifecycle.catalog import release_bytes_match
from core.lifecycle.filesystem import (
    FilesystemInspectionError,
    bounded_read,
    normalize_relative_path,
)

ANCHOR_VERSION = 1
RELEASE_ANCHOR_PATH = portable_contract.RELEASE_ANCHOR_RELATIVE
RELEASE_ANCHOR_RECEIPT_PATH = portable_contract.RELEASE_ANCHOR_RECEIPT_RELATIVE
# C11: the declared size bound, enforced at every read. ~2,100 whole-tree
# rows measure roughly 350 KB; 4 MiB leaves generous room without ever
# admitting a content-smuggling anchor near the 16 MB catalog class.
MAX_RELEASE_ANCHOR_BYTES = 4 * 1024 * 1024

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HEX_OBJECT = re.compile(r"^[0-9a-f]{40,64}$")
# Shape check for the STORED tag string. The authoritative verification pin
# stays core.update.apply_update.RELEASE_TAG in the generation lane; the
# consumer never treats this string as proof of anything.
_ANCHOR_TAG = re.compile(
    r"^dist/release/v(?P<version>(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*))-(?P<short>[0-9a-f]{7,64})$"
)

_ANCHOR_FIELDS = frozenset({"anchor_version", "release", "bindings", "files", "integrity"})
_RELEASE_FIELDS = frozenset({"version", "tag", "tag_object", "commit", "tree"})
_BINDING_FIELDS = frozenset({"manifest_sha256", "catalog_sha256"})
_INTEGRITY_FIELDS = frozenset({"anchor_sha256"})


class AnchorError(RuntimeError):
    """The anchor document cannot be trusted; callers fail closed to today."""


def _fail(message: str) -> None:
    raise AnchorError(f"release anchor {message}")


def _strict_loads(text: str) -> object:
    def closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for field, value in pairs:
            if field in result:
                _fail(f"repeats JSON field {field!r}")
            result[field] = value
        return result

    def reject_nonfinite(value: str) -> None:
        _fail(f"contains non-finite JSON number {value}")

    try:
        return json.loads(text, object_pairs_hook=closed_object, parse_constant=reject_nonfinite)
    except (TypeError, json.JSONDecodeError) as error:
        _fail(f"JSON cannot be parsed: {error}")
    raise AssertionError("unreachable")


def canonical_anchor_bytes(document: Mapping[str, object]) -> bytes:
    """Exact canonical bytes of one anchor document (what gets written)."""
    try:
        return (
            json.dumps(
                dict(document),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        _fail(f"cannot be serialized canonically: {error}")
    raise AssertionError("unreachable")


def compute_anchor_sha256(document: Mapping[str, object]) -> str:
    """The self-hash: canonical payload with the integrity envelope excluded."""
    payload = {key: value for key, value in document.items() if key != "integrity"}
    return hashlib.sha256(canonical_anchor_bytes(payload)).hexdigest()


def _anchor_relative_path(value: object, context: str) -> str:
    if not isinstance(value, str):
        _fail(f"{context} is not a canonical release-relative path")
    try:
        normalized = normalize_relative_path(value)
    except FilesystemInspectionError:
        _fail(f"{context} is not a canonical release-relative path")
        raise AssertionError("unreachable")
    if normalized != value:
        _fail(f"{context} is not a canonical release-relative path")
    return normalized


def _require_sha256(value: object, context: str) -> str:
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        _fail(f"{context} is not a lowercase sha256")
    assert isinstance(value, str)
    return value


@dataclass(frozen=True)
class ReleaseAnchor:
    """One parsed, binding-verified anchor document."""

    release_version: str
    tag: str
    tag_object: str
    commit: str
    tree: str
    manifest_sha256: str
    catalog_sha256: str
    files: Mapping[str, str]
    anchor_sha256: str


def build_release_anchor_document(
    *,
    release_version: str,
    tag: str,
    tag_object: str,
    commit: str,
    tree: str,
    manifest_sha256: str,
    catalog_sha256: str,
    files: Mapping[str, str],
) -> dict[str, object]:
    """Build one canonical anchor document with its self-hash bound.

    ``files`` maps release-relative paths to the sha256 of their exact
    release-tree bytes — PATHS AND HASHES ONLY, never contents (C11). Row
    filtering to brain-owned paths is the generation lane's job (C6,
    generation-time half); the consumer filters again at merge time.
    """
    match = _ANCHOR_TAG.fullmatch(tag) if isinstance(tag, str) else None
    if match is None:
        _fail("tag is not an immutable dist/release/v* tag")
    assert match is not None
    if not isinstance(release_version, str) or match.group("version") != release_version:
        _fail("tag does not carry the declared release version")
    for context, value in (("tag_object", tag_object), ("commit", commit), ("tree", tree)):
        if not isinstance(value, str) or _HEX_OBJECT.fullmatch(value) is None:
            _fail(f"{context} identity is malformed")
    if not commit.startswith(match.group("short")):
        _fail("tag suffix does not pin the release commit")
    _require_sha256(manifest_sha256, "manifest binding")
    _require_sha256(catalog_sha256, "catalog binding")
    rows: dict[str, str] = {}
    for raw_path, raw_hash in files.items():
        path = _anchor_relative_path(raw_path, "row path")
        rows[path] = _require_sha256(raw_hash, f"row for {path}")
    document: dict[str, object] = {
        "anchor_version": ANCHOR_VERSION,
        "release": {
            "version": release_version,
            "tag": tag,
            "tag_object": tag_object,
            "commit": commit,
            "tree": tree,
        },
        "bindings": {
            "manifest_sha256": manifest_sha256,
            "catalog_sha256": catalog_sha256,
        },
        "files": dict(sorted(rows.items())),
        "integrity": {"anchor_sha256": "0" * 64},
    }
    document["integrity"] = {"anchor_sha256": compute_anchor_sha256(document)}
    return document


def parse_release_anchor(
    raw: bytes,
    *,
    manifest_bytes: bytes,
    catalog_sha256: str,
    release_version: str | None = None,
) -> ReleaseAnchor:
    """Parse an anchor only after every binding proves out; else fail closed.

    The three trust checks — self-hash, manifest binding, catalog binding —
    are each independent (C7): deleting any one must turn its
    red-when-removed test red. ``catalog_sha256`` is the installed catalog's
    verified ``integrity.catalog_sha256`` (its canonical-bytes identity),
    which the caller has already proved against the installed manifest, so a
    valid anchor is strictly subordinate to an already-VERIFIED baseline.
    """
    if not isinstance(raw, bytes):
        _fail("bytes were not supplied as bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        _fail(f"is not UTF-8: {error}")
        raise AssertionError("unreachable")
    document = _strict_loads(text)
    if not isinstance(document, Mapping) or set(document) != _ANCHOR_FIELDS:
        _fail("has an unsupported shape")
    assert isinstance(document, Mapping)
    if document["anchor_version"] != ANCHOR_VERSION:
        _fail("version is unsupported")

    integrity = document["integrity"]
    if not isinstance(integrity, Mapping) or set(integrity) != _INTEGRITY_FIELDS:
        _fail("integrity envelope is malformed")
    declared_self_hash = _require_sha256(integrity["anchor_sha256"], "self-hash")
    # Trust check 1: the self-hash covers the exact canonical payload.
    if compute_anchor_sha256(document) != declared_self_hash:
        _fail("self-hash does not match its canonical payload")

    release = document["release"]
    if not isinstance(release, Mapping) or set(release) != _RELEASE_FIELDS:
        _fail("release identity is malformed")
    version = release["version"]
    tag = release["tag"]
    if not isinstance(version, str) or not version:
        _fail("release version is malformed")
    match = _ANCHOR_TAG.fullmatch(tag) if isinstance(tag, str) else None
    if match is None or match.group("version") != version:
        _fail("tag does not carry the declared release version")
    for context in ("tag_object", "commit", "tree"):
        value = release[context]
        if not isinstance(value, str) or _HEX_OBJECT.fullmatch(value) is None:
            _fail(f"{context} identity is malformed")
    if release_version is not None and version != release_version:
        _fail("declares a different release version than the installed catalog")

    bindings = document["bindings"]
    if not isinstance(bindings, Mapping) or set(bindings) != _BINDING_FIELDS:
        _fail("bindings are malformed")
    manifest_sha256 = _require_sha256(bindings["manifest_sha256"], "manifest binding")
    declared_catalog_sha256 = _require_sha256(bindings["catalog_sha256"], "catalog binding")
    # Trust check 2: the manifest binding must prove the INSTALLED manifest
    # bytes (same CRLF-tolerant policy the catalog binding uses).
    if not isinstance(manifest_bytes, bytes) or not release_bytes_match(
        manifest_sha256, manifest_bytes
    ):
        _fail("manifest binding does not match the installed manifest")
    # Trust check 3: the catalog binding must equal the installed catalog's
    # canonical identity.
    if declared_catalog_sha256 != catalog_sha256:
        _fail("catalog binding does not match the installed catalog")

    files = document["files"]
    if not isinstance(files, Mapping):
        _fail("files must be an object")
    assert isinstance(files, Mapping)
    rows: dict[str, str] = {}
    for raw_path, raw_hash in files.items():
        path = _anchor_relative_path(raw_path, "row path")
        rows[path] = _require_sha256(raw_hash, f"row for {path}")

    return ReleaseAnchor(
        version,
        str(tag),
        str(release["tag_object"]),
        str(release["commit"]),
        str(release["tree"]),
        manifest_sha256,
        declared_catalog_sha256,
        rows,
        declared_self_hash,
    )


def brain_owned_rows(
    files: Mapping[str, str],
    *,
    manifest_paths: frozenset[str],
) -> dict[str, str]:
    """C6, merge-time half: only brain-owned manifest rows may prove bytes.

    ``classify_release_state`` consults expected hashes BEFORE ownership
    branching, so an unfiltered row for a seed path (03-Tasks/Tasks.md) or a
    runtime path (System/usage_log.md) would reclassify the user's living
    file as ``stock-*`` (review §2.2). Every non-brain, denied, unresolvable,
    or manifest-absent row is inert: dropped here, contributing nothing.
    """
    rows: dict[str, str] = {}
    for path, sha256 in files.items():
        if path not in manifest_paths:
            continue
        try:
            resolution = portable_contract.resolve(path)
        except portable_contract.ContractViolation:
            continue
        if resolution.denied or resolution.ownership != "brain":
            continue
        rows[path] = sha256
    return rows


def consume_release_anchor(
    vault_root: Path,
    *,
    manifest_bytes: bytes,
    manifest_paths: frozenset[str],
    catalog_sha256: str,
    release_version: str | None = None,
) -> tuple[str, dict[str, str], tuple[str, ...]]:
    """Read one anchor fail-closed; never raise, never promote.

    Returns ``(state, rows, errors)`` where ``state`` is ``"absent"``
    (no anchor present — silence never promotes and never complains),
    ``"verified"`` (all three bindings proved; ``rows`` carry the brain-owned
    manifest subset), or ``"rejected"`` (present but unprovable; ``rows`` are
    empty and ``errors`` carries exactly one named reason). The receipt path
    is deliberately never opened here: receipts are audit evidence, not trust
    (C10).
    """
    root = Path(vault_root)
    target = root / RELEASE_ANCHOR_PATH
    try:
        present = target.is_symlink() or target.exists()
    except OSError:
        present = True
    if not present:
        return ("absent", {}, ())
    try:
        raw = bounded_read(root, RELEASE_ANCHOR_PATH, max_bytes=MAX_RELEASE_ANCHOR_BYTES)
    except FilesystemInspectionError as error:
        return ("rejected", {}, (f"release anchor is unreadable: {error}",))
    try:
        anchor = parse_release_anchor(
            raw,
            manifest_bytes=manifest_bytes,
            catalog_sha256=catalog_sha256,
            release_version=release_version,
        )
    except AnchorError as error:
        return ("rejected", {}, (str(error),))
    return ("verified", brain_owned_rows(anchor.files, manifest_paths=manifest_paths), ())


__all__ = [
    "ANCHOR_VERSION",
    "MAX_RELEASE_ANCHOR_BYTES",
    "RELEASE_ANCHOR_PATH",
    "RELEASE_ANCHOR_RECEIPT_PATH",
    "AnchorError",
    "ReleaseAnchor",
    "brain_owned_rows",
    "build_release_anchor_document",
    "canonical_anchor_bytes",
    "compute_anchor_sha256",
    "consume_release_anchor",
    "parse_release_anchor",
]
