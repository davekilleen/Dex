"""Helpers for Windows byte-mode Phase 2 tests.

Fixtures are stored LF in git; tests add the trailing CR so autocrlf cannot
rewrite the committed bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.lifecycle.bridge import _canonical
from core.lifecycle.byte_mode import canonical_topology_receipt_bytes
from core.lifecycle.engine import AdoptionReceipt, canonical_adoption_receipt_bytes
from core.lifecycle.ledger import _canonical_bytes

TX_ID = "20260128T120000-abcd1234"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "byte-mode"


def crlf_variant(canonical: bytes) -> bytes:
    return canonical.replace(b"\n", b"\r\n")


def interior_crlf_variant(canonical: bytes) -> bytes:
    """A non-trailing CRLF change the migration must not repair."""
    if b"," not in canonical:
        return canonical[:-1] + b"\r\n extra\n"
    return canonical.replace(b",", b",\r\n", 1)


def sample_activation() -> dict[str, object]:
    return {
        "activation_version": 1,
        "api_version": "1.5.0",
        "baseline_inventory_sha256": "a" * 64,
        "bridge_release_version": "1.64.0",
    }


def sample_receipt() -> AdoptionReceipt:
    return AdoptionReceipt.from_dict(
        {
            "receipt_version": 1,
            "items_adopted": ["alpha"],
            "files_written": [
                {
                    "item_id": "alpha",
                    "path": "README.md",
                    "sha256": "b" * 64,
                    "byte_size": 12,
                }
            ],
            "transaction_id": TX_ID,
            "snapshot_ref": f"System/.dex/tx/{TX_ID}/snapshot",
            "catalog_sha256": "c" * 64,
            "inventory_sha256": "d" * 64,
            "preview_sha256": "e" * 64,
        }
    )


def sample_topology_receipt() -> dict[str, object]:
    return {
        "archive_ref": None,
        "attempts": [{"exit_code": 0, "mode": "auto"}],
        "final_report_path": "System/.dex/topology-report.md",
        "final_report_sha256": "f" * 64,
        "migration_started_at": None,
        "operation": "brain-vault-topology",
        "preview_sha256": "1" * 64,
        "receipt_version": 1,
        "topology_after": "post-split",
        "topology_before": "combined",
        "transaction_id": TX_ID,
    }


def sample_ledger_event() -> dict[str, object]:
    without_sha = {
        "event_type": "install-registered",
        "ledger_version": 1,
        "payload": {"install_id": "12345678-1234-4678-9234-567812345678"},
        "prev_event_sha256": "0" * 64,
        "seq": 1,
    }
    digest = hashlib.sha256(
        _canonical_bytes(without_sha, "lifecycle event")
    ).hexdigest()
    return {**without_sha, "event_sha256": digest}


def write_lf_fixture(relative: str, document: object, *, canonical: bytes) -> Path:
    target = FIXTURE_DIR / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical)
    return target


def activation_bytes() -> bytes:
    return _canonical(sample_activation())


def receipt_bytes() -> bytes:
    return canonical_adoption_receipt_bytes(sample_receipt())


def topology_bytes() -> bytes:
    return canonical_topology_receipt_bytes(sample_topology_receipt())


def event_bytes() -> bytes:
    return _canonical_bytes(sample_ledger_event(), "lifecycle event")


def write_receipt(vault: Path, raw: bytes, transaction_id: str = TX_ID) -> Path:
    path = vault / "System/.dex/adoptions" / f"{transaction_id}.receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def write_topology_receipt(vault: Path, raw: bytes, transaction_id: str = TX_ID) -> Path:
    path = vault / "System/.dex/topology-migrations" / f"{transaction_id}.receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def write_activation(vault: Path, raw: bytes) -> Path:
    path = vault / "System/.dex/lifecycle/activation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def write_ledger_event(vault: Path, raw: bytes) -> Path:
    path = vault / "System/.dex/ledger/events" / "00000001-install-registered.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path
