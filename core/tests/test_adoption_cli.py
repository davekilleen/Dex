"""D1 lifecycle-ledger command-line behavior."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from core.lifecycle.cli import main
from core.lifecycle.ledger import record_holdback, register_install


def _new_vault(path: Path) -> Path:
    path.mkdir()
    return path


def test_status_prints_canonical_state_json_without_writing_cache(
    tmp_path: Path, capsys
) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    state_path = vault / "System/.dex/ledger/state.json"
    state_path.unlink()

    assert main(["--vault-root", str(vault), "status"]) == 0

    output = capsys.readouterr()
    document = json.loads(output.out)
    assert document == {
        "adopted": {},
        "held_back": [],
        "install_id": "12345678-1234-4678-9234-567812345678",
        "last_event_sha256": document["last_event_sha256"],
        "last_seq": 1,
        "ledger_version": 1,
    }
    assert output.out == json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    assert output.err == ""
    assert not state_path.exists()


def test_events_lists_canonical_json_since_sequence(tmp_path: Path, capsys) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    record_holdback(vault, "alpha")

    assert main(["--vault-root", str(vault), "events", "--since", "2"]) == 0

    output = capsys.readouterr()
    events = json.loads(output.out)
    assert len(events) == 1
    assert events[0]["seq"] == 2
    assert events[0]["event_type"] == "holdback-recorded"
    assert output.out == json.dumps(events, sort_keys=True, separators=(",", ":")) + "\n"
    assert output.err == ""


def test_verify_is_read_only_and_reports_plain_success(tmp_path: Path, capsys) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    state_path = vault / "System/.dex/ledger/state.json"
    state_path.unlink()

    assert main(["--vault-root", str(vault), "verify"]) == 0

    output = capsys.readouterr()
    assert output.out == "Ledger verified: 1 immutable event forms a valid chain.\n"
    assert output.err == ""
    assert not state_path.exists()


def test_verify_returns_one_and_precise_message_for_tampering(tmp_path: Path, capsys) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    event = next((vault / "System/.dex/ledger/events").glob("*.json"))
    event.write_bytes(event.read_bytes().replace(b'"ledger_version":1', b'"ledger_version":2'))

    assert main(["--vault-root", str(vault), "verify"]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith("Ledger verification failed: event 1 ")


def test_rebuild_state_regenerates_the_cache_and_reports_action(tmp_path: Path, capsys) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    event = next((vault / "System/.dex/ledger/events").glob("*.json"))
    event_before = event.read_bytes()
    state_path = vault / "System/.dex/ledger/state.json"
    state_path.unlink()

    assert main(["--vault-root", str(vault), "rebuild-state"]) == 0

    output = capsys.readouterr()
    state = json.loads(output.out)
    assert state_path.read_bytes() == output.out.encode()
    assert state["last_seq"] == 1
    assert event.read_bytes() == event_before
    assert output.err == "Ledger rebuild-state completed: rebuilt state cache from 1 event.\n"


def test_rebuild_state_quarantines_torn_tail_and_reports_repair(tmp_path: Path, capsys) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    torn = vault / "System/.dex/ledger/events/00000002-holdback-recorded.json"
    torn.write_bytes(b"{")

    assert main(["--vault-root", str(vault), "rebuild-state"]) == 0

    output = capsys.readouterr()
    assert json.loads(output.out)["last_seq"] == 1
    assert "quarantined unreadable torn event 2" in output.err
    assert not torn.exists()
    quarantined = list((vault / "System/.dex/ledger/quarantine").iterdir())
    assert len(quarantined) == 1
    assert quarantined[0].name.startswith(torn.name + ".torn")


def test_rebuild_state_completes_valid_terminal_commitment_and_reports_repair(
    tmp_path: Path, capsys
) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    event = next((vault / "System/.dex/ledger/events").glob("*.json"))
    event_before = event.read_bytes()
    commitment = vault / "System/.dex/ledger/commitments/00000001.sha256"
    commitment.unlink()

    assert main(["--vault-root", str(vault), "rebuild-state"]) == 0

    output = capsys.readouterr()
    assert json.loads(output.out)["last_seq"] == 1
    assert "completed publication commitment for valid event 1" in output.err
    assert event.read_bytes() == event_before
    assert commitment.read_text(encoding="ascii") == json.loads(event_before)["event_sha256"] + "\n"


@pytest.mark.parametrize("command", ["status", "verify", "events"])
def test_read_only_commands_report_incomplete_publication_without_mutating(
    tmp_path: Path, capsys, command: str
) -> None:
    vault = _new_vault(tmp_path / "vault")
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    event = next((vault / "System/.dex/ledger/events").glob("*.json"))
    event_before = event.read_bytes()
    state_path = vault / "System/.dex/ledger/state.json"
    state_before = state_path.read_bytes()
    commitment = vault / "System/.dex/ledger/commitments/00000001.sha256"
    commitment.unlink()

    assert main(["--vault-root", str(vault), command]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert "publication is incomplete" in output.err
    assert f"python3 -m core.lifecycle.cli --vault-root {vault} rebuild-state" in output.err
    assert event.read_bytes() == event_before
    assert state_path.read_bytes() == state_before
    assert not commitment.exists()


def test_cli_rejects_negative_since_with_argparse_exit_two(tmp_path: Path) -> None:
    vault = _new_vault(tmp_path / "vault")

    try:
        main(["--vault-root", str(vault), "events", "--since", "-1"])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("negative --since must be rejected")
