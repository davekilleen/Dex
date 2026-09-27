"""Phase 2: a CRLF-tailed activation is re-recorded through _prepare."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.lifecycle.bridge import (
    ACTIVATION_RELATIVE,
    _canonical,
    _well_formed_activation,
    activate_vault,
)
from core.lifecycle.byte_mode import MARKER_RELATIVE, load_marker
from core.lifecycle.service import _prepare
from core.tests.byte_mode_helpers import crlf_variant
from core.tests.test_lifecycle_bridge import _activation_fixture

pytestmark = pytest.mark.windows_supported


def test_prepare_re_records_crlf_tailed_activation(tmp_path: Path) -> None:
    vault = _activation_fixture(tmp_path)
    first = activate_vault(vault)
    path = vault / ACTIVATION_RELATIVE
    original = path.read_bytes()
    assert original == _canonical(first)
    path.write_bytes(crlf_variant(original))

    _prepare(vault)

    rewritten = path.read_bytes()
    document = _well_formed_activation(rewritten)
    assert document is not None
    assert rewritten == _canonical(document)
    assert b"\r\n" not in rewritten
    marker = load_marker(vault)
    assert marker is not None
    assert (vault / MARKER_RELATIVE).is_file()
    quarantine = vault / str(marker["quarantine"])
    assert (quarantine / ACTIVATION_RELATIVE).read_bytes() == crlf_variant(original)
