"""Old-engine delivery bridge and first-run activation guarantees."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from core import portable_contract
from core.lifecycle.bridge import (
    ACTIVATION_RELATIVE,
    BridgeActivationError,
    activate_vault,
    load_bridge_release,
    resume_bridge_transactions,
)
from core.lifecycle.catalog import load_catalog
from core.lifecycle.inventory import build_inventory
from core.tests.test_adoption_transaction import _setup
from core.transaction.journal import PREVIOUS_SCHEMA_VERSION, SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _write_bridge_release(vault: Path, release_version: str = "1.64.0") -> None:
    target = vault / "core/lifecycle/catalog/bridge-release.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        _canonical(
            {
                "bridge_contract_version": 1,
                "release_version": release_version,
                "transaction_journal": {
                    "current_schema": SCHEMA_VERSION,
                    "previous_schema": PREVIOUS_SCHEMA_VERSION,
                    "minimum_resumable_schema": PREVIOUS_SCHEMA_VERSION,
                    "incompatible_action": "rollback-only",
                },
            }
        )
    )


def _activation_fixture(tmp_path: Path) -> Path:
    vault, _document, _catalog, _inventory, _plan, _loader = _setup(
        tmp_path, item_ids=("alpha",)
    )
    _write_bridge_release(vault)
    return vault


def test_baseline_import_is_read_only_and_activation_is_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.lifecycle import bridge as bridge_module

    vault = _activation_fixture(tmp_path)
    catalog = load_catalog(vault / "System/.release-catalog.json", release_root=vault)
    expected_hash = build_inventory(vault, catalog=catalog).to_dict()["inventory_sha256"]
    protected = vault / ".claude/skills/alpha/SKILL.md"
    before = protected.read_bytes()
    system_mode = stat.S_IMODE((vault / "System").stat().st_mode)
    fsynced_directories: list[Path] = []
    real_fsync_directory = bridge_module._fsync_directory

    def record_fsync(directory: Path) -> None:
        fsynced_directories.append(directory.relative_to(vault))
        real_fsync_directory(directory)

    monkeypatch.setattr(bridge_module, "_fsync_directory", record_fsync)

    activation = activate_vault(vault)

    activation_path = vault / ACTIVATION_RELATIVE
    assert activation == {
        "activation_version": 1,
        "api_version": "1.0.0",
        "bridge_release_version": "1.64.0",
        "baseline_inventory_sha256": expected_hash,
    }
    assert activation_path.read_bytes() == _canonical(activation)
    assert stat.S_IMODE(activation_path.stat().st_mode) == 0o600
    assert protected.read_bytes() == before
    assert stat.S_IMODE((vault / "System").stat().st_mode) == system_mode
    assert fsynced_directories == [
        Path("System"),
        Path("System/.dex"),
        Path("System/.dex/lifecycle"),
    ]
    assert not list(activation_path.parent.glob(".activation.json.tmp-*"))
    resolution = portable_contract.resolve(ACTIVATION_RELATIVE.as_posix())
    assert (resolution.ownership, resolution.denied) == ("runtime", False)
    assert portable_contract.update_write_verdict(
        ACTIVATION_RELATIVE.as_posix(), exists=False
    ).allowed is False


def test_reactivation_is_idempotent_but_invalid_existing_record_is_refused(
    tmp_path: Path,
) -> None:
    vault = _activation_fixture(tmp_path)
    first = activate_vault(vault)
    activation_path = vault / ACTIVATION_RELATIVE
    before_bytes = activation_path.read_bytes()
    before_mtime = activation_path.stat().st_mtime_ns

    assert activate_vault(vault) == first
    assert activation_path.read_bytes() == before_bytes
    assert activation_path.stat().st_mtime_ns == before_mtime

    activation_path.write_text('{"activation_version":999}\n', encoding="utf-8")
    with pytest.raises(BridgeActivationError, match="existing activation"):
        activate_vault(vault)
    assert activation_path.read_text(encoding="utf-8") == '{"activation_version":999}\n'


_INTERRUPT_WORKER = r"""
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[2])

from core.transaction.engine import PlanEntry, Transaction

vault = Path(sys.argv[1])
Transaction.begin(
    vault,
    [PlanEntry("System/.installed-files.manifest", b"bridge release manifest\n")],
).run()
"""


@pytest.mark.parametrize(
    ("seam", "expected"),
    (
        ("mid-apply:0", b"old manifest\n"),
        ("after-commit-record", b"bridge release manifest\n"),
    ),
)
def test_interrupted_bridge_transaction_converges_on_next_run(
    seam: str, expected: bytes, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    target = vault / "System/.installed-files.manifest"
    target.write_bytes(b"old manifest\n")
    _write_bridge_release(vault)
    process = subprocess.run(
        [sys.executable, "-c", _INTERRUPT_WORKER, str(vault), str(REPO_ROOT)],
        env={**os.environ, "DEX_TX_TEST_STOP_AFTER": seam},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert process.returncode == 137, process.stderr

    outcomes = resume_bridge_transactions(vault)

    assert target.read_bytes() == expected
    if seam == "after-commit-record":
        assert outcomes == []
    else:
        assert len(outcomes) == 1
        assert outcomes[0]["resumed"] is True
        assert outcomes[0]["committed"] is False


def test_incompatible_journal_schema_is_rollback_only(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    target = vault / "System/.installed-files.manifest"
    target.write_bytes(b"old manifest\n")
    _write_bridge_release(vault)
    process = subprocess.run(
        [sys.executable, "-c", _INTERRUPT_WORKER, str(vault), str(REPO_ROOT)],
        env={**os.environ, "DEX_TX_TEST_STOP_AFTER": "mid-apply:0"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert process.returncode == 137, process.stderr
    journal_path = next((vault / "System/.dex/tx").glob("*/journal.jsonl"))
    rewritten = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        record["schema_version"] = 999
        unsigned = {key: value for key, value in record.items() if key != "sha"}
        record["sha"] = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        rewritten.append(json.dumps(record, sort_keys=True, separators=(",", ":")))
    journal_path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")

    outcomes = resume_bridge_transactions(vault)

    assert target.read_bytes() == b"old manifest\n"
    assert len(outcomes) == 1
    assert outcomes[0]["rollback_only"] is True
    assert outcomes[0]["committed"] is False


def test_previous_journal_schema_resumes_normally(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    target = vault / "System/.installed-files.manifest"
    target.write_bytes(b"old manifest\n")
    _write_bridge_release(vault)
    process = subprocess.run(
        [sys.executable, "-c", _INTERRUPT_WORKER, str(vault), str(REPO_ROOT)],
        env={**os.environ, "DEX_TX_TEST_STOP_AFTER": "mid-apply:0"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert process.returncode == 137, process.stderr
    journal_path = next((vault / "System/.dex/tx").glob("*/journal.jsonl"))
    rewritten = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        record["schema_version"] = PREVIOUS_SCHEMA_VERSION
        unsigned = {key: value for key, value in record.items() if key != "sha"}
        record["sha"] = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        rewritten.append(json.dumps(record, sort_keys=True, separators=(",", ":")))
    journal_path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")

    outcomes = resume_bridge_transactions(vault)

    assert target.read_bytes() == b"old manifest\n"
    assert len(outcomes) == 1
    assert outcomes[0]["resumed"] is True
    assert "rollback_only" not in outcomes[0]


def test_shipped_bridge_release_matches_transaction_resume_window() -> None:
    bridge = load_bridge_release(REPO_ROOT)

    assert bridge.release_version == "1.68.0"
    assert bridge.transaction_journal.current_schema == SCHEMA_VERSION
    assert bridge.transaction_journal.previous_schema == PREVIOUS_SCHEMA_VERSION
    assert bridge.transaction_journal.minimum_resumable_schema == PREVIOUS_SCHEMA_VERSION
    assert bridge.transaction_journal.incompatible_action == "rollback-only"
