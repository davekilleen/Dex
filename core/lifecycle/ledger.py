"""Immutable lifecycle events with a rebuildable local state projection.

The transaction journal remains the authority for filesystem commits.  This
ledger records lifecycle meaning after those commits: event publication never
rewrites an existing sequence file, and a cache-write failure never alters an
already published event.  An append-only ``commitments/<seq>.sha256`` witness
marks publication complete, while the state cache is also a high-water mark
against joint tail loss.  An interrupted publication is repaired only while
holding the exclusive write lock.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID, uuid4

from core.lifecycle.engine import (
    AdoptionExecutionError,
    AdoptionReceipt,
    RewindReceipt,
)
from core.lifecycle.model import HEX_SHA256, ITEM_ID, SEMVER

LEDGER_VERSION = 1
GENESIS_SHA256 = "0" * 64
MAX_SEQUENCE = 99_999_999
LEDGER_RELATIVE = Path("System") / ".dex" / "ledger"
EVENT_TYPES = frozenset(
    {
        "install-registered",
        "adoption-recorded",
        "rewind-recorded",
        "holdback-recorded",
        "holdback-cleared",
    }
)
EVENT_FILENAME = re.compile(
    r"^(?P<seq>[0-9]{8})-(?P<event_type>"
    + "|".join(sorted(EVENT_TYPES))
    + r")\.json$"
)
COMMITMENT_FILENAME = re.compile(r"^(?P<seq>[0-9]{8})\.sha256$")
EVENT_FIELDS = {
    "ledger_version",
    "seq",
    "event_type",
    "prev_event_sha256",
    "payload",
    "event_sha256",
}
STATE_FIELDS = {
    "ledger_version",
    "install_id",
    "adopted",
    "held_back",
    "last_seq",
    "last_event_sha256",
}


class LedgerError(RuntimeError):
    """The lifecycle ledger is unsafe, invalid, or could not be updated."""


class _UnreadableEvent(LedgerError):
    """A byte-level parse failure that may be a torn final publication."""


def _canonical_bytes(value: object, context: str) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise LedgerError(f"{context} cannot be serialized canonically: {error}") from error


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ledger_paths(vault_root: Path) -> tuple[Path, Path, Path]:
    ledger_root = Path(vault_root) / LEDGER_RELATIVE
    return ledger_root, ledger_root / "events", ledger_root / "state.json"


def _check_existing_directory(path: Path, context: str) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise LedgerError(f"ledger path is unsafe at {context}: {path}")


def _ensure_directories(vault_root: Path) -> tuple[Path, Path, Path]:
    root = Path(vault_root)
    _check_existing_directory(root, "vault root")
    if not root.is_dir():
        raise LedgerError(f"vault root does not exist: {root}")
    ledger_root, events_dir, state_path = _ledger_paths(root)
    parents = (root / "System", root / "System/.dex")
    for component in parents:
        _check_existing_directory(component, str(component.relative_to(root)))
        component.mkdir(exist_ok=True, mode=0o700)
    for component in (ledger_root, events_dir, ledger_root / "commitments"):
        _check_existing_directory(component, str(component.relative_to(root)))
        component.mkdir(exist_ok=True, mode=0o700)
        os.chmod(component, 0o700)
    return ledger_root, events_dir, state_path


def _strict_json(raw: bytes, context: str) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise LedgerError(f"{context} repeats field {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except LedgerError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _UnreadableEvent(f"{context} is unreadable or torn") from error


def _closed_mapping(
    raw: object,
    *,
    fields: set[str],
    context: str,
) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
        raise LedgerError(f"{context} must be an object with string field names")
    missing = fields - set(raw)
    unknown = set(raw) - fields
    if missing:
        raise LedgerError(f"{context} is missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise LedgerError(f"{context} has unknown fields: {', '.join(sorted(unknown))}")
    return raw


def _item_id(raw: object, context: str = "ledger item id") -> str:
    if not isinstance(raw, str) or ITEM_ID.fullmatch(raw) is None:
        raise LedgerError(f"{context} is not a canonical item id")
    return raw


def _semver(raw: object, context: str) -> str:
    if not isinstance(raw, str) or SEMVER.fullmatch(raw) is None:
        raise LedgerError(f"{context} is not strict SemVer")
    return raw


def _uuid4(raw: object) -> str:
    text = str(raw) if isinstance(raw, UUID) else raw
    if not isinstance(text, str):
        raise LedgerError("install_id must be a canonical UUID4 string")
    try:
        value = UUID(text)
    except (AttributeError, TypeError, ValueError) as error:
        raise LedgerError("install_id must be a canonical UUID4 string") from error
    if str(value) != text or value.version != 4:
        raise LedgerError("install_id must be a canonical UUID4 string")
    return text


def _validated_adoption(raw: object) -> AdoptionReceipt:
    try:
        document = raw.to_dict() if isinstance(raw, AdoptionReceipt) else raw
        return AdoptionReceipt.from_dict(document)
    except (AdoptionExecutionError, AttributeError, TypeError, ValueError) as error:
        raise LedgerError(f"adoption receipt is invalid: {error}") from error


def _validated_rewind(raw: object) -> RewindReceipt:
    try:
        document = raw.to_dict() if isinstance(raw, RewindReceipt) else raw
        return RewindReceipt.from_dict(document)
    except (AdoptionExecutionError, AttributeError, TypeError, ValueError) as error:
        raise LedgerError(f"rewind receipt is invalid: {error}") from error


def _validated_versions(
    raw: object,
    receipt: AdoptionReceipt,
) -> dict[str, str]:
    if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
        raise LedgerError("adoption item versions must be an object")
    if set(raw) != set(receipt.items_adopted):
        raise LedgerError("adoption item versions must exactly match the receipt items")
    return {
        item_id: _semver(raw[item_id], f"adoption item {item_id} version")
        for item_id in sorted(raw)
    }


def _validated_payload(event_type: str, raw: object) -> dict[str, object]:
    if event_type == "install-registered":
        payload = _closed_mapping(raw, fields={"install_id"}, context="install event payload")
        return {"install_id": _uuid4(payload["install_id"])}
    if event_type == "adoption-recorded":
        payload = _closed_mapping(
            raw,
            fields={"receipt", "item_versions"},
            context="adoption event payload",
        )
        receipt = _validated_adoption(payload["receipt"])
        versions = _validated_versions(payload["item_versions"], receipt)
        return {"receipt": receipt.to_dict(), "item_versions": versions}
    if event_type == "rewind-recorded":
        payload = _closed_mapping(raw, fields={"receipt"}, context="rewind event payload")
        return {"receipt": _validated_rewind(payload["receipt"]).to_dict()}
    if event_type in {"holdback-recorded", "holdback-cleared"}:
        payload = _closed_mapping(raw, fields={"item_id"}, context="holdback event payload")
        return {"item_id": _item_id(payload["item_id"])}
    raise LedgerError(f"unknown lifecycle event type: {event_type}")


def _event_sha256(without_sha: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_bytes(without_sha, "lifecycle event")).hexdigest()


def _validate_event(path: Path, raw: bytes, expected_seq: int, expected_prev: str) -> dict[str, object]:
    context = f"event {expected_seq} ({path.name})"
    document = _closed_mapping(
        _strict_json(raw, context),
        fields=EVENT_FIELDS,
        context=context,
    )
    if type(document["ledger_version"]) is not int or document["ledger_version"] != LEDGER_VERSION:
        raise LedgerError(f"event {expected_seq} has unsupported ledger version")
    if type(document["seq"]) is not int or document["seq"] != expected_seq:
        raise LedgerError(f"event {expected_seq} sequence does not match its filename")
    event_type = document["event_type"]
    if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
        raise LedgerError(f"event {expected_seq} has an unknown event type")
    expected_name = f"{expected_seq:08d}-{event_type}.json"
    if path.name != expected_name:
        raise LedgerError(f"event {expected_seq} type does not match its filename")
    previous = document["prev_event_sha256"]
    if not isinstance(previous, str) or HEX_SHA256.fullmatch(previous) is None:
        raise LedgerError(f"event {expected_seq} has an invalid previous-event hash")
    own_hash = document["event_sha256"]
    if not isinstance(own_hash, str) or HEX_SHA256.fullmatch(own_hash) is None:
        raise LedgerError(f"event {expected_seq} has an invalid integrity hash")
    without_sha = {key: value for key, value in document.items() if key != "event_sha256"}
    if own_hash != _event_sha256(without_sha):
        raise LedgerError(f"event {expected_seq} fails its integrity hash")
    if raw != _canonical_bytes(document, context):
        raise LedgerError(f"event {expected_seq} is valid JSON but not canonical")
    if previous != expected_prev:
        raise LedgerError(
            f"event {expected_seq} breaks the hash chain: expected {expected_prev}, found {previous}"
        )
    payload = _validated_payload(event_type, document["payload"])
    if payload != document["payload"]:
        raise LedgerError(f"event {expected_seq} payload is not canonical")
    return dict(document)


def _event_candidates(events_dir: Path) -> list[tuple[int, Path]]:
    if events_dir.is_symlink():
        raise LedgerError(f"ledger events path is unsafe: {events_dir}")
    if not events_dir.exists():
        return []
    _check_existing_directory(events_dir, "events")
    candidates: list[tuple[int, Path]] = []
    seen: dict[int, Path] = {}
    for path in events_dir.iterdir():
        match = EVENT_FILENAME.fullmatch(path.name)
        if match is None:
            raise LedgerError(f"events directory contains an unexpected entry: {path.name}")
        sequence = int(match.group("seq"))
        if sequence in seen:
            raise LedgerError(
                f"ledger fork at sequence {sequence}: {seen[sequence].name}, {path.name}"
            )
        if path.is_symlink() or not path.is_file():
            raise LedgerError(f"event {sequence} is missing or unsafe: {path}")
        seen[sequence] = path
        candidates.append((sequence, path))
    candidates.sort(key=lambda candidate: candidate[0])
    for expected, (sequence, _path) in enumerate(candidates, start=1):
        if sequence != expected:
            raise LedgerError(
                f"ledger sequence gap: expected {expected}, found {sequence}; history is missing"
            )
    return candidates


def _repair_command(vault_root: Path) -> str:
    return f"python3 -m core.lifecycle.cli --vault-root {Path(vault_root)} rebuild-state"


def _quarantine_torn_event(vault_root: Path, path: Path) -> Path:
    ledger_root, _events_dir, _state_path = _ensure_directories(vault_root)
    quarantine = ledger_root / "quarantine"
    _check_existing_directory(quarantine, "quarantine")
    quarantine.mkdir(exist_ok=True, mode=0o700)
    os.chmod(quarantine, 0o700)
    target = quarantine / f"{path.name}.torn"
    suffix = 1
    while target.exists():
        target = quarantine / f"{path.name}.torn-{suffix}"
        suffix += 1
    os.rename(path, target)
    _fsync_directory(path.parent)
    _fsync_directory(quarantine)
    return target


def _complete_commitment(vault_root: Path, sequence: int, digest: str) -> None:
    ledger_root, _events_dir, _state_path = _ensure_directories(vault_root)
    commitment_directory = ledger_root / "commitments"
    target = commitment_directory / f"{sequence:08d}.sha256"
    data = f"{digest}\n".encode("ascii")
    if target.exists():
        if target.is_symlink() or not target.is_file() or target.read_bytes() != data:
            raise LedgerError(
                f"existing lifecycle commitment sequence {sequence} disagrees with event"
            )
        return
    temporary = ledger_root / f".commitment.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or target.read_bytes() != data:
                raise LedgerError(
                    f"existing lifecycle commitment sequence {sequence} disagrees with event"
                )
        _fsync_directory(commitment_directory)
        temporary.unlink()
        _fsync_directory(ledger_root)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _commitments(vault_root: Path) -> list[tuple[int, str]]:
    ledger_root, _events_dir, _state_path = _ledger_paths(vault_root)
    directory = ledger_root / "commitments"
    if directory.is_symlink():
        raise LedgerError(f"ledger commitments path is unsafe: {directory}")
    if not directory.exists():
        return []
    _check_existing_directory(directory, "commitments")
    commitments: list[tuple[int, str]] = []
    for path in directory.iterdir():
        match = COMMITMENT_FILENAME.fullmatch(path.name)
        if match is None:
            raise LedgerError(f"commitments directory contains an unexpected entry: {path.name}")
        sequence = int(match.group("seq"))
        if path.is_symlink() or not path.is_file():
            raise LedgerError(f"commitment {sequence} is missing or unsafe: {path}")
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise LedgerError(f"commitment {sequence} could not be read: {error}") from error
        try:
            digest = raw.decode("ascii").removesuffix("\n")
        except UnicodeDecodeError as error:
            raise LedgerError(f"commitment {sequence} is unreadable") from error
        if raw != f"{digest}\n".encode("ascii") or HEX_SHA256.fullmatch(digest) is None:
            raise LedgerError(f"commitment {sequence} is not a canonical sha256 record")
        commitments.append((sequence, digest))
    commitments.sort(key=lambda entry: entry[0])
    for expected, (sequence, _digest) in enumerate(commitments, start=1):
        if sequence != expected:
            raise LedgerError(
                f"ledger commitment gap: expected {expected}, found {sequence}; history is missing"
            )
    return commitments


def _existing_state_floor(vault_root: Path) -> dict[str, object] | None:
    _ledger_root, _events_dir, state_path = _ledger_paths(vault_root)
    if not state_path.exists():
        return None
    if state_path.is_symlink() or not state_path.is_file():
        raise LedgerError(f"ledger state path is unsafe: {state_path}")
    try:
        raw = state_path.read_bytes()
        state = _validate_state_document(_strict_json(raw, "ledger state"))
        if raw != canonical_state_bytes(state):
            return None
        return state
    except LedgerError:
        return None
    except OSError as error:
        raise LedgerError(f"ledger state could not be read: {error}") from error


def _enforce_state_floor(vault_root: Path, events: list[dict[str, object]]) -> None:
    floor = _existing_state_floor(vault_root)
    if floor is None:
        return
    floor_seq = int(floor["last_seq"])
    if len(events) < floor_seq:
        raise LedgerError(
            f"possible ledger tail loss: verified history ends at sequence {len(events)}, but "
            f"valid state.json reached sequence {floor_seq}; backup/sync may have dropped the "
            "newest event and commitment files. Restore the missing files from backup/sync "
            f"before retrying {_repair_command(vault_root)!r}"
        )
    actual_hash = GENESIS_SHA256 if floor_seq == 0 else str(events[floor_seq - 1]["event_sha256"])
    if actual_hash != floor["last_event_sha256"]:
        raise LedgerError(
            f"possible ledger tail loss or history replacement at state.json sequence {floor_seq}: "
            "the verified event hash differs from the surviving high-water mark. Restore the "
            f"ledger from backup/sync before retrying {_repair_command(vault_root)!r}"
        )


def _load_events(
    vault_root: Path,
    *,
    repair_terminal_publication: bool,
    quarantine_unreadable: bool = False,
    repair_actions: list[str] | None = None,
) -> list[dict[str, object]]:
    _ledger_root, events_dir, _state_path = _ledger_paths(vault_root)
    candidates = _event_candidates(events_dir)
    commitments = _commitments(vault_root)
    if len(candidates) < len(commitments):
        raise LedgerError(
            f"ledger is missing event file for committed sequence {len(candidates) + 1}"
        )
    uncommitted: tuple[int, Path] | None = None
    if len(candidates) > len(commitments):
        uncommitted = candidates[len(commitments)]
        if len(candidates) != len(commitments) + 1:
            raise LedgerError(
                f"ledger has multiple uncommitted event files beginning at sequence "
                f"{uncommitted[0]}"
            )
        candidates = candidates[: len(commitments)]
    events: list[dict[str, object]] = []
    previous = GENESIS_SHA256
    for (sequence, path), (committed_sequence, committed_hash) in zip(
        candidates, commitments, strict=True
    ):
        if sequence != committed_sequence:
            raise LedgerError(
                f"event and commitment sequences disagree at {sequence} and {committed_sequence}"
            )
        try:
            event = _validate_event(path, path.read_bytes(), sequence, previous)
        except OSError as error:
            raise LedgerError(f"event {sequence} could not be read: {error}") from error
        if event["event_sha256"] != committed_hash:
            raise LedgerError(f"event {sequence} disagrees with its immutable commitment")
        events.append(event)
        previous = str(event["event_sha256"])
    if uncommitted is not None:
        sequence, path = uncommitted
        try:
            raw = path.read_bytes()
            event = _validate_event(path, raw, sequence, previous)
        except _UnreadableEvent as error:
            if not quarantine_unreadable:
                raise LedgerError(
                    f"event {sequence} publication is incomplete and its event file is unreadable "
                    f"or torn; run {_repair_command(vault_root)!r} to quarantine it and rebuild state"
                ) from error
            _enforce_state_floor(vault_root, events)
            _quarantine_torn_event(vault_root, path)
            if repair_actions is not None:
                repair_actions.append(f"quarantined unreadable torn event {sequence}")
        except OSError as error:
            raise LedgerError(f"event {sequence} could not be read: {error}") from error
        else:
            if not repair_terminal_publication:
                raise LedgerError(
                    f"event {sequence} publication is incomplete: the valid event has no "
                    f"commitment; run {_repair_command(vault_root)!r} to complete publication"
                )
            _enforce_state_floor(vault_root, [*events, event])
            _complete_commitment(vault_root, sequence, str(event["event_sha256"]))
            events.append(event)
            if repair_actions is not None:
                repair_actions.append(
                    f"completed publication commitment for valid event {sequence}"
                )
    _enforce_state_floor(vault_root, events)
    return events


def _empty_state() -> dict[str, object]:
    return {
        "ledger_version": LEDGER_VERSION,
        "install_id": None,
        "adopted": {},
        "held_back": [],
        "last_seq": 0,
        "last_event_sha256": GENESIS_SHA256,
    }


def _project(events: list[dict[str, object]]) -> dict[str, object]:
    state = _empty_state()
    adopted: dict[str, dict[str, str]] = {}
    held_back: set[str] = set()
    for event in events:
        event_type = str(event["event_type"])
        payload = event["payload"]
        assert isinstance(payload, dict)
        if event_type == "install-registered":
            if state["install_id"] is not None:
                raise LedgerError(f"event {event['seq']} attempts to re-register the install")
            state["install_id"] = payload["install_id"]
        elif event_type == "adoption-recorded":
            receipt = _validated_adoption(payload["receipt"])
            versions = _validated_versions(payload["item_versions"], receipt)
            for item_id in receipt.items_adopted:
                adopted[item_id] = {
                    "version": versions[item_id],
                    "tx_id": receipt.transaction_id,
                    "receipt_path": (
                        f"System/.dex/adoptions/{receipt.transaction_id}.receipt.json"
                    ),
                }
        elif event_type == "rewind-recorded":
            receipt = _validated_rewind(payload["receipt"])
            item_ids = {entry.item_id for entry in receipt.files_restored}
            for item_id in sorted(item_ids):
                current = adopted.get(item_id)
                if current is None:
                    continue
                if current["tx_id"] != receipt.adoption_transaction_id:
                    raise LedgerError(
                        f"event {event['seq']} rewinds item {item_id} without its matching current adoption"
                    )
                del adopted[item_id]
        elif event_type == "holdback-recorded":
            held_back.add(str(payload["item_id"]))
        elif event_type == "holdback-cleared":
            item_id = str(payload["item_id"])
            if item_id not in held_back:
                raise LedgerError(
                    f"event {event['seq']} clears item {item_id}, but it is not held back"
                )
            held_back.remove(item_id)
        state["last_seq"] = event["seq"]
        state["last_event_sha256"] = event["event_sha256"]
    state["adopted"] = {key: adopted[key] for key in sorted(adopted)}
    state["held_back"] = sorted(held_back)
    return state


def _validate_state_document(raw: object) -> dict[str, object]:
    state = _closed_mapping(raw, fields=STATE_FIELDS, context="ledger state")
    if type(state["ledger_version"]) is not int or state["ledger_version"] != LEDGER_VERSION:
        raise LedgerError("ledger state has unsupported version")
    install_id = state["install_id"]
    if install_id is not None:
        install_id = _uuid4(install_id)
    last_seq = state["last_seq"]
    if type(last_seq) is not int or last_seq < 0:
        raise LedgerError("ledger state last_seq must be a non-negative integer")
    last_hash = state["last_event_sha256"]
    if not isinstance(last_hash, str) or HEX_SHA256.fullmatch(last_hash) is None:
        raise LedgerError("ledger state last_event_sha256 is invalid")
    adopted_raw = state["adopted"]
    if not isinstance(adopted_raw, Mapping) or not all(isinstance(key, str) for key in adopted_raw):
        raise LedgerError("ledger state adopted must be an object")
    adopted: dict[str, dict[str, str]] = {}
    for item_id in sorted(adopted_raw):
        _item_id(item_id, "ledger state adopted item id")
        entry = _closed_mapping(
            adopted_raw[item_id],
            fields={"version", "tx_id", "receipt_path"},
            context=f"ledger state adopted item {item_id}",
        )
        version = _semver(entry["version"], f"ledger state adopted item {item_id} version")
        tx_id = entry["tx_id"]
        receipt_path = entry["receipt_path"]
        if not isinstance(tx_id, str) or not isinstance(receipt_path, str):
            raise LedgerError(f"ledger state adopted item {item_id} has invalid receipt fields")
        if receipt_path != f"System/.dex/adoptions/{tx_id}.receipt.json":
            raise LedgerError(f"ledger state adopted item {item_id} has a mismatched receipt path")
        adopted[item_id] = {"version": version, "tx_id": tx_id, "receipt_path": receipt_path}
    held_raw = state["held_back"]
    if not isinstance(held_raw, list):
        raise LedgerError("ledger state held_back must be an array")
    held = [_item_id(item_id, "ledger state held-back item id") for item_id in held_raw]
    if held != sorted(set(held)):
        raise LedgerError("ledger state held_back must be sorted and unique")
    if last_seq == 0 and last_hash != GENESIS_SHA256:
        raise LedgerError("empty ledger state must use the genesis hash")
    return {
        "ledger_version": LEDGER_VERSION,
        "install_id": install_id,
        "adopted": adopted,
        "held_back": held,
        "last_seq": last_seq,
        "last_event_sha256": last_hash,
    }


def canonical_state_bytes(state: object) -> bytes:
    """Canonical bytes for the rebuildable state cache."""
    return _canonical_bytes(_validate_state_document(state), "ledger state")


def _project_state_unlocked(vault_root: Path) -> dict[str, object]:
    return _project(_load_events(vault_root, repair_terminal_publication=False))


def project_state(vault_root: Path) -> dict[str, object]:
    """Verify and replay a shared-lock-consistent snapshot without writes."""
    with _read_lock(vault_root):
        return _project_state_unlocked(vault_root)


def _write_state(vault_root: Path, state: dict[str, object]) -> None:
    ledger_root, _events_dir, state_path = _ensure_directories(vault_root)
    data = canonical_state_bytes(state)
    temporary = ledger_root / f".state.json.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, state_path)
        os.chmod(state_path, 0o600)
        _fsync_directory(ledger_root)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _rebuild_state_unlocked(
    vault_root: Path, repair_actions: list[str] | None = None
) -> dict[str, object]:
    projected = _project(
        _load_events(
            vault_root,
            repair_terminal_publication=True,
            quarantine_unreadable=True,
            repair_actions=repair_actions,
        )
    )
    _write_state(vault_root, projected)
    return projected


def rebuild_state(vault_root: Path) -> dict[str, object]:
    """Serialize with writers, verify history, and regenerate the state cache."""
    with _write_lock(vault_root):
        return _rebuild_state_unlocked(vault_root)


def repair_state(vault_root: Path) -> tuple[dict[str, object], tuple[str, ...]]:
    """Repair an interrupted tail and rebuild state under the exclusive lock."""
    with _write_lock(vault_root):
        actions: list[str] = []
        state = _rebuild_state_unlocked(vault_root, actions)
        return state, tuple(actions)


def rebuild_state_cache(vault_root: Path) -> dict[str, object]:
    """Regenerate only state.json; never quarantine or otherwise alter events."""
    with _write_lock(vault_root):
        projected = _project_state_unlocked(vault_root)
        _write_state(vault_root, projected)
        return projected


def read_events(vault_root: Path, *, since: int = 1) -> list[dict[str, object]]:
    """Return verified immutable events at or after ``since`` without writes."""
    if type(since) is not int or since < 0:
        raise LedgerError("event --since sequence must be a non-negative integer")
    with _read_lock(vault_root):
        events = _load_events(vault_root, repair_terminal_publication=False)
        _project(events)
        return [event for event in events if int(event["seq"]) >= since]


def _open_lock(path: Path, *, create: bool) -> int:
    if path.is_symlink():
        raise LedgerError(f"ledger lock path is unsafe: {path}")
    flags = os.O_RDONLY
    if create:
        flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise LedgerError(f"ledger lock path is unsafe or unavailable: {path}: {error}") from error
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        os.close(descriptor)
        raise LedgerError(f"ledger lock path is unsafe: {path}")
    return descriptor


@contextmanager
def _read_lock(vault_root: Path) -> Iterator[None]:
    ledger_root, _events_dir, _state_path = _ledger_paths(vault_root)
    if ledger_root.is_symlink():
        raise LedgerError(f"ledger path is unsafe: {ledger_root}")
    if not ledger_root.exists():
        yield
        return
    _check_existing_directory(ledger_root, "ledger")
    lock_path = ledger_root / ".write.lock"
    if lock_path.is_symlink():
        raise LedgerError(f"ledger lock path is unsafe: {lock_path}")
    if not lock_path.exists():
        events_exist = (ledger_root / "events").exists()
        commitments_exist = (ledger_root / "commitments").exists()
        if events_exist or commitments_exist:
            raise LedgerError(f"ledger lock file is missing: {lock_path}")
        yield
        return
    descriptor = _open_lock(lock_path, create=False)
    try:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_SH)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def _write_lock(vault_root: Path) -> Iterator[None]:
    import fcntl

    ledger_root, _events_dir, _state_path = _ensure_directories(vault_root)
    lock_path = ledger_root / ".write.lock"
    descriptor = _open_lock(lock_path, create=True)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _publish_event(vault_root: Path, event_type: str, payload: dict[str, object]) -> None:
    ledger_root, events_dir, _state_path = _ensure_directories(vault_root)
    events = _load_events(vault_root, repair_terminal_publication=True)
    _project(events)
    last_sequence = int(events[-1]["seq"]) if events else 0
    if last_sequence >= MAX_SEQUENCE:
        raise LedgerError(
            f"lifecycle ledger sequence maximum {MAX_SEQUENCE:,} reached; refusing to append"
        )
    sequence = last_sequence + 1
    previous = str(events[-1]["event_sha256"]) if events else GENESIS_SHA256
    without_sha: dict[str, object] = {
        "ledger_version": LEDGER_VERSION,
        "seq": sequence,
        "event_type": event_type,
        "prev_event_sha256": previous,
        "payload": payload,
    }
    event = {**without_sha, "event_sha256": _event_sha256(without_sha)}
    data = _canonical_bytes(event, f"event {sequence}")
    target = events_dir / f"{sequence:08d}-{event_type}.json"
    temporary = ledger_root / f".event.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        try:
            os.link(temporary, target)
        except FileExistsError as error:
            raise LedgerError(
                f"refusing to rewrite existing lifecycle event sequence {sequence}: {target.name}"
            ) from error
        _fsync_directory(events_dir)
        temporary.unlink()
        _fsync_directory(ledger_root)
        commitment_directory = ledger_root / "commitments"
        commitment_target = commitment_directory / f"{sequence:08d}.sha256"
        commitment_temporary = (
            ledger_root / f".commitment.tmp-{os.getpid()}-{secrets.token_hex(8)}"
        )
        commitment_data = f"{event['event_sha256']}\n".encode("ascii")
        commitment_descriptor: int | None = None
        try:
            commitment_descriptor = os.open(
                commitment_temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            view = memoryview(commitment_data)
            while view:
                view = view[os.write(commitment_descriptor, view) :]
            os.fsync(commitment_descriptor)
            os.close(commitment_descriptor)
            commitment_descriptor = None
            try:
                os.link(commitment_temporary, commitment_target)
            except FileExistsError as error:
                raise LedgerError(
                    f"refusing to rewrite existing lifecycle commitment sequence {sequence}"
                ) from error
            _fsync_directory(commitment_directory)
            commitment_temporary.unlink()
            _fsync_directory(ledger_root)
        except BaseException:
            if commitment_descriptor is not None:
                os.close(commitment_descriptor)
            try:
                commitment_temporary.unlink()
            except FileNotFoundError:
                pass
            raise
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _record(vault_root: Path, event_type: str, payload: dict[str, object]) -> dict[str, object]:
    validated_payload = _validated_payload(event_type, payload)
    with _write_lock(vault_root):
        events = _load_events(vault_root, repair_terminal_publication=True)
        current = _project(events)
        if event_type != "install-registered" and current["install_id"] is None:
            _publish_event(
                vault_root,
                "install-registered",
                {"install_id": str(uuid4())},
            )
            events = _load_events(vault_root, repair_terminal_publication=True)
            current = _project(events)
        if event_type == "install-registered" and current["install_id"] is not None:
            raise LedgerError(f"install is already registered as {current['install_id']}")
        if event_type == "holdback-cleared" and validated_payload["item_id"] not in current["held_back"]:
            raise LedgerError(f"item {validated_payload['item_id']} is not currently held back")
        if event_type == "rewind-recorded":
            rewind = _validated_rewind(validated_payload["receipt"])
            item_ids = {entry.item_id for entry in rewind.files_restored}
            adopted = current["adopted"]
            assert isinstance(adopted, dict)
            if any(
                item_id in adopted
                and adopted[item_id]["tx_id"] != rewind.adoption_transaction_id
                for item_id in item_ids
            ):
                raise LedgerError("rewind receipt conflicts with a newer currently adopted item")
        transaction_id: str | None = None
        if event_type == "adoption-recorded":
            transaction_id = _validated_adoption(validated_payload["receipt"]).transaction_id
            id_field = "transaction_id"
        elif event_type == "rewind-recorded":
            transaction_id = _validated_rewind(validated_payload["receipt"]).rewind_transaction_id
            id_field = "rewind_transaction_id"
        if transaction_id is not None:
            for event in events:
                if event["event_type"] != event_type:
                    continue
                receipt = event["payload"]["receipt"]
                assert isinstance(receipt, dict)
                if receipt[id_field] != transaction_id:
                    continue
                if event["payload"] != validated_payload:
                    raise LedgerError(
                        f"lifecycle transaction id {transaction_id} is already recorded "
                        "with different evidence"
                    )
                _write_state(vault_root, current)
                return current
        _publish_event(vault_root, event_type, validated_payload)
        return _rebuild_state_unlocked(vault_root)


def register_install(vault_root: Path, install_id: UUID | str) -> dict[str, object]:
    return _record(vault_root, "install-registered", {"install_id": _uuid4(install_id)})


def record_adoption(
    vault_root: Path,
    receipt: AdoptionReceipt | object,
    item_versions: Mapping[str, str] | object,
) -> dict[str, object]:
    validated = _validated_adoption(receipt)
    versions = _validated_versions(item_versions, validated)
    return _record(
        vault_root,
        "adoption-recorded",
        {"receipt": validated.to_dict(), "item_versions": versions},
    )


def record_rewind(vault_root: Path, receipt: RewindReceipt | object) -> dict[str, object]:
    validated = _validated_rewind(receipt)
    return _record(vault_root, "rewind-recorded", {"receipt": validated.to_dict()})


def record_holdback(vault_root: Path, item_id: str) -> dict[str, object]:
    return _record(vault_root, "holdback-recorded", {"item_id": _item_id(item_id)})


def clear_holdback(vault_root: Path, item_id: str) -> dict[str, object]:
    return _record(vault_root, "holdback-cleared", {"item_id": _item_id(item_id)})


__all__ = [
    "EVENT_TYPES",
    "GENESIS_SHA256",
    "LEDGER_VERSION",
    "MAX_SEQUENCE",
    "LedgerError",
    "canonical_state_bytes",
    "clear_holdback",
    "project_state",
    "read_events",
    "rebuild_state",
    "rebuild_state_cache",
    "repair_state",
    "record_adoption",
    "record_holdback",
    "record_rewind",
    "register_install",
]
