"""Append-only, fsynced, torn-tail-tolerant transaction journal.

The journal is the transaction's single source of truth: every state
transition is appended (and fsynced) BEFORE the action it describes takes
effect — "intent before act" — so crash recovery can always reconstruct
where a transaction died from the journal alone.

Format: one JSON object per line. Every line carries its own integrity hash
(``sha`` = sha256 of the canonical entry without the ``sha`` field), so a
torn final line — the only corruption an append-only fsynced file can suffer
from a crash — is detected and dropped on read. Any corruption EARLIER in
the file is not survivable-by-guessing: reads fail closed with
:class:`JournalCorruptError` rather than trusting a damaged history.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 2
PREVIOUS_SCHEMA_VERSION = 1
RESUMABLE_SCHEMA_VERSIONS = frozenset({PREVIOUS_SCHEMA_VERSION, SCHEMA_VERSION})


class JournalCorruptError(RuntimeError):
    """The journal has damage that cannot be attributed to a torn tail."""


class JournalSchemaError(JournalCorruptError):
    """The journal is intact but outside the current+previous resume window."""

    def __init__(self, schema_version: object, path: Path) -> None:
        self.schema_version = schema_version
        super().__init__(f"journal has an unsupported schema {schema_version!r}: {path}")


@dataclass(frozen=True)
class JournalEntry:
    sequence: int
    event: str
    payload: dict


def _canonical(record: dict) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _entry_sha(record: dict) -> str:
    without_sha = {key: value for key, value in record.items() if key != "sha"}
    return hashlib.sha256(_canonical(without_sha)).hexdigest()


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class Journal:
    """One transaction's journal file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def append(self, event: str, payload: dict | None = None) -> JournalEntry:
        """Append one entry; fsync file and parent before returning.

        A torn tail from an earlier crash is truncated first — it is by
        definition not part of history (read() already ignores it), and
        appending after it would wedge the file.
        """
        entries = self.read()
        self._truncate_torn_tail()
        sequence = entries[-1].sequence + 1 if entries else 1
        record = {
            "schema_version": SCHEMA_VERSION,
            "sequence": sequence,
            "event": str(event),
            "at": datetime.now(timezone.utc).isoformat(),
            "payload": payload or {},
        }
        record["sha"] = _entry_sha(record)
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"

        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(
            self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
        )
        try:
            os.write(descriptor, line.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(self.path.parent)
        return JournalEntry(sequence, record["event"], record["payload"])

    def _truncate_torn_tail(self) -> None:
        """Drop any bytes after the final newline that don't parse as a
        complete, hash-valid entry. Called only from append(), after read()
        has validated the preceding history."""
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return
        newline = raw.rfind(b"\n")
        tail = raw[newline + 1 :]
        if not tail:
            return
        try:
            self._parse_line(tail, -1)
        except JournalCorruptError:
            pass
        else:
            # A complete, hash-valid entry merely missing its newline: keep
            # it and finish the line so the next append starts fresh.
            descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND)
            try:
                os.write(descriptor, b"\n")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return
        keep = raw[: newline + 1] if newline >= 0 else b""
        descriptor = os.open(self.path, os.O_WRONLY)
        try:
            os.ftruncate(descriptor, len(keep))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def read(self) -> list[JournalEntry]:
        """All valid entries. A torn FINAL line is dropped; anything else
        malformed fails closed."""
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return []
        entries: list[JournalEntry] = []
        lines = raw.split(b"\n")
        # A well-formed file ends with a newline, so the final split element
        # is empty; anything after the last newline is a torn tail candidate.
        tail = lines.pop() if lines else b""
        for index, line in enumerate(lines):
            if not line:
                if index != len(lines) - 1 and index != len(lines):
                    # Interior blank line: not a torn tail.
                    raise JournalCorruptError(
                        f"journal has an interior blank line: {self.path}"
                    )
                continue
            entries.append(self._parse_line(line, index))
        if tail:
            # Bytes after the final newline: the classic torn append. Try to
            # parse — a complete, hash-valid record just missing its newline
            # is accepted; anything else is dropped as the torn tail.
            try:
                entries.append(self._parse_line(tail, len(lines)))
            except JournalCorruptError:
                pass
        self._check_sequence(entries)
        return entries

    def _parse_line(self, line: bytes, index: int) -> JournalEntry:
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise JournalCorruptError(
                f"journal line {index + 1} is unreadable: {self.path}"
            ) from error
        if not isinstance(record, dict):
            raise JournalCorruptError(
                f"journal line {index + 1} is not an object: {self.path}"
            )
        schema_version = record.get("schema_version")
        if type(schema_version) is not int or schema_version not in RESUMABLE_SCHEMA_VERSIONS:
            raise JournalSchemaError(schema_version, self.path)
        if record.get("sha") != _entry_sha(record):
            raise JournalCorruptError(
                f"journal line {index + 1} fails its integrity hash: {self.path}"
            )
        sequence = record.get("sequence")
        event = record.get("event")
        payload = record.get("payload")
        if not isinstance(sequence, int) or not isinstance(event, str) or not isinstance(payload, dict):
            raise JournalCorruptError(
                f"journal line {index + 1} has invalid fields: {self.path}"
            )
        return JournalEntry(sequence, event, payload)

    @staticmethod
    def _check_sequence(entries: list[JournalEntry]) -> None:
        for position, entry in enumerate(entries, start=1):
            if entry.sequence != position:
                raise JournalCorruptError(
                    "journal sequence numbers are not contiguous — history is "
                    "missing or reordered"
                )
