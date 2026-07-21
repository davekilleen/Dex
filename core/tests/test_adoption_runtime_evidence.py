"""Read-only transaction, journal, lock, and ledger probes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.lifecycle.runtime_evidence import probe_runtime_evidence
from core.tests.lifecycle_test_helpers import write_file


def _journal(events: list[str]) -> bytes:
    records = []
    for sequence, event in enumerate(events, start=1):
        record = {
            "schema_version": 1,
            "sequence": sequence,
            "event": event,
            "at": "now",
            "payload": {"path": ".env", "token": "secret"},
        }
        record["sha"] = hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        records.append((json.dumps(record) + "\n").encode())
    return b"".join(records)


def test_runtime_probe_reports_state_without_exposing_lock_or_journal_payloads(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(
        vault,
        "System/.dex/mutation.lock",
        (json.dumps({"pid": 42, "kind": "transaction:test", "at": "now", "token": "never-output"}) + "\n").encode(),
    )
    write_file(vault, "System/.dex/tx/committed/journal.jsonl", _journal(["BEGIN", "COMMITTED"]))
    write_file(vault, "System/.dex/tx/interrupted/journal.jsonl", _journal(["BEGIN", "APPLY-START"]))
    write_file(vault, "System/.dex/lifecycle/ledger/events/0001.json", b"{}\n")
    write_file(vault, "System/.dex/lifecycle/state.json", b"{}\n")

    report = probe_runtime_evidence(vault)
    document = report.to_dict()

    assert report.lock.state == "PRESENT"
    assert report.lock.pid == 42
    assert {entry.path: entry.state for entry in report.transactions} == {
        "System/.dex/tx/committed": "COMMITTED",
        "System/.dex/tx/interrupted": "INTERRUPTED",
    }
    assert report.ledger.event_file_count == 1
    encoded = json.dumps(document, sort_keys=True)
    assert "never-output" not in encoded
    assert "secret" not in encoded
    assert '".env"' not in encoded


def test_malformed_runtime_evidence_is_unknown_not_guessed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(vault, "System/.dex/mutation.lock", b"not-json")
    write_file(vault, "System/.dex/tx/broken/journal.jsonl", b"not-json\n")

    report = probe_runtime_evidence(vault)

    assert report.lock.state == "UNKNOWN"
    assert report.transactions[0].state == "UNKNOWN"
    assert report.errors
