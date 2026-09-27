"""Phase 2: Doctor wording and the byte-mode CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.lifecycle.cli import main
from core.tests.byte_mode_helpers import (
    crlf_variant,
    event_bytes,
    receipt_bytes,
    write_ledger_event,
    write_receipt,
)
from core.utils import doctor
from core.utils.doctor import DoctorContext, Heal

pytestmark = pytest.mark.windows_supported


def _context(vault: Path) -> DoctorContext:
    return DoctorContext(
        vault_root=vault,
        repo_root=vault,
        home=vault,
        now=doctor.datetime.now(doctor.timezone.utc)
        if hasattr(doctor, "datetime")
        else __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )


def test_doctor_reports_repairable_finding_in_plain_english(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_receipt(vault, crlf_variant(receipt_bytes()))
    from datetime import datetime, timezone

    context = DoctorContext(
        vault_root=vault,
        repo_root=vault,
        home=vault,
        now=datetime.now(timezone.utc),
    )

    result = doctor._probe_lifecycle_byte_mode(context)

    assert result.verdict == "BROKEN"
    assert "Windows line endings" in result.detail
    assert "notes" in result.detail.lower()
    assert result.heal == Heal(
        tier=2,
        action="Repair Dex's bookkeeping files (a copy is kept first).",
    )


def test_doctor_reports_ledger_as_hand_repair(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_ledger_event(vault, crlf_variant(event_bytes()))
    from datetime import datetime, timezone

    context = DoctorContext(
        vault_root=vault,
        repo_root=vault,
        home=vault,
        now=datetime.now(timezone.utc),
    )

    result = doctor._probe_lifecycle_byte_mode(context)

    assert result.verdict == "BROKEN"
    assert result.heal is not None
    assert result.heal.tier == 3
    assert "/feedback" in result.heal.action
    assert "cannot safely repair" in result.detail


def test_cli_status_apply_and_idempotent_second_apply(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_receipt(vault, crlf_variant(receipt_bytes()))

    assert main(["--vault-root", str(vault), "byte-mode", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["findings"]

    assert main(["--vault-root", str(vault), "byte-mode", "apply"]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["actions"]

    assert main(["--vault-root", str(vault), "byte-mode", "apply"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["actions"] == []

    assert main(["--vault-root", str(vault), "byte-mode", "status"]) == 0
    clean = json.loads(capsys.readouterr().out)
    assert clean == {"state": "binary", "findings": []}
