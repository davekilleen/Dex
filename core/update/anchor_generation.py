"""Generate and write the release anchor from LOCALLY verified release evidence.

Slice 2 of the customization re-anchoring design
(docs/superpowers/specs/2026-09-04-customization-reanchoring-design.md), built
under the adversarial review's conditions
(docs/superpowers/specs/2026-09-05-anchor-seam-adversarial-review.md):

- **C4** — ``refs/dex/installed`` is a HINT only (it may order candidates,
  never prove one). Anchor rows are generated exclusively from a tree bound
  to an official annotated ``dist/release/v*`` tag verified with the origin
  pin. A crafted installed-ref commit with the correct manifest blob and no
  matching official tag produces no anchor.
- **C5** — :func:`verify_local_release_tag` is the ONE parameterized
  verification variant: it reuses ``apply_update``'s origin pin, tag regex,
  annotated-tag and header discipline, tag→commit→tree binding,
  tree-manifest self-consistency, and package-version equality verbatim (by
  importing them, never re-typing them), and replaces ONLY the channel-head
  equality with version-equality against the installed catalog's
  manifest-bound claim. This lane runs against the local brain store only;
  the evidence-cache/network lane (slice 3) passes a different ``git_dir``
  to the same function.
- **C6 (generation-time half)** — only brain-owned tree entries are hashed
  into rows; the user's seed and runtime files are never even read.
- **C9/C10** — the write is one transaction under the ``release-anchor``
  operation carrying ``expected_absent`` (first write) or
  ``expected_current_sha256`` (regeneration); the written bytes must hash to
  the previewed digest; the receipt rides the same transaction and is audit
  evidence only — no code path reads it to establish trust.
- **C12** — the release to prove is DERIVED from the installed catalog's
  manifest-bound claim; no argument substitutes a version or tag.

The interactive Doctor/CLI consent flow is a later lane. Nothing here is
reachable from any MCP tool, and the ``operation`` value is a literal — it is
never accepted from tool arguments, plan files, or anchor content (C8, this
lane's half).
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
    CatalogError,
    loads_catalog,
    release_bytes_match,
)
from core.lifecycle.customizations import (
    CATALOG_CANDIDATES,
    MANIFEST_PATH,
    MAX_CATALOG_BYTES,
    MAX_MANIFEST_BYTES,
)
from core.lifecycle.filesystem import (
    FilesystemInspectionError,
    bounded_read,
    normalize_relative_path,
)
from core.lifecycle.model import ReleaseCatalog
from core.lifecycle.release_anchor import (
    MAX_RELEASE_ANCHOR_BYTES,
    RELEASE_ANCHOR_PATH,
    RELEASE_ANCHOR_RECEIPT_PATH,
    build_release_anchor_document,
    canonical_anchor_bytes,
)

# Read-only reuse of the update lane's verification machinery (C5: one
# implementation, one parameter, never a re-typed copy). This module NEVER
# calls anything in apply_update that mutates state.
from core.update.apply_update import (
    MANIFEST_RELATIVE,
    RELEASE_TAG,
    ReleaseVerificationError,
    TreeEntry,
    _blob,
    _brain_text,
    _topology,
    _tree_entries,
    _verify_manifest,
    _verify_official_origin,
)

RECEIPT_VERSION = 1
MAX_RELEASE_ANCHOR_RECEIPT_BYTES = 64 * 1024
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HEX_OBJECT = re.compile(r"^[0-9a-f]{40,64}$")


class AnchorGenerationError(RuntimeError):
    """No anchor could be generated or written safely; nothing was mutated."""


@dataclass(frozen=True)
class VerifiedAnchorSource:
    """One locally proven release identity an anchor may be generated from."""

    tag: str
    tag_object: str
    commit: str
    tree: str
    version: str
    git_dir: Path
    entries: tuple[TreeEntry, ...]


@dataclass(frozen=True)
class AnchorGeneration:
    """A generated anchor document, ready for preview and consented write.

    ``replaces_sha256`` / ``replaces_receipt_sha256`` capture the live target
    state AT PREVIEW TIME: the consented write carries them as transaction
    preconditions, so anything appearing or changing between the preview and
    the write aborts (review §2.12) — the existing file wins.
    """

    document: dict[str, object]
    canonical_bytes: bytes
    # The document's internal self-hash (integrity.anchor_sha256, computed
    # over the canonical payload with the integrity envelope excluded).
    anchor_sha256: str
    # The digest of the EXACT bytes a consented write persists — this is the
    # value a preview shows and the confirm step names (review §2.12).
    document_sha256: str
    tag: str
    tag_object: str
    commit: str
    tree: str
    release_version: str
    row_count: int
    skipped_non_brain: int
    replaces_sha256: str | None
    replaces_receipt_sha256: str | None


def _git_text(vault_root: Path, git_dir: Path, *arguments: str) -> str:
    try:
        return _brain_text(vault_root, git_dir, *arguments)
    except (RuntimeError, OSError) as error:
        raise AnchorGenerationError(
            f"local release evidence is unreadable: {error}"
        ) from error


def _installed_claim(vault_root: Path) -> tuple[bytes, ReleaseCatalog]:
    """The release identity to PROVE: the installed, manifest-bound catalog claim.

    C12: this is the only place the target release comes from. It is a claim,
    never trusted — every row still requires the tag-verified tree below.
    """
    root = Path(vault_root)
    try:
        manifest_bytes = bounded_read(root, MANIFEST_PATH, max_bytes=MAX_MANIFEST_BYTES)
    except FilesystemInspectionError as error:
        raise AnchorGenerationError(
            f"the installed manifest cannot be read: {error}"
        ) from error
    candidates = [path for path in CATALOG_CANDIDATES if (root / path).is_file()]
    if len(candidates) != 1:
        raise AnchorGenerationError(
            "exactly one installed release catalog is required to derive the claim"
        )
    try:
        raw = bounded_read(
            root, normalize_relative_path(candidates[0]), max_bytes=MAX_CATALOG_BYTES
        )
        text = raw.decode("utf-8")
        catalog = loads_catalog(text, manifest_bytes=manifest_bytes)
    except (CatalogError, FilesystemInspectionError, UnicodeDecodeError) as error:
        raise AnchorGenerationError(
            f"the installed catalog does not verify against the installed manifest: {error}"
        ) from error
    return manifest_bytes, catalog


def verify_local_release_tag(
    vault_root: Path,
    *,
    git_dir: Path,
    tag: str,
    claimed_version: str,
    installed_manifest_bytes: bytes,
) -> VerifiedAnchorSource:
    """The C5 verification variant, parameterized by ``git_dir``.

    Retained verbatim from ``verify_release_ref``: the origin pin, the
    ``dist/release/v*`` tag regex, the annotated-tag and header discipline,
    the tag→commit→tree binding, the tree's manifest self-consistency, and
    the package-version equality. Replaced (ONLY this): the channel-head
    equality becomes version-equality against the installed catalog's
    manifest-bound claim, because the anchor proves the INSTALLED release,
    which is almost never the channel head. Additionally required here: the
    tree's manifest blob must prove the INSTALLED manifest bytes — a tag for
    any other release proves nothing about this vault.
    """
    root = Path(vault_root).resolve()

    # Retained check 1: the origin pin, applied to the supplied git dir.
    try:
        _verify_official_origin(root, git_dir)
    except (ReleaseVerificationError, RuntimeError, OSError) as error:
        raise AnchorGenerationError(
            f"release evidence origin is not the official Dex repository: {error}"
        ) from error

    # Retained check 2: the immutable-tag name discipline.
    match = RELEASE_TAG.fullmatch(tag)
    if match is None:
        raise AnchorGenerationError(
            "release ref is not an immutable dist/release/v* tag"
        )

    # Replaced check (C5): version-equality against the installed claim,
    # instead of channel-head equality.
    if match.group("version") != claimed_version:
        raise AnchorGenerationError(
            "release tag does not carry the installed catalog's claimed version"
        )

    # Retained check 3: the tag must be a resolvable ANNOTATED tag.
    tag_object = _git_text(root, git_dir, "rev-parse", "--verify", f"refs/tags/{tag}")
    if _HEX_OBJECT.fullmatch(tag_object) is None:
        raise AnchorGenerationError("release tag object identity is malformed")
    if _git_text(root, git_dir, "cat-file", "-t", tag_object) != "tag":
        raise AnchorGenerationError("immutable release tag is not annotated")

    # Retained check 4: the annotated-tag header discipline.
    tag_payload = _git_text(root, git_dir, "cat-file", "tag", tag_object)
    headers: dict[str, str] = {}
    for line in tag_payload.split("\n\n", 1)[0].splitlines():
        if " " not in line:
            continue
        key, value = line.split(" ", 1)
        if key in headers:
            raise AnchorGenerationError("annotated release tag headers are ambiguous")
        headers[key] = value
    commit = headers.get("object", "")
    if (
        headers.get("type") != "commit"
        or headers.get("tag") != tag
        or _HEX_OBJECT.fullmatch(commit) is None
    ):
        raise AnchorGenerationError(
            "annotated release tag identity contradicts its own headers"
        )
    if _git_text(root, git_dir, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}") != commit:
        raise AnchorGenerationError(
            "annotated release tag does not peel to its declared commit"
        )

    # Retained check 5: the tag-name suffix pins the full commit.
    if not commit.startswith(match.group("short")):
        raise AnchorGenerationError(
            "immutable tag suffix does not pin the full release commit"
        )

    # Retained check 6: tag→commit→tree binding.
    tree = _git_text(root, git_dir, "rev-parse", "--verify", f"{commit}^{{tree}}")
    if _HEX_OBJECT.fullmatch(tree) is None:
        raise AnchorGenerationError("release tree identity is malformed")

    # Retained check 7: the tree's own manifest blob equals the exact tree.
    try:
        entries = _tree_entries(root, git_dir, commit)
        _verify_manifest(root, git_dir, entries)
    except (ReleaseVerificationError, RuntimeError, OSError) as error:
        raise AnchorGenerationError(
            f"release tree does not verify: {error}"
        ) from error

    # Anchor-specific binding: the proven tree's manifest must prove the
    # INSTALLED manifest bytes (same centralized CRLF policy as every other
    # release-byte comparison). Without this, a verified tag for a different
    # release could mint rows for a vault it never shipped.
    by_path = {entry.path: entry for entry in entries}
    manifest_entry = by_path.get(MANIFEST_RELATIVE)
    if manifest_entry is None:
        raise AnchorGenerationError("release is missing its installed-files manifest")
    try:
        tree_manifest = _blob(root, git_dir, manifest_entry.object_id)
    except (RuntimeError, OSError) as error:
        raise AnchorGenerationError(
            f"release manifest blob is unreadable: {error}"
        ) from error
    if not release_bytes_match(
        hashlib.sha256(tree_manifest).hexdigest(), installed_manifest_bytes
    ):
        raise AnchorGenerationError(
            "verified release tree does not reproduce the installed manifest"
        )

    # Retained check 8: package-version equality against the tag version.
    package_entry = by_path.get("package.json")
    if package_entry is None:
        raise AnchorGenerationError("release is missing package.json")
    try:
        package = json.loads(_blob(root, git_dir, package_entry.object_id).decode("utf-8"))
    except (RuntimeError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AnchorGenerationError("release package metadata is unreadable") from error
    if not isinstance(package, dict) or package.get("version") != match.group("version"):
        raise AnchorGenerationError(
            "release package version contradicts the immutable tag"
        )

    return VerifiedAnchorSource(
        tag,
        tag_object,
        commit,
        tree,
        match.group("version"),
        git_dir,
        entries,
    )


def _installed_ref_hint(vault_root: Path, git_dir: Path) -> str | None:
    """C4: the mutable installed ref may ORDER candidates, never prove one."""
    try:
        commit = _brain_text(
            vault_root, git_dir, "rev-parse", "--verify", "refs/dex/installed^{commit}"
        )
    except (RuntimeError, OSError):
        return None
    return commit if _HEX_OBJECT.fullmatch(commit) is not None else None


def _local_tag_candidates(
    vault_root: Path,
    git_dir: Path,
    *,
    claimed_version: str,
) -> tuple[str, ...]:
    listing = _git_text(
        vault_root,
        git_dir,
        "for-each-ref",
        "--format=%(refname:strip=2)\t%(*objectname)",
        "refs/tags/dist/release/",
    )
    hint = _installed_ref_hint(vault_root, git_dir)
    candidates: list[tuple[int, str]] = []
    for line in listing.splitlines():
        name, _, peeled = line.partition("\t")
        match = RELEASE_TAG.fullmatch(name)
        if match is None or match.group("version") != claimed_version:
            continue
        # Hint-only ordering (C4): a tag whose peeled commit matches the
        # installed ref is tried first. Verification below is identical for
        # every candidate; the hint can never admit an unverified tree.
        candidates.append((0 if hint is not None and peeled == hint else 1, name))
    return tuple(name for _, name in sorted(candidates))


def generate_release_anchor(vault_root: Path) -> AnchorGeneration:
    """Generate one anchor from local sources only; fail closed otherwise.

    No parameter names a version or tag (C12): the release to prove is
    derived from the installed catalog's manifest-bound claim. Nothing is
    written — the caller previews the returned digest and only the separate,
    consent-gated :func:`write_release_anchor` persists it.
    """
    root = Path(vault_root).resolve()
    manifest_bytes, catalog = _installed_claim(root)
    claimed_version = catalog.release.version

    try:
        git_dir, _topology_value, _brain_marker = _topology(root)
    except Exception as error:  # UpdateError and friends — fail closed, named.
        raise AnchorGenerationError(
            f"the local brain store is unavailable for anchor generation: {error}"
        ) from error

    candidates = _local_tag_candidates(root, git_dir, claimed_version=claimed_version)
    source: VerifiedAnchorSource | None = None
    failures: list[str] = []
    for tag in candidates:
        try:
            source = verify_local_release_tag(
                root,
                git_dir=git_dir,
                tag=tag,
                claimed_version=claimed_version,
                installed_manifest_bytes=manifest_bytes,
            )
            break
        except AnchorGenerationError as error:
            failures.append(f"{tag}: {error}")
    if source is None:
        detail = "; ".join(failures) if failures else "no matching official tag is present locally"
        raise AnchorGenerationError(
            "no local source verifies the installed release "
            f"v{claimed_version}: {detail}"
        )

    # C6, generation-time half: hash ONLY brain-owned tree blobs. Seed and
    # runtime paths (the user's living files) are never read, never hashed,
    # never carried.
    rows: dict[str, str] = {}
    skipped = 0
    for entry in source.entries:
        try:
            resolution = portable_contract.resolve(entry.path)
        except portable_contract.ContractViolation:
            skipped += 1
            continue
        if resolution.denied or resolution.ownership != "brain":
            skipped += 1
            continue
        try:
            blob = _blob(root, git_dir, entry.object_id)
        except (RuntimeError, OSError) as error:
            raise AnchorGenerationError(
                f"verified release blob is unreadable for {entry.path}: {error}"
            ) from error
        rows[entry.path] = hashlib.sha256(blob).hexdigest()

    document = build_release_anchor_document(
        release_version=source.version,
        tag=source.tag,
        tag_object=source.tag_object,
        commit=source.commit,
        tree=source.tree,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        catalog_sha256=catalog.integrity.catalog_sha256,
        files=rows,
    )
    payload = canonical_anchor_bytes(document)
    if len(payload) > MAX_RELEASE_ANCHOR_BYTES:
        raise AnchorGenerationError(
            "generated anchor exceeds the declared release-anchor size bound"
        )
    integrity = document["integrity"]
    assert isinstance(integrity, dict)
    return AnchorGeneration(
        document,
        payload,
        str(integrity["anchor_sha256"]),
        hashlib.sha256(payload).hexdigest(),
        source.tag,
        source.tag_object,
        source.commit,
        source.tree,
        source.version,
        len(rows),
        skipped,
        _current_file_sha256(root, RELEASE_ANCHOR_PATH, max_bytes=MAX_RELEASE_ANCHOR_BYTES),
        _current_file_sha256(
            root, RELEASE_ANCHOR_RECEIPT_PATH, max_bytes=MAX_RELEASE_ANCHOR_RECEIPT_BYTES
        ),
    )


def _current_file_sha256(vault_root: Path, relative: str, *, max_bytes: int) -> str | None:
    """Strict digest of a live target, or None when absent; refuse unsafe."""
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
        raise AnchorGenerationError(
            f"existing {relative} cannot be safely replaced: {error}"
        ) from error
    return hashlib.sha256(raw).hexdigest()


def write_release_anchor(
    vault_root: Path,
    generation: AnchorGeneration,
    *,
    previewed_sha256: str,
    clock=time.time,
) -> dict[str, object]:
    """Persist anchor + receipt in ONE ``release-anchor`` transaction (C9/C10).

    ``previewed_sha256`` is the digest the interactive layer showed the user;
    the written bytes must hash to exactly that value, or nothing is written.
    A first write carries ``expected_absent``; a regeneration carries
    ``expected_current_sha256`` of the bytes that were live AT PREVIEW TIME
    (captured in the generation), so anything appearing or changing between
    preview and write aborts the transaction and the existing file wins
    (review §2.12). The receipt is audit evidence only: nothing may ever read
    it to establish classification trust.

    Consent is NOT collected here — this function is the mutation seam the
    consent-gated Doctor/CLI lane (a later slice) calls after its interactive
    confirmation. It is intentionally reachable from no MCP tool.
    """
    if (
        not isinstance(previewed_sha256, str)
        or _HEX_SHA256.fullmatch(previewed_sha256) is None
    ):
        raise AnchorGenerationError("previewed anchor digest is malformed")
    digest = hashlib.sha256(generation.canonical_bytes).hexdigest()
    if digest != previewed_sha256 or digest != generation.document_sha256:
        raise AnchorGenerationError(
            "anchor bytes do not match the previewed digest; refusing to write"
        )

    receipt_document = {
        "receipt_version": RECEIPT_VERSION,
        "kind": "release-anchor",
        "anchor_sha256": generation.anchor_sha256,
        "document_sha256": generation.document_sha256,
        "release": {
            "version": generation.release_version,
            "tag": generation.tag,
            "tag_object": generation.tag_object,
            "commit": generation.commit,
            "tree": generation.tree,
        },
        "row_count": generation.row_count,
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock())),
    }
    receipt_bytes = (
        json.dumps(receipt_document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")

    # Lazy import keeps the read-only generation half importable without the
    # transaction machinery, mirroring apply_update's own layering.
    from core.transaction.engine import PlanEntry, Transaction

    caps = {
        RELEASE_ANCHOR_PATH: MAX_RELEASE_ANCHOR_BYTES,
        RELEASE_ANCHOR_RECEIPT_PATH: MAX_RELEASE_ANCHOR_RECEIPT_BYTES,
    }
    entries = [
        PlanEntry(
            relative,
            content,
            mode=0o600,
            expected_current_sha256=previewed_current,
            expected_absent=previewed_current is None,
        )
        for relative, content, previewed_current in (
            (RELEASE_ANCHOR_PATH, generation.canonical_bytes, generation.replaces_sha256),
            (
                RELEASE_ANCHOR_RECEIPT_PATH,
                receipt_bytes,
                generation.replaces_receipt_sha256,
            ),
        )
    ]

    transaction = Transaction.begin(
        Path(vault_root),
        entries,
        operation="release-anchor",
        max_read_bytes_by_relative=caps,
    )
    result = transaction.run()
    result["anchor_sha256"] = generation.anchor_sha256
    result["document_sha256"] = generation.document_sha256
    return result


__all__ = [
    "AnchorGeneration",
    "AnchorGenerationError",
    "MAX_RELEASE_ANCHOR_RECEIPT_BYTES",
    "RECEIPT_VERSION",
    "VerifiedAnchorSource",
    "generate_release_anchor",
    "verify_local_release_tag",
    "write_release_anchor",
]
