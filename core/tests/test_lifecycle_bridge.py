"""Old-engine delivery bridge and first-run activation guarantees."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from core import portable_contract
from core.lifecycle import service
from core.lifecycle.bridge import (
    ACTIVATION_RELATIVE,
    BridgeActivationError,
    activate_vault,
    discard_superseded_activation,
    load_bridge_release,
    resume_bridge_transactions,
)
from core.lifecycle.catalog import load_catalog
from core.lifecycle.inventory import build_inventory
from core.tests.lifecycle_test_helpers import write_bridge_release
from core.tests.test_adoption_transaction import _setup
from core.transaction.engine import PlanRejected
from core.transaction.journal import PREVIOUS_SCHEMA_VERSION, SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


# Shared with other lifecycle suites; kept under its historical name so
# existing ``from core.tests.test_lifecycle_bridge import _write_bridge_release``
# imports keep working.
_write_bridge_release = write_bridge_release


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
    real_fsync_directory = bridge_module.fsync_directory

    def record_fsync(directory: Path) -> None:
        fsynced_directories.append(directory.relative_to(vault))
        real_fsync_directory(directory)

    monkeypatch.setattr(bridge_module, "fsync_directory", record_fsync)

    activation = activate_vault(vault)

    activation_path = vault / ACTIVATION_RELATIVE
    assert activation == {
        "activation_version": 1,
        "api_version": service.api_version,
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

    previous_api = {**first, "api_version": "1.2.0"}
    activation_path.write_bytes(_canonical(previous_api))
    assert activate_vault(vault) == previous_api

    previous_api = {**first, "api_version": "1.3.0"}
    activation_path.write_bytes(_canonical(previous_api))
    assert activate_vault(vault) == previous_api

    activation_path.write_text('{"activation_version":999}\n', encoding="utf-8")
    with pytest.raises(BridgeActivationError, match="existing activation"):
        activate_vault(vault)
    assert activation_path.read_text(encoding="utf-8") == '{"activation_version":999}\n'


def test_activation_accepts_a_self_consistent_release_and_refuses_a_mismatch(
    tmp_path: Path,
) -> None:
    consistent_root = tmp_path / "consistent"
    consistent_root.mkdir()
    consistent = _activation_fixture(consistent_root)

    activation = activate_vault(consistent)

    assert activation["bridge_release_version"] == "1.64.0"

    mismatched_root = tmp_path / "mismatched"
    mismatched_root.mkdir()
    mismatched = _activation_fixture(mismatched_root)
    _write_bridge_release(mismatched, release_version="1.64.1")

    with pytest.raises(
        BridgeActivationError,
        match="installed catalog release does not match the designated bridge release",
    ):
        activate_vault(mismatched)
    assert not (mismatched / ACTIVATION_RELATIVE).exists()


def _deliver_release(vault: Path, release_version: str) -> None:
    """Simulate a delivered update: bridge declaration + catalog move together."""
    from core.lifecycle.catalog import canonical_catalog_bytes, with_catalog_identity

    _write_bridge_release(vault, release_version=release_version)
    catalog_path = vault / "System/.release-catalog.json"
    document = json.loads(catalog_path.read_text(encoding="utf-8"))
    document["release"]["version"] = release_version
    document["release"]["immutable_distribution_tag"] = (
        f"dist/release/v{release_version}-0123456"
    )
    catalog_path.write_bytes(canonical_catalog_bytes(with_catalog_identity(document)))


def test_stale_activation_from_a_previous_release_is_rerecorded(
    tmp_path: Path,
) -> None:
    vault = _activation_fixture(tmp_path)
    first = activate_vault(vault)
    assert first["bridge_release_version"] == "1.64.0"

    _deliver_release(vault, "1.64.1")

    refreshed = activate_vault(vault)

    catalog = load_catalog(vault / "System/.release-catalog.json", release_root=vault)
    expected_hash = build_inventory(vault, catalog=catalog).to_dict()["inventory_sha256"]
    activation_path = vault / ACTIVATION_RELATIVE
    assert refreshed == {
        "activation_version": 1,
        "api_version": service.api_version,
        "bridge_release_version": "1.64.1",
        "baseline_inventory_sha256": expected_hash,
    }
    assert activation_path.read_bytes() == _canonical(refreshed)
    assert stat.S_IMODE(activation_path.stat().st_mode) == 0o600
    assert not list(activation_path.parent.glob(".activation.json.tmp-*"))
    assert activate_vault(vault) == refreshed


def test_stale_activation_refresh_still_refuses_a_torn_install(
    tmp_path: Path,
) -> None:
    vault = _activation_fixture(tmp_path)
    stale = activate_vault(vault)
    _write_bridge_release(vault, release_version="1.64.1")

    with pytest.raises(
        BridgeActivationError,
        match="installed catalog release does not match the designated bridge release",
    ):
        activate_vault(vault)
    assert (vault / ACTIVATION_RELATIVE).read_bytes() == _canonical(stale)


def test_discard_superseded_activation_removes_only_routine_records(
    tmp_path: Path,
) -> None:
    vault = _activation_fixture(tmp_path)
    record = activate_vault(vault)
    path = vault / ACTIVATION_RELATIVE

    # Same-version records and malformed version arguments are left alone.
    assert discard_superseded_activation(vault, "1.64.0") is False
    assert discard_superseded_activation(vault, "not-semver") is False
    assert path.read_bytes() == _canonical(record)

    # A structurally invalid record is fail-closed evidence, never tidy-up.
    path.write_text('{"activation_version":999}\n', encoding="utf-8")
    assert discard_superseded_activation(vault, "1.65.0") is False
    assert path.read_text(encoding="utf-8") == '{"activation_version":999}\n'

    # A symlinked record is refused untouched.
    path.unlink()
    real = vault / "real-activation.json"
    real.write_bytes(_canonical(record))
    path.symlink_to(real)
    assert discard_superseded_activation(vault, "1.65.0") is False
    assert path.is_symlink()
    path.unlink()

    # An absent record is a no-op.
    assert discard_superseded_activation(vault, "1.65.0") is False

    # A well-formed record for another release is removed, exactly once.
    path.write_bytes(_canonical(record))
    assert discard_superseded_activation(vault, "1.65.0") is True
    assert not path.exists()
    assert discard_superseded_activation(vault, "1.65.0") is False


def test_discard_superseded_activation_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.lifecycle import bridge as bridge_module

    vault = _activation_fixture(tmp_path)
    activate_vault(vault)
    path = vault / ACTIVATION_RELATIVE

    def fail_fsync(_directory: Path) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(bridge_module, "_fsync_directory", fail_fsync)
    assert discard_superseded_activation(vault, "1.65.0") is False
    assert not path.exists()


def test_gated_operations_recover_after_a_delivered_release(tmp_path: Path) -> None:
    vault = _activation_fixture(tmp_path)
    activate_vault(vault)
    _deliver_release(vault, "1.64.1")

    state = service.read_lifecycle_state(vault)

    assert "ledger_state" in state
    plan = service.build_inventory_and_plan(vault)
    assert "plan" in plan


def test_lifecycle_service_translates_bridge_activation_failure_to_plain_refusal(
    tmp_path: Path,
) -> None:
    vault = _activation_fixture(tmp_path)
    _write_bridge_release(vault, release_version="1.64.1")

    with pytest.raises(
        PlanRejected,
        match=(
            "this Dex copy's update engine doesn't match its release information "
            "— run /dex-doctor"
        ),
    ):
        service.build_inventory_and_plan(vault)


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
    package_version = json.loads(
        (REPO_ROOT / "package.json").read_text(encoding="utf-8")
    )["version"]

    assert bridge.release_version == package_version
    assert bridge.transaction_journal.current_schema == SCHEMA_VERSION
    assert bridge.transaction_journal.previous_schema == PREVIOUS_SCHEMA_VERSION
    assert bridge.transaction_journal.minimum_resumable_schema == PREVIOUS_SCHEMA_VERSION
    assert bridge.transaction_journal.incompatible_action == "rollback-only"


def test_lifecycle_1_2_callers_resolve_unchanged_operations() -> None:
    """The 1.3 surface is additive: every 1.2 operation keeps its exact call shape."""
    expected_signatures = {
        "build_inventory_and_plan": "(vault_root: 'str | Path') -> 'dict[str, object]'",
        "build_and_preview_adoption": (
            "(vault_root: 'str | Path', release_root: 'str | Path', "
            "requested_item_ids: 'Sequence[str]') -> 'dict[str, object]'"
        ),
        "execute_approved_adoption": (
            "(vault_root: 'str | Path', release_root: 'str | Path', "
            "preview: 'AdoptionPreview | Mapping[str, object]', "
            "approved_token: 'str') -> 'dict[str, object]'"
        ),
        "rewind_adoption_by_receipt": (
            "(vault_root: 'str | Path', "
            "receipt: 'AdoptionReceipt | Mapping[str, object]', "
            "acknowledgement_token: 'str') -> 'dict[str, object]'"
        ),
        "read_lifecycle_state": "(vault_root: 'str | Path') -> 'dict[str, object]'",
        "build_and_preview_conflict_resolution": (
            "(vault_root: 'str | Path', release_root: 'str | Path', "
            "resolutions: 'Sequence[Mapping[str, object]]') -> 'dict[str, object]'"
        ),
        "execute_approved_conflict_resolution": (
            "(vault_root: 'str | Path', release_root: 'str | Path', "
            "preview: 'ConflictResolutionPreview | Mapping[str, object]', "
            "approved_token: 'str') -> 'dict[str, object]'"
        ),
        "build_archive_removal_preview": (
            "(vault_root: 'str | Path') -> 'dict[str, object]'"
        ),
        "execute_approved_archive_removal": (
            "(vault_root: 'str | Path', approved_token: 'str') "
            "-> 'dict[str, object]'"
        ),
        "build_and_preview_topology_migration": (
            "(vault_root: 'str | Path') -> 'dict[str, object]'"
        ),
        "execute_approved_topology_migration": (
            "(vault_root: 'str | Path', preview: 'Mapping[str, object]', "
            "approved_token: 'str') -> 'dict[str, object]'"
        ),
    }

    assert service.api_version == "1.4.0"
    assert {
        name: str(inspect.signature(getattr(service, name)))
        for name in expected_signatures
    } == expected_signatures
