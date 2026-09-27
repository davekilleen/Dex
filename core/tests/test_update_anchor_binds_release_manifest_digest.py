"""Phase 1: generated anchors bind the catalog's declared manifest digest.

A Windows autocrlf checkout can carry the installed manifest as CRLF while
the catalog stores the LF digest. Generation must bind
``catalog.release.manifest.sha256`` (line-ending independent), not the
on-disk digest. ``parse_release_anchor`` still verifies installed bytes
through ``release_bytes_match``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from core.lifecycle.catalog import loads_catalog
from core.lifecycle.customizations import CATALOG_CANDIDATES, MAX_CATALOG_BYTES
from core.lifecycle.filesystem import bounded_read, normalize_relative_path
from core.tests.test_release_anchor_generation import _release_repo, _vault_with_brain
from core.update.anchor_generation import generate_release_anchor

pytestmark = pytest.mark.windows_supported


def test_generated_anchor_binds_catalog_manifest_digest_not_crlf_ondisk(
    tmp_path: Path,
) -> None:
    fixture = _release_repo(tmp_path)
    vault = _vault_with_brain(tmp_path, fixture)
    lf_manifest = fixture["manifest_bytes"]
    assert isinstance(lf_manifest, bytes)
    declared = hashlib.sha256(lf_manifest).hexdigest()
    crlf_manifest = lf_manifest.replace(b"\n", b"\r\n")
    assert crlf_manifest != lf_manifest
    (vault / "System/.installed-files.manifest").write_bytes(crlf_manifest)

    candidates = [path for path in CATALOG_CANDIDATES if (vault / path).is_file()]
    assert len(candidates) == 1
    catalog = loads_catalog(
        bounded_read(
            vault, normalize_relative_path(candidates[0]), max_bytes=MAX_CATALOG_BYTES
        ).decode("utf-8"),
        manifest_bytes=crlf_manifest,
    )
    assert catalog.release.manifest.sha256 == declared
    assert catalog.release.manifest.sha256 != hashlib.sha256(crlf_manifest).hexdigest()

    generation = generate_release_anchor(vault)

    assert generation.document["bindings"]["manifest_sha256"] == declared
    assert generation.document["bindings"]["manifest_sha256"] == (
        catalog.release.manifest.sha256
    )
    assert generation.document["bindings"]["manifest_sha256"] != hashlib.sha256(
        crlf_manifest
    ).hexdigest()
