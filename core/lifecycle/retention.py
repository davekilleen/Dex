"""Read-only reporting for Dex's lean transaction-snapshot retention."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core.transaction.journal import Journal, JournalCorruptError

RETENTION_WARNING_BYTES = 2 * 1024**3
TX_RELATIVE = Path("System") / ".dex" / "tx"


@dataclass(frozen=True)
class RetentionReport:
    """Current transaction-store footprint; warning is advisory only."""

    total_bytes: int
    committed_snapshot_count: int
    warning: bool
    warning_threshold_bytes: int


def _total_file_bytes(root: Path) -> int:
    total = 0
    for directory, _subdirectories, filenames in os.walk(root, followlinks=False):
        parent = Path(directory)
        for filename in filenames:
            candidate = parent / filename
            try:
                if not candidate.is_symlink() and candidate.is_file():
                    total += candidate.stat().st_size
            except FileNotFoundError:
                continue
    return total


def _committed_snapshots(tx_root: Path) -> int:
    count = 0
    for candidate in tx_root.iterdir():
        snapshot = candidate / "snapshot"
        if not candidate.is_dir() or snapshot.is_symlink() or not snapshot.is_dir():
            continue
        try:
            events = [
                entry.event for entry in Journal(candidate / "journal.jsonl").read()
            ]
        except JournalCorruptError:
            continue
        if events.count("COMMITTED") == 1 and "ROLLED-BACK" not in events:
            count += 1
    return count


def compute_retention_report(vault_root: Path) -> RetentionReport:
    """Measure retained transaction state and warn above 2 GiB without blocking."""
    tx_root = Path(vault_root) / TX_RELATIVE
    if tx_root.is_symlink() or not tx_root.is_dir():
        return RetentionReport(0, 0, False, RETENTION_WARNING_BYTES)
    total_bytes = _total_file_bytes(tx_root)
    return RetentionReport(
        total_bytes,
        _committed_snapshots(tx_root),
        total_bytes > RETENTION_WARNING_BYTES,
        RETENTION_WARNING_BYTES,
    )


__all__ = [
    "RETENTION_WARNING_BYTES",
    "RetentionReport",
    "compute_retention_report",
]
