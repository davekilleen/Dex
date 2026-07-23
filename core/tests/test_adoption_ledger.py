"""D1 lifecycle ledger: immutable history and rebuildable state."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
from pathlib import Path
from uuid import UUID

import pytest

from core import portable_contract
from core.lifecycle import ledger as ledger_module
from core.lifecycle.engine import (
    AdoptionReceipt,
    LifecycleLedgerPersistenceError,
    RewindReceipt,
    RewindReceiptFile,
    execute_adoption,
    rewind_acknowledgement_token,
    rewind_adoption,
)
from core.lifecycle.ledger import (
    GENESIS_SHA256,
    LedgerError,
    canonical_state_bytes,
    clear_holdback,
    project_state,
    read_events,
    rebuild_state,
    record_adoption,
    record_holdback,
    record_rewind,
    register_install,
)
from core.tests.test_adoption_rewind import CREATED_PATH, EXISTING_PATH, OLD, _committed_adoption
from core.tests.test_adoption_transaction import _preview


def _adoption_receipt(
    *,
    tx_id: str = "20260721T120000-00000001",
    items: tuple[str, ...] = ("alpha",),
) -> AdoptionReceipt:
    return AdoptionReceipt.from_dict(
        {
            "receipt_version": 1,
            "items_adopted": list(items),
            "files_written": [
                {
                    "item_id": item_id,
                    "path": f".claude/skills/{item_id}/SKILL.md",
                    "sha256": hashlib.sha256(item_id.encode()).hexdigest(),
                    "byte_size": len(item_id),
                }
                for item_id in items
            ],
            "transaction_id": tx_id,
            "snapshot_ref": f"System/.dex/tx/{tx_id}/snapshot",
            "catalog_sha256": "a" * 64,
            "inventory_sha256": "b" * 64,
            "preview_sha256": "c" * 64,
        }
    )


def _rewind_receipt(receipt: AdoptionReceipt) -> RewindReceipt:
    rewind_tx = "20260721T120001-00000002"
    return RewindReceipt(
        1,
        receipt.transaction_id,
        rewind_tx,
        f"System/.dex/tx/{rewind_tx}/snapshot",
        hashlib.sha256(
            (json.dumps(receipt.to_dict(), sort_keys=True, separators=(",", ":")) + "\n").encode()
        ).hexdigest(),
        tuple(
            RewindReceiptFile(item_id, f".claude/skills/{item_id}/SKILL.md", False, None, None, None)
            for item_id in receipt.items_adopted
        ),
    )


def _event_files(vault: Path) -> list[Path]:
    return sorted((vault / "System/.dex/ledger/events").glob("*.json"))


def _new_vault(path: Path) -> Path:
    path.mkdir()
    return path


def test_events_are_canonical_self_hashed_and_hash_chained(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    install_id = UUID("12345678-1234-4678-9234-567812345678")

    register_install(vault, install_id)
    record_holdback(vault, "alpha")
    clear_holdback(vault, "alpha")

    events = read_events(vault)
    assert [event["seq"] for event in events] == [1, 2, 3]
    assert [event["event_type"] for event in events] == [
        "install-registered",
        "holdback-recorded",
        "holdback-cleared",
    ]
    assert events[0]["prev_event_sha256"] == GENESIS_SHA256
    assert events[1]["prev_event_sha256"] == events[0]["event_sha256"]
    assert events[2]["prev_event_sha256"] == events[1]["event_sha256"]
    for path, event in zip(_event_files(vault), events, strict=True):
        assert path.name == f"{event['seq']:08d}-{event['event_type']}.json"
        assert path.read_bytes().endswith(b"\n")
        assert json.loads(path.read_bytes()) == event


def test_ledger_setup_does_not_change_parent_directory_permissions(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    system = vault / "System"
    dex = system / ".dex"
    dex.mkdir(parents=True)
    os.chmod(system, 0o755)
    os.chmod(dex, 0o750)

    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))

    assert stat.S_IMODE(system.stat().st_mode) == 0o755
    assert stat.S_IMODE(dex.stat().st_mode) == 0o750


@pytest.mark.parametrize("event_index", [0, 1, 2])
def test_mutating_any_historical_event_fails_closed(tmp_path: Path, event_index: int) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    record_holdback(vault, "alpha")
    clear_holdback(vault, "alpha")
    target = _event_files(vault)[event_index]
    raw = target.read_bytes()
    target.write_bytes(raw.replace(b'"ledger_version":1', b'"ledger_version":9', 1))

    with pytest.raises(LedgerError, match=r"event .*integrity hash|unsupported ledger version"):
        rebuild_state(vault)


@pytest.mark.parametrize("event_index", [0, 1, 2])
def test_deleting_any_historical_event_fails_closed(tmp_path: Path, event_index: int) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    record_holdback(vault, "alpha")
    clear_holdback(vault, "alpha")
    _event_files(vault)[event_index].unlink()

    with pytest.raises(LedgerError, match=r"gap|rollback|missing"):
        rebuild_state(vault)


def test_terminal_event_deletion_is_detected_without_state_cache(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    record_holdback(vault, "alpha")
    (vault / "System/.dex/ledger/state.json").unlink()
    _event_files(vault)[-1].unlink()

    with pytest.raises(LedgerError, match=r"missing.*event.*sequence 2"):
        rebuild_state(vault)


def test_terminal_event_truncation_is_not_quarantined_without_state_cache(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    state_path = vault / "System/.dex/ledger/state.json"
    state_path.unlink()
    event = _event_files(vault)[0]
    event.write_bytes(b"{")

    with pytest.raises(LedgerError, match=r"event 1.*unreadable"):
        rebuild_state(vault)

    assert event.exists()


def test_next_record_completes_missing_terminal_commitment(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    event = _event_files(vault)[0]
    event_before = event.read_bytes()
    commitment = vault / "System/.dex/ledger/commitments/00000001.sha256"
    commitment.unlink()

    state = record_holdback(vault, "alpha")

    assert state["last_seq"] == 2
    assert event.read_bytes() == event_before
    assert commitment.read_text(encoding="ascii") == json.loads(event_before)["event_sha256"] + "\n"
    assert [entry["event_type"] for entry in read_events(vault)] == [
        "install-registered",
        "holdback-recorded",
    ]
    assert not (vault / "System/.dex/ledger/quarantine").exists()


def test_chain_invalid_uncommitted_tail_is_never_completed_or_quarantined(
    tmp_path: Path,
) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    event_path = _event_files(vault)[0]
    event = json.loads(event_path.read_bytes())
    event["prev_event_sha256"] = "f" * 64
    without_sha = {key: value for key, value in event.items() if key != "event_sha256"}
    event["event_sha256"] = ledger_module._event_sha256(without_sha)
    event_path.write_bytes(
        (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    commitment = vault / "System/.dex/ledger/commitments/00000001.sha256"
    commitment.unlink()

    with pytest.raises(LedgerError, match=r"event 1.*breaks the hash chain"):
        rebuild_state(vault)

    assert event_path.exists()
    assert not commitment.exists()
    assert not (vault / "System/.dex/ledger/quarantine").exists()


def test_state_floor_mismatch_prevents_completing_uncommitted_tail(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    event_path = _event_files(vault)[0]
    event = json.loads(event_path.read_bytes())
    event["payload"] = {"install_id": "87654321-4321-4765-8765-432187654321"}
    without_sha = {key: value for key, value in event.items() if key != "event_sha256"}
    event["event_sha256"] = ledger_module._event_sha256(without_sha)
    event_path.write_bytes(
        (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    commitment = vault / "System/.dex/ledger/commitments/00000001.sha256"
    commitment.unlink()

    with pytest.raises(LedgerError, match=r"possible.*history replacement"):
        rebuild_state(vault)

    assert event_path.exists()
    assert not commitment.exists()
    assert not (vault / "System/.dex/ledger/quarantine").exists()


def test_rebuild_state_serializes_with_event_publication(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def rebuild() -> None:
        started.set()
        try:
            rebuild_state(vault)
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    with ledger_module._write_lock(vault):
        worker = threading.Thread(target=rebuild)
        worker.start()
        assert started.wait(timeout=1)
        assert not finished.wait(timeout=0.05)

    worker.join(timeout=1)
    assert not worker.is_alive()
    assert errors == []


def test_read_only_projection_serializes_with_event_publication(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    started = threading.Event()
    finished = threading.Event()

    def project() -> None:
        started.set()
        try:
            ledger_module.project_state(vault)
        finally:
            finished.set()

    with ledger_module._write_lock(vault):
        worker = threading.Thread(target=project)
        worker.start()
        assert started.wait(timeout=1)
        assert not finished.wait(timeout=0.05)

    worker.join(timeout=1)
    assert not worker.is_alive()


def test_boolean_schema_versions_fail_closed_even_with_matching_hashes(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    event_path = _event_files(vault)[0]
    event = json.loads(event_path.read_bytes())
    event["ledger_version"] = True
    without_sha = {key: value for key, value in event.items() if key != "event_sha256"}
    event["event_sha256"] = ledger_module._event_sha256(without_sha)
    event_path.write_bytes(
        (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    commitment = vault / "System/.dex/ledger/commitments/00000001.sha256"
    commitment.write_text(event["event_sha256"] + "\n", encoding="ascii")

    with pytest.raises(LedgerError, match="unsupported ledger version"):
        rebuild_state(vault)

    empty = {
        "ledger_version": True,
        "install_id": None,
        "adopted": {},
        "held_back": [],
        "last_seq": 0,
        "last_event_sha256": GENESIS_SHA256,
    }
    with pytest.raises(LedgerError, match="unsupported version"):
        canonical_state_bytes(empty)


def test_retry_after_state_cache_failure_does_not_duplicate_transaction_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _new_vault(tmp_path / "vault")
    receipt = _adoption_receipt()
    real_write_state = ledger_module._write_state
    calls = 0

    def fail_once(vault_root: Path, state: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected cache failure")
        real_write_state(vault_root, state)

    monkeypatch.setattr(ledger_module, "_write_state", fail_once)

    with pytest.raises(OSError, match="injected cache failure"):
        record_adoption(vault, receipt, {"alpha": "1.0.0"})
    state = record_adoption(vault, receipt, {"alpha": "1.0.0"})

    assert state["last_seq"] == 2
    assert len(read_events(vault)) == 2


def test_write_lock_refuses_symlink_without_touching_target(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    ledger_root = vault / "System/.dex/ledger"
    ledger_root.mkdir(parents=True)
    outside = tmp_path / "outside-lock"
    outside.write_bytes(b"outside\n")
    (ledger_root / ".write.lock").symlink_to(outside)

    with pytest.raises(LedgerError, match=r"lock.*unsafe"):
        register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))

    assert outside.read_bytes() == b"outside\n"


def test_gap_and_fork_are_detected_precisely(tmp_path: Path) -> None:
    gap_vault = _new_vault(tmp_path / "gap")
    register_install(gap_vault, UUID("12345678-1234-4678-9234-567812345678"))
    record_holdback(gap_vault, "alpha")
    second = _event_files(gap_vault)[1]
    second.rename(second.with_name(second.name.replace("00000002", "00000003")))
    with pytest.raises(LedgerError, match=r"sequence gap.*expected 2.*found 3"):
        rebuild_state(gap_vault)

    fork_vault = _new_vault(tmp_path / "fork")
    register_install(fork_vault, UUID("87654321-4321-4765-8765-432187654321"))
    record_holdback(fork_vault, "alpha")
    second = _event_files(fork_vault)[1]
    second.with_name("00000002-holdback-cleared.json").write_bytes(second.read_bytes())
    with pytest.raises(LedgerError, match=r"fork.*sequence 2"):
        rebuild_state(fork_vault)


def test_torn_last_event_is_quarantined_but_interior_damage_fails(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    events_dir = vault / "System/.dex/ledger/events"
    torn = events_dir / "00000002-holdback-recorded.json"
    torn.write_bytes(b'{"event_type":"holdback-recorded"')

    state = rebuild_state(vault)

    assert state["last_seq"] == 1
    assert not torn.exists()
    quarantined = list((vault / "System/.dex/ledger/quarantine").iterdir())
    assert len(quarantined) == 1
    assert quarantined[0].name.startswith(torn.name + ".torn")

    record_holdback(vault, "alpha")
    first = _event_files(vault)[0]
    first.write_bytes(b"{")
    with pytest.raises(LedgerError, match="unreadable"):
        rebuild_state(vault)


def test_state_rebuild_is_byte_identical_after_cache_deletion(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    receipt = _adoption_receipt(items=("alpha", "beta"))
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    record_adoption(vault, receipt, {"alpha": "1.0.0", "beta": "2.0.0"})
    record_holdback(vault, "beta")
    state_path = vault / "System/.dex/ledger/state.json"
    first = state_path.read_bytes()

    state_path.unlink()
    rebuilt = rebuild_state(vault)

    assert state_path.read_bytes() == first == canonical_state_bytes(rebuilt)
    assert rebuilt["adopted"] == {
        "alpha": {
            "receipt_path": f"System/.dex/adoptions/{receipt.transaction_id}.receipt.json",
            "tx_id": receipt.transaction_id,
            "version": "1.0.0",
        },
        "beta": {
            "receipt_path": f"System/.dex/adoptions/{receipt.transaction_id}.receipt.json",
            "tx_id": receipt.transaction_id,
            "version": "2.0.0",
        },
    }
    assert rebuilt["held_back"] == ["beta"]


def test_state_floor_detects_joint_terminal_event_and_commitment_deletion(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    record_holdback(vault, "alpha")
    state_path = vault / "System/.dex/ledger/state.json"
    state_before = state_path.read_bytes()
    _event_files(vault)[-1].unlink()
    (vault / "System/.dex/ledger/commitments/00000002.sha256").unlink()

    with pytest.raises(LedgerError, match=r"possible.*tail loss.*backup|sync.*newest files"):
        rebuild_state(vault)

    assert state_path.read_bytes() == state_before


def test_state_floor_detects_replaced_terminal_event_at_same_sequence(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    record_holdback(vault, "alpha")
    event_path = _event_files(vault)[-1]
    event = json.loads(event_path.read_bytes())
    event["payload"] = {"item_id": "beta"}
    without_sha = {key: value for key, value in event.items() if key != "event_sha256"}
    event["event_sha256"] = ledger_module._event_sha256(without_sha)
    event_path.write_bytes(
        (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    (vault / "System/.dex/ledger/commitments/00000002.sha256").write_text(
        event["event_sha256"] + "\n", encoding="ascii"
    )

    with pytest.raises(LedgerError, match=r"possible.*tail loss|history replacement"):
        project_state(vault)


def test_first_state_build_without_existing_cache_is_unaffected(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")

    state = rebuild_state(vault)

    assert state["last_seq"] == 0
    assert (vault / "System/.dex/ledger/state.json").read_bytes() == canonical_state_bytes(state)


def test_install_id_is_stable_and_reregistration_refuses_without_append(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    install_id = UUID("12345678-1234-4678-9234-567812345678")
    register_install(vault, install_id)
    before = _event_files(vault)[0].read_bytes()

    with pytest.raises(LedgerError, match="already registered"):
        register_install(vault, install_id)
    with pytest.raises(LedgerError, match="already registered"):
        register_install(vault, UUID("87654321-4321-4765-8765-432187654321"))

    assert len(_event_files(vault)) == 1
    assert _event_files(vault)[0].read_bytes() == before


def test_first_lifecycle_record_automatically_registers_install(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")

    state = record_holdback(vault, "alpha")

    install_id = UUID(str(state["install_id"]))
    assert install_id.version == 4
    assert [event["event_type"] for event in read_events(vault)] == [
        "install-registered",
        "holdback-recorded",
    ]


def test_record_helpers_strictly_validate_receipts_versions_and_ids(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    receipt = _adoption_receipt()
    malformed = receipt.to_dict()
    malformed["surprise"] = True

    with pytest.raises(LedgerError, match="receipt"):
        record_adoption(vault, malformed, {"alpha": "1.0.0"})
    with pytest.raises(LedgerError, match="versions"):
        record_adoption(vault, receipt, {"other": "1.0.0"})
    with pytest.raises(LedgerError, match="item id"):
        record_holdback(vault, "../alpha")
    assert _event_files(vault) == []


def test_rewind_event_durably_embeds_receipt_and_removes_matching_adoption(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    adoption = _adoption_receipt()
    rewind = _rewind_receipt(adoption)
    record_adoption(vault, adoption, {"alpha": "1.0.0"})

    state = record_rewind(vault, rewind)

    assert state["adopted"] == {}
    assert read_events(vault)[2]["payload"]["receipt"] == rewind.to_dict()


def test_append_refuses_sequence_beyond_filename_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _new_vault(tmp_path / "vault")
    fake_tail = {
        "seq": 99_999_999,
        "event_type": "holdback-recorded",
        "payload": {"item_id": "alpha"},
        "event_sha256": "a" * 64,
    }
    monkeypatch.setattr(ledger_module, "_load_events", lambda *_args, **_kwargs: [fake_tail])

    with pytest.raises(LedgerError, match=r"99,999,999|99999999.*maximum"):
        ledger_module._publish_event(vault, "holdback-recorded", {"item_id": "beta"})

    assert _event_files(vault) == []


def test_record_never_rewrites_an_existing_sequence_file(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    first = _event_files(vault)[0]
    original = first.read_bytes()
    occupied = first.with_name("00000002-holdback-recorded.json")
    occupied.write_bytes(b"do not overwrite\n")

    with pytest.raises(LedgerError):
        record_holdback(vault, "alpha")

    assert first.read_bytes() == original
    assert occupied.read_bytes() == b"do not overwrite\n"


def test_execute_adoption_records_real_receipt_and_item_version(tmp_path: Path) -> None:
    vault, _document, preview, loader = _preview(tmp_path)

    receipt = execute_adoption(vault, preview, preview.sha256, loader)
    state = rebuild_state(vault)

    assert state["adopted"] == {
        "alpha": {
            "receipt_path": f"System/.dex/adoptions/{receipt.transaction_id}.receipt.json",
            "tx_id": receipt.transaction_id,
            "version": "1.0.0",
        }
    }
    event = read_events(vault)[1]
    assert event["event_type"] == "adoption-recorded"
    assert event["payload"]["receipt"] == receipt.to_dict()
    assert portable_contract.resolve("System/.dex/ledger/events/00000001-adoption-recorded.json").rule_id == (
        "runtime-lifecycle-ledger"
    )


def test_ledger_failure_after_adoption_reports_without_rolling_back_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.lifecycle import ledger

    vault, _document, preview, loader = _preview(tmp_path)
    target = vault / ".claude/skills/alpha/SKILL.md"

    def fail_record(*_args, **_kwargs):
        raise LedgerError("injected ledger failure")

    monkeypatch.setattr(ledger, "record_adoption", fail_record)

    with pytest.raises(
        LifecycleLedgerPersistenceError,
        match=r"committed.*journal is authoritative.*python3 -m core.lifecycle.cli.*rebuild-state",
    ):
        execute_adoption(vault, preview, preview.sha256, loader)

    assert target.read_bytes() == b"# alpha\n"
    receipts = list((vault / "System/.dex/adoptions").glob("*.receipt.json"))
    assert len(receipts) == 1


def test_rewind_flow_durably_records_preledger_adoption_receipt(tmp_path: Path) -> None:
    vault, adoption = _committed_adoption(tmp_path)

    rewind = rewind_adoption(vault, adoption, rewind_acknowledgement_token(adoption))

    events = read_events(vault)
    assert len(events) == 2
    assert events[1]["event_type"] == "rewind-recorded"
    assert events[1]["payload"]["receipt"] == rewind.to_dict()


def test_ledger_failure_after_rewind_reports_without_rolling_back_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.lifecycle import ledger

    vault, adoption = _committed_adoption(tmp_path)

    def fail_record(*_args, **_kwargs):
        raise LedgerError("injected ledger failure")

    monkeypatch.setattr(ledger, "record_rewind", fail_record)

    with pytest.raises(
        LifecycleLedgerPersistenceError,
        match=r"committed.*journal is authoritative.*python3 -m core.lifecycle.cli.*rebuild-state",
    ):
        rewind_adoption(vault, adoption, rewind_acknowledgement_token(adoption))

    assert (vault / EXISTING_PATH).read_bytes() == OLD
    assert not (vault / CREATED_PATH).exists()
