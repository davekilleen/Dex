"""Byte-exact snapshots of a write-plan's targets, for exact undo.

Before a transaction mutates anything, every target path's current state is
captured under ``System/.dex/tx/<id>/snapshot/``: file bytes, mode bits, and
whether the path existed at all (so rollback knows to delete files the
transaction created). A manifest carries sha256 per entry; restore verifies
what it re-reads against the manifest, so a damaged snapshot fails closed
rather than "restoring" wrong bytes.

The tx directory is 0o700 and files 0o600 — and hard-denied paths can never
appear in a plan (the engine refuses them), so secrets never enter snapshots.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

MANIFEST_NAME = "manifest.json"


class SnapshotError(RuntimeError):
    """A snapshot could not be taken or restored safely."""


@dataclass(frozen=True)
class SnapshotEntry:
    relative: str
    existed: bool
    mode: int | None
    sha256: str | None
    size: int | None


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _store_name(index: int) -> str:
    return f"{index:06d}.bin"


class Snapshot:
    """One transaction's snapshot store."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # -- capture -----------------------------------------------------------

    def capture(self, vault_root: Path, relatives: list[str]) -> list[SnapshotEntry]:
        """Capture the current state of every relative path, fsynced.

        Refuses symlinked targets outright: a transaction plan must operate
        on regular files, and following links would snapshot (and later
        restore onto) the wrong object.
        """
        vault = Path(vault_root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        entries: list[SnapshotEntry] = []
        for index, relative in enumerate(relatives):
            target = vault / relative
            if target.is_symlink():
                raise SnapshotError(f"refusing to snapshot a symlink: {relative}")
            if target.is_dir():
                raise SnapshotError(
                    f"plans operate on files, not directories: {relative}"
                )
            if target.exists():
                store = self.root / _store_name(index)
                shutil.copyfile(target, store)
                os.chmod(store, 0o600)
                digest, size = _sha256(store)
                # The copy must byte-match the source AT CAPTURE TIME; if the
                # source is being mutated concurrently the lock was violated
                # and we must not proceed on a torn snapshot.
                source_digest, _ = _sha256(target)
                if digest != source_digest:
                    raise SnapshotError(
                        f"target changed while being snapshotted: {relative}"
                    )
                descriptor = os.open(store, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                entries.append(
                    SnapshotEntry(
                        relative,
                        True,
                        target.stat().st_mode & 0o7777,
                        digest,
                        size,
                    )
                )
            else:
                entries.append(SnapshotEntry(relative, False, None, None, None))
        self._write_manifest(entries)
        _fsync_directory(self.root)
        return entries

    def _write_manifest(self, entries: list[SnapshotEntry]) -> None:
        manifest = {
            "schema_version": 1,
            "entries": [entry.__dict__ for entry in entries],
        }
        path = self.root / MANIFEST_NAME
        data = json.dumps(manifest, indent=2).encode("utf-8")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    # -- read / restore ------------------------------------------------------

    def read_manifest(self) -> list[SnapshotEntry]:
        path = self.root / MANIFEST_NAME
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise SnapshotError("snapshot manifest is missing") from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise SnapshotError("snapshot manifest is unreadable") from error
        if payload.get("schema_version") != 1 or not isinstance(
            payload.get("entries"), list
        ):
            raise SnapshotError("snapshot manifest has an unsupported shape")
        entries = []
        for raw in payload["entries"]:
            entries.append(
                SnapshotEntry(
                    raw["relative"],
                    raw["existed"],
                    raw["mode"],
                    raw["sha256"],
                    raw["size"],
                )
            )
        return entries

    def restore(
        self, vault_root: Path, *, created_deletions: set[str] | None = None
    ) -> list[str]:
        """Byte-exact restore of every captured target; returns restored paths.

        Files absent at capture time are removed ONLY when the caller confirms
        the transaction actually wrote them (``created_deletions``): the vault
        is live, and a file the USER created in the window must never be
        deleted by someone else's rollback. ``None`` means "the caller applied
        everything" (legacy behavior). Every stored blob is verified against
        its manifest sha before it is copied back — a damaged snapshot store
        fails closed.
        """
        vault = Path(vault_root)
        entries = self.read_manifest()
        restored: list[str] = []
        for index, entry in enumerate(entries):
            target = vault / entry.relative
            if entry.existed:
                store = self.root / _store_name(index)
                digest, size = _sha256(store)
                if digest != entry.sha256 or size != entry.size:
                    raise SnapshotError(
                        f"snapshot store is damaged for {entry.relative}; "
                        "refusing to restore wrong bytes"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.parent / f".{target.name}.tx-restore"
                shutil.copyfile(store, temporary)
                if entry.mode is not None:
                    os.chmod(temporary, entry.mode)
                descriptor = os.open(temporary, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                os.replace(temporary, target)
                _fsync_directory(target.parent)
            else:
                transaction_wrote_it = (
                    created_deletions is None or entry.relative in created_deletions
                )
                if transaction_wrote_it and (target.is_symlink() or target.exists()):
                    target.unlink()
                    _fsync_directory(target.parent)
                    # Remove now-empty parent directories the apply created,
                    # stopping at the first non-empty (or the vault root).
                    parent = target.parent
                    while parent != vault and parent.is_dir():
                        try:
                            parent.rmdir()
                        except OSError:
                            break
                        parent = parent.parent
            restored.append(entry.relative)
        return restored
