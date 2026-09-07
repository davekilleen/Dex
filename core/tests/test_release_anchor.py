"""Release-anchor artifact + fail-closed consumer (re-anchoring slice 2).

Red-when-removed coverage for the adversarial-review conditions owned by the
consumer half: C6 (merge-time row filtering), C7 (independent self-hash,
manifest-binding, and catalog-binding checks; every failure demotes with a
named error), C10 (the receipt is audit-only), C11 (size bound enforced at
read), and the C8 slice that anchor content can never carry an operation.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from core.lifecycle import release_anchor as release_anchor_module
from core.lifecycle.customizations import load_release_baseline
from core.lifecycle.inventory import build_inventory
from core.lifecycle.release_anchor import (
    MAX_RELEASE_ANCHOR_BYTES,
    RELEASE_ANCHOR_PATH,
    RELEASE_ANCHOR_RECEIPT_PATH,
    AnchorError,
    build_release_anchor_document,
    canonical_anchor_bytes,
    compute_anchor_sha256,
    parse_release_anchor,
)
from core.tests.lifecycle_test_helpers import (
    SOURCE_COMMIT,
    catalog_for,
    write_file,
    write_manifest,
)

RELEASE_TAG_NAME = f"dist/release/v1.64.0-{SOURCE_COMMIT[:7]}"

SHIPPED = b"release bytes\n"
ENGINE = b"engine release bytes\n"
TASKS = b"# the user's living tasks\n"
USAGE = b"# per-machine usage state\n"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _by_path(report):
    return {entry.actual_path: entry for entry in report.entries}


def _vault(tmp_path: Path):
    """A verified-catalog vault whose second brain file only an anchor can prove."""
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(vault, "core/feature.py", SHIPPED)
    write_file(vault, "core/engine.py", ENGINE)
    write_file(vault, "03-Tasks/Tasks.md", TASKS)
    write_file(vault, "System/usage_log.md", USAGE)
    manifest = write_manifest(
        vault,
        ["core/feature.py", "core/engine.py", "03-Tasks/Tasks.md", "System/usage_log.md"],
    )
    catalog = catalog_for(manifest, {"core/feature.py": SHIPPED})
    return vault, manifest, catalog


def _document(
    manifest_bytes: bytes,
    catalog,
    files: dict[str, str],
    *,
    version: str = "1.64.0",
    manifest_sha256: str | None = None,
    catalog_sha256: str | None = None,
):
    return build_release_anchor_document(
        release_version=version,
        tag=f"dist/release/v{version}-{SOURCE_COMMIT[:7]}",
        tag_object="a" * 40,
        commit=SOURCE_COMMIT,
        tree="f" * 40,
        manifest_sha256=manifest_sha256 or _sha(manifest_bytes),
        catalog_sha256=catalog_sha256 or catalog.integrity.catalog_sha256,
        files=files,
    )


def _plant(vault: Path, document) -> bytes:
    raw = canonical_anchor_bytes(document)
    write_file(vault, RELEASE_ANCHOR_PATH, raw)
    return raw


# ---------------------------------------------------------------------------
# The happy path: a bound anchor proves brain files the catalog cannot.
# ---------------------------------------------------------------------------


def test_verified_anchor_proves_brain_files_the_catalog_does_not(tmp_path: Path) -> None:
    vault, manifest, catalog = _vault(tmp_path)
    _plant(vault, _document(manifest, catalog, {"core/engine.py": _sha(ENGINE)}))

    baseline = load_release_baseline(vault, catalog=catalog)
    report = build_inventory(vault, catalog=catalog)
    entries = _by_path(report)

    assert baseline.identity_state == "VERIFIED"
    assert baseline.anchor_state == "verified"
    assert baseline.errors == ()
    assert baseline.expected_sha256("core/engine.py") == _sha(ENGINE)
    assert entries["core/engine.py"].release_state == "stock-unmodified"
    assert entries["core/feature.py"].release_state == "stock-unmodified"

    # A locally modified anchor-covered file is a divergence, never pristine.
    write_file(vault, "core/engine.py", b"locally changed\n")
    modified = _by_path(build_inventory(vault, catalog=catalog))
    assert modified["core/engine.py"].release_state == "stock-modified"


def test_absent_anchor_is_silent_and_keeps_todays_behavior(tmp_path: Path) -> None:
    vault, _manifest, catalog = _vault(tmp_path)

    baseline = load_release_baseline(vault, catalog=catalog)

    assert baseline.identity_state == "VERIFIED"
    assert baseline.anchor_state == "absent"
    assert baseline.errors == ()
    assert baseline.expected_sha256("core/engine.py") is None


def test_anchor_rows_merge_under_catalog_rows(tmp_path: Path) -> None:
    vault, manifest, catalog = _vault(tmp_path)
    _plant(
        vault,
        _document(
            manifest,
            catalog,
            {"core/feature.py": "1" * 64, "core/engine.py": _sha(ENGINE)},
        ),
    )

    baseline = load_release_baseline(vault, catalog=catalog)

    # The catalog stays authoritative for what it covers.
    assert baseline.anchor_state == "verified"
    assert baseline.expected_sha256("core/feature.py") == _sha(SHIPPED)
    assert baseline.expected_sha256("core/engine.py") == _sha(ENGINE)


# ---------------------------------------------------------------------------
# C7 — three independent trust checks, each red-when-removed. Deleting the
# manifest-binding comparison, the catalog-binding comparison, or the
# self-hash comparison in parse_release_anchor turns the matching test red.
# ---------------------------------------------------------------------------


def test_anchor_with_wrong_manifest_binding_is_rejected_with_named_error(
    tmp_path: Path,
) -> None:
    vault, manifest, catalog = _vault(tmp_path)
    _plant(
        vault,
        _document(
            manifest,
            catalog,
            {"core/engine.py": _sha(ENGINE)},
            manifest_sha256=_sha(b"some other manifest\n"),
        ),
    )

    baseline = load_release_baseline(vault, catalog=catalog)

    assert baseline.identity_state == "VERIFIED"
    assert baseline.anchor_state == "rejected"
    assert baseline.expected_sha256("core/engine.py") is None
    assert any("manifest binding" in error for error in baseline.errors)


def test_anchor_with_wrong_catalog_binding_is_rejected_with_named_error(
    tmp_path: Path,
) -> None:
    vault, manifest, catalog = _vault(tmp_path)
    _plant(
        vault,
        _document(
            manifest,
            catalog,
            {"core/engine.py": _sha(ENGINE)},
            catalog_sha256="1" * 64,
        ),
    )

    baseline = load_release_baseline(vault, catalog=catalog)

    assert baseline.anchor_state == "rejected"
    assert baseline.expected_sha256("core/engine.py") is None
    assert any("catalog binding" in error for error in baseline.errors)


def test_anchor_with_broken_self_hash_is_rejected_with_named_error(
    tmp_path: Path,
) -> None:
    vault, manifest, catalog = _vault(tmp_path)
    document = _document(manifest, catalog, {"core/engine.py": _sha(ENGINE)})
    # Tamper one row AFTER the self-hash was computed.
    document["files"]["core/engine.py"] = "2" * 64
    _plant(vault, document)

    baseline = load_release_baseline(vault, catalog=catalog)

    assert baseline.anchor_state == "rejected"
    assert baseline.expected_sha256("core/engine.py") is None
    assert any("self-hash" in error for error in baseline.errors)


def test_anchor_declaring_a_different_release_version_is_rejected(
    tmp_path: Path,
) -> None:
    vault, manifest, catalog = _vault(tmp_path)
    _plant(
        vault,
        _document(manifest, catalog, {"core/engine.py": _sha(ENGINE)}, version="1.63.0"),
    )

    baseline = load_release_baseline(vault, catalog=catalog)

    assert baseline.anchor_state == "rejected"
    assert any("release version" in error for error in baseline.errors)


# ---------------------------------------------------------------------------
# C7 / C11 — hostile bytes: every failure is a named error, never an
# exception, never a promotion. The size bound is enforced at read.
# ---------------------------------------------------------------------------


def test_oversized_anchor_is_rejected_at_read_with_named_error(tmp_path: Path) -> None:
    vault, _manifest, catalog = _vault(tmp_path)
    write_file(vault, RELEASE_ANCHOR_PATH, b"x" * (MAX_RELEASE_ANCHOR_BYTES + 1))

    baseline = load_release_baseline(vault, catalog=catalog)

    assert baseline.identity_state == "VERIFIED"
    assert baseline.anchor_state == "rejected"
    assert any("release anchor is unreadable" in error for error in baseline.errors)


def test_non_utf8_anchor_is_rejected_with_named_error(tmp_path: Path) -> None:
    vault, _manifest, catalog = _vault(tmp_path)
    write_file(vault, RELEASE_ANCHOR_PATH, b"\xff\xfe not utf-8")

    baseline = load_release_baseline(vault, catalog=catalog)

    assert baseline.anchor_state == "rejected"
    assert any("not UTF-8" in error for error in baseline.errors)


@pytest.mark.parametrize(
    "raw",
    [
        b"not json at all",
        b"[]\n",
        b'{"anchor_version": 1}\n',
        b'{"anchor_version": 99, "release": {}, "bindings": {}, "files": {}, "integrity": {}}\n',
    ],
)
def test_malformed_anchor_is_rejected_with_named_error(tmp_path: Path, raw: bytes) -> None:
    vault, _manifest, catalog = _vault(tmp_path)
    write_file(vault, RELEASE_ANCHOR_PATH, raw)

    baseline = load_release_baseline(vault, catalog=catalog)

    assert baseline.anchor_state == "rejected"
    assert baseline.errors
    assert all(error.startswith("release anchor") for error in baseline.errors)


def test_symlinked_anchor_is_rejected_with_named_error(tmp_path: Path) -> None:
    vault, manifest, catalog = _vault(tmp_path)
    outside = tmp_path / "outside-anchor.json"
    outside.write_bytes(
        canonical_anchor_bytes(_document(manifest, catalog, {"core/engine.py": _sha(ENGINE)}))
    )
    target = vault / RELEASE_ANCHOR_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(outside, target)

    baseline = load_release_baseline(vault, catalog=catalog)

    assert baseline.anchor_state == "rejected"
    assert baseline.expected_sha256("core/engine.py") is None
    assert any("release anchor is unreadable" in error for error in baseline.errors)


# ---------------------------------------------------------------------------
# C5 (subordination) — the anchor merges only when the catalog baseline is
# already VERIFIED; it can never rescue an unverified pair.
# ---------------------------------------------------------------------------


def test_anchor_never_rescues_an_unverified_catalog_baseline(tmp_path: Path) -> None:
    vault, manifest, catalog = _vault(tmp_path)
    _plant(vault, _document(manifest, catalog, {"core/engine.py": _sha(ENGINE)}))
    # The installed manifest changes; the catalog binding no longer verifies.
    write_manifest(
        vault,
        [
            "core/feature.py",
            "core/engine.py",
            "03-Tasks/Tasks.md",
            "System/usage_log.md",
            "core/added.py",
        ],
    )

    baseline = load_release_baseline(vault, catalog=catalog)

    assert baseline.identity_state == "UNKNOWN"
    assert baseline.anchor_state == "absent"
    assert dict(baseline.expected_hashes) == {}


# ---------------------------------------------------------------------------
# C6, merge-time half — seed and runtime rows are inert; the user's living
# files never classify stock-* because of an anchor. Deleting the
# brain_owned_rows filter turns these red.
# ---------------------------------------------------------------------------


def test_seed_and_runtime_rows_are_inert_and_never_reclassify_user_files(
    tmp_path: Path,
) -> None:
    vault, manifest, catalog = _vault(tmp_path)
    _plant(
        vault,
        _document(
            manifest,
            catalog,
            {
                "core/engine.py": _sha(ENGINE),
                # The attack from review §2.2: rows matching the user's own
                # live bytes, which would classify stock-unmodified (and any
                # later edit stock-modified) if merged.
                "03-Tasks/Tasks.md": _sha(TASKS),
                "System/usage_log.md": _sha(USAGE),
            },
        ),
    )

    baseline = load_release_baseline(vault, catalog=catalog)
    entries = _by_path(build_inventory(vault, catalog=catalog))

    assert baseline.anchor_state == "verified"
    assert baseline.expected_sha256("03-Tasks/Tasks.md") is None
    assert baseline.expected_sha256("System/usage_log.md") is None
    assert entries["03-Tasks/Tasks.md"].release_state == "canonical-customization"
    assert entries["System/usage_log.md"].release_state == "durable-state"
    assert not entries["03-Tasks/Tasks.md"].release_state.startswith("stock-")
    assert entries["core/engine.py"].release_state == "stock-unmodified"


def test_leftover_files_stay_unproved_despite_a_verified_anchor(tmp_path: Path) -> None:
    # A leftover: on disk, brain-owned, absent from the installed manifest
    # and the proven tree. The anchor never blesses it — it stays honestly
    # unproved and flows to the existing exclusion/cleanup lanes.
    vault, manifest, catalog = _vault(tmp_path)
    write_file(vault, "core/leftover.py", b"pre-merge leftover bytes\n")
    _plant(vault, _document(manifest, catalog, {"core/engine.py": _sha(ENGINE)}))

    baseline = load_release_baseline(vault, catalog=catalog)
    entries = _by_path(build_inventory(vault, catalog=catalog))

    assert baseline.anchor_state == "verified"
    assert baseline.expected_sha256("core/leftover.py") is None
    assert entries["core/leftover.py"].release_state == "unknown"


def test_crlf_checkout_form_of_an_anchor_proved_file_is_stock(tmp_path: Path) -> None:
    # Windows autocrlf checkouts carry CRLF on disk while anchor rows hash
    # the LF release bytes — the centralized CRLF tolerance carries over.
    vault, manifest, catalog = _vault(tmp_path)
    write_file(vault, "core/engine.py", ENGINE.replace(b"\n", b"\r\n"))
    _plant(vault, _document(manifest, catalog, {"core/engine.py": _sha(ENGINE)}))

    entries = _by_path(build_inventory(vault, catalog=catalog))

    assert entries["core/engine.py"].release_state == "stock-unmodified"


def test_rows_outside_the_installed_manifest_are_inert(tmp_path: Path) -> None:
    vault, manifest, catalog = _vault(tmp_path)
    _plant(
        vault,
        _document(
            manifest,
            catalog,
            {"core/not-installed.py": "3" * 64, "core/engine.py": _sha(ENGINE)},
        ),
    )

    baseline = load_release_baseline(vault, catalog=catalog)

    assert baseline.anchor_state == "verified"
    assert baseline.expected_sha256("core/not-installed.py") is None
    assert baseline.expected_sha256("core/engine.py") == _sha(ENGINE)


# ---------------------------------------------------------------------------
# C10 — the receipt is audit evidence, never trust.
# ---------------------------------------------------------------------------


def test_forged_or_orphan_receipt_changes_nothing(tmp_path: Path) -> None:
    vault, _manifest, catalog = _vault(tmp_path)
    before = load_release_baseline(vault, catalog=catalog)
    write_file(
        vault,
        RELEASE_ANCHOR_RECEIPT_PATH,
        b'{"receipt_version": 1, "kind": "release-anchor", "anchor_sha256": "'
        + b"4" * 64
        + b'"}\n',
    )

    after = load_release_baseline(vault, catalog=catalog)

    assert after == before
    assert after.anchor_state == "absent"


def test_baseline_consumer_never_opens_the_receipt_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, manifest, catalog = _vault(tmp_path)
    _plant(vault, _document(manifest, catalog, {"core/engine.py": _sha(ENGINE)}))
    write_file(vault, RELEASE_ANCHOR_RECEIPT_PATH, b"{}\n")
    real_bounded_read = release_anchor_module.bounded_read

    def trapped(root, relative, **kwargs):
        assert relative != RELEASE_ANCHOR_RECEIPT_PATH, (
            "classification trust must never read the anchor receipt"
        )
        return real_bounded_read(root, relative, **kwargs)

    monkeypatch.setattr(release_anchor_module, "bounded_read", trapped)

    baseline = load_release_baseline(vault, catalog=catalog)

    assert baseline.anchor_state == "verified"


# ---------------------------------------------------------------------------
# C8 (content half) — anchor content can never smuggle an operation or any
# other field: the document shape is closed.
# ---------------------------------------------------------------------------


def test_anchor_content_cannot_carry_an_operation_field(tmp_path: Path) -> None:
    vault, manifest, catalog = _vault(tmp_path)
    document = dict(_document(manifest, catalog, {"core/engine.py": _sha(ENGINE)}))
    document["operation"] = "release-anchor"
    document["integrity"] = {"anchor_sha256": compute_anchor_sha256(document)}
    _plant(vault, document)

    baseline = load_release_baseline(vault, catalog=catalog)

    assert baseline.anchor_state == "rejected"
    assert any("unsupported shape" in error for error in baseline.errors)
    assert baseline.expected_sha256("core/engine.py") is None


# ---------------------------------------------------------------------------
# Direct parse-level contracts (the consumer above exercises them through
# load_release_baseline; these pin the raised error type and messages).
# ---------------------------------------------------------------------------


def test_parse_release_anchor_raises_named_anchor_errors(tmp_path: Path) -> None:
    vault, manifest, catalog = _vault(tmp_path)
    raw = canonical_anchor_bytes(
        _document(manifest, catalog, {"core/engine.py": _sha(ENGINE)})
    )

    parsed = parse_release_anchor(
        raw,
        manifest_bytes=manifest,
        catalog_sha256=catalog.integrity.catalog_sha256,
        release_version="1.64.0",
    )
    assert parsed.files == {"core/engine.py": _sha(ENGINE)}
    assert parsed.tag == RELEASE_TAG_NAME

    with pytest.raises(AnchorError, match="manifest binding"):
        parse_release_anchor(
            raw,
            manifest_bytes=b"different\n",
            catalog_sha256=catalog.integrity.catalog_sha256,
        )
    with pytest.raises(AnchorError, match="catalog binding"):
        parse_release_anchor(raw, manifest_bytes=manifest, catalog_sha256="5" * 64)


def test_anchor_manifest_binding_tolerates_crlf_manifest_form(tmp_path: Path) -> None:
    vault, manifest, catalog = _vault(tmp_path)
    raw = canonical_anchor_bytes(
        _document(manifest, catalog, {"core/engine.py": _sha(ENGINE)})
    )
    crlf_manifest = manifest.replace(b"\n", b"\r\n")

    parsed = parse_release_anchor(
        raw,
        manifest_bytes=crlf_manifest,
        catalog_sha256=catalog.integrity.catalog_sha256,
    )

    assert parsed.manifest_sha256 == _sha(manifest)


def test_build_document_stores_paths_and_hashes_only(tmp_path: Path) -> None:
    vault, manifest, catalog = _vault(tmp_path)
    document = _document(manifest, catalog, {"core/engine.py": _sha(ENGINE)})

    raw = canonical_anchor_bytes(document)

    assert ENGINE not in raw
    assert set(document) == {"anchor_version", "release", "bindings", "files", "integrity"}
    with pytest.raises(AnchorError, match="row for"):
        _document(manifest, catalog, {"core/engine.py": "not-a-hash"})
    with pytest.raises(AnchorError, match="row path"):
        _document(manifest, catalog, {"../escape.py": "6" * 64})
