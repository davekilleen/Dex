"""The transaction engine: plan → authorize → snapshot → apply → verify → commit.

One Transaction is the ONLY sanctioned way for an engine (updater, migrator,
repair) to mutate a vault. Its guarantees, each fault-injection tested:

1. Every plan entry is authorized by the ownership contract
   (``portable_contract.update_write_verdict``) BEFORE any write — one
   disallowed entry aborts the whole transaction (all-or-nothing gate).
2. Nothing is mutated before its snapshot is journaled and fsynced.
3. Applies are atomic per file (temp + rename in the target's directory).
4. ``rollback()`` restores byte-identical state, deleting files the
   transaction created.
5. One mutator per vault (the shared owner lock).
6. Every state transition is journaled BEFORE it takes effect; after a crash
   ``Transaction.resume`` completes or rolls back from the journal alone —
   never a half-state.

Test seams: setting ``DEX_TX_TEST_STOP_AFTER`` to one of
``after-begin | after-snapshot | mid-apply:<index> | after-apply |
after-verify | after-commit-record`` makes the engine ``os._exit(137)`` at
that exact point, so tests can assert recovery from every crash window.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from core import portable_contract
from core.transaction.journal import Journal, JournalCorruptError
from core.transaction.lock import acquire_owned_lock
from core.transaction.snapshot import Snapshot

TX_ROOT_RELATIVE = Path("System") / ".dex" / "tx"


class TransactionError(RuntimeError):
    """The transaction could not proceed safely."""


class PlanRejected(TransactionError):
    """At least one plan entry is not authorized by the ownership contract."""


@dataclass(frozen=True)
class PlanEntry:
    """One intended write: put ``content`` at vault-relative ``relative``."""

    relative: str
    content: bytes
    mode: int = 0o644

    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


def _stop_seam(seam: str) -> None:
    if os.environ.get("DEX_TX_TEST_STOP_AFTER") == seam:
        os._exit(137)


class Transaction:
    """A single crash-safe mutation of one vault."""

    def __init__(self, vault_root: Path, tx_id: str, *, _resumed: bool = False) -> None:
        self.vault_root = Path(vault_root).resolve()
        self.tx_id = tx_id
        self.tx_dir = self.vault_root / TX_ROOT_RELATIVE / tx_id
        self.journal = Journal(self.tx_dir / "journal.jsonl")
        self.snapshot = Snapshot(self.tx_dir / "snapshot")
        self._release = None
        self._plan: list[PlanEntry] | None = None
        self._resumed = _resumed

    # -- lifecycle -----------------------------------------------------------

    @classmethod
    def begin(cls, vault_root: Path, plan: list[PlanEntry]) -> "Transaction":
        """Authorize the whole plan, take the lock, journal BEGIN."""
        if not plan:
            raise TransactionError("a transaction needs at least one plan entry")

        # Target modes are bounded: no setuid/setgid/sticky, no bits beyond
        # permissions. A buggy or hostile plan must not mint a 4777 file.
        for entry in plan:
            if entry.mode & ~0o777:
                raise PlanRejected(
                    f"{entry.relative}: mode {oct(entry.mode)} carries special "
                    "bits; only permission bits up to 0o777 are allowed"
                )

        # All-or-nothing authorization BEFORE the lock: one disallowed entry
        # rejects the plan with nothing acquired and nothing written. For
        # write-if-absent entries this check is provisional — it is repeated
        # UNDER the lock at apply time, because the vault is a live directory
        # (the user, Obsidian, background sync) and a seed file appearing in
        # the window must win.
        rejections = []
        for entry in plan:
            target = Path(vault_root) / entry.relative
            verdict = portable_contract.update_write_verdict(
                entry.relative, exists=target.exists()
            )
            if not verdict.allowed:
                rejections.append(f"{entry.relative} [{verdict.action}]")
        if rejections:
            raise PlanRejected(
                "the ownership contract forbids writing: " + ", ".join(rejections)
            )

        tx = cls(vault_root, time.strftime("%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:8])
        tx._plan = list(plan)
        tx._release = acquire_owned_lock(tx.vault_root, f"transaction:{tx.tx_id}")
        try:
            tx.tx_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            tx.journal.append(
                "BEGIN",
                {
                    "tx_id": tx.tx_id,
                    "plan": [
                        {
                            "relative": entry.relative,
                            "sha256": entry.sha256(),
                            "mode": entry.mode,
                            "size": len(entry.content),
                        }
                        for entry in plan
                    ],
                },
            )
            # The intended content must survive a crash for resume to finish
            # the apply: stage it in the tx dir before anything mutates.
            staged = tx.tx_dir / "staged"
            staged.mkdir(mode=0o700, exist_ok=True)
            for index, entry in enumerate(plan):
                blob = staged / f"{index:06d}.bin"
                blob.write_bytes(entry.content)
                os.chmod(blob, 0o600)
            tx.journal.append("STAGED")
        except BaseException:
            tx._release()
            raise
        _stop_seam("after-begin")
        return tx

    def run(self) -> dict:
        """snapshot → apply → verify → commit. Rolls back on any failure."""
        try:
            self._snapshot_phase()
            _stop_seam("after-snapshot")
            self._apply_phase()
            _stop_seam("after-apply")
            self._verify_phase()
            _stop_seam("after-verify")
            return self._commit_phase()
        except BaseException:
            self.rollback()
            raise

    # -- phases ---------------------------------------------------------------

    def _snapshot_phase(self) -> None:
        assert self._plan is not None
        self.journal.append("SNAPSHOT-START")
        self.snapshot.capture(
            self.vault_root, [entry.relative for entry in self._plan]
        )
        self.journal.append("SNAPSHOT-DONE")

    def _apply_phase(self) -> None:
        assert self._plan is not None
        self.journal.append("APPLY-START")
        for index, entry in enumerate(self._plan):
            # F1 guard: the begin()-time authorization was provisional for
            # write-if-absent paths. The vault is live — if the user (or any
            # non-transaction writer) created this file since, THEIR file
            # wins and the whole transaction aborts (all-or-nothing), rolling
            # back anything already applied.
            verdict = portable_contract.update_write_verdict(
                entry.relative, exists=(self.vault_root / entry.relative).exists()
            )
            if not verdict.allowed:
                raise PlanRejected(
                    f"{entry.relative} appeared in the vault after authorization "
                    f"[{verdict.action}]; the existing file wins and the "
                    "transaction aborts"
                )
            self._apply_one(index, entry.relative, entry.mode)
            self.journal.append("APPLIED", {"index": index, "relative": entry.relative})
            _stop_seam(f"mid-apply:{index}")
        self.journal.append("APPLY-DONE")

    def _apply_one(self, index: int, relative: str, mode: int) -> None:
        staged = self.tx_dir / "staged" / f"{index:06d}.bin"
        target = self.vault_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}.tx-{self.tx_id}"
        shutil.copyfile(staged, temporary)
        os.chmod(temporary, mode)
        descriptor = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _verify_phase(self) -> None:
        assert self._plan is not None
        self.journal.append("VERIFY-START")
        for entry in self._plan:
            target = self.vault_root / entry.relative
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if digest != entry.sha256():
                raise TransactionError(
                    f"verification failed for {entry.relative}: applied bytes do "
                    "not match the plan"
                )
            actual_mode = target.stat().st_mode & 0o777
            if actual_mode != entry.mode:
                raise TransactionError(
                    f"verification failed for {entry.relative}: applied mode "
                    f"{oct(actual_mode)} does not match planned {oct(entry.mode)}"
                )
        self.journal.append("VERIFY-DONE")

    def _commit_phase(self) -> dict:
        self.journal.append("COMMITTED")
        _stop_seam("after-commit-record")
        self._prune_committed(keep=3)
        result = {
            "tx_id": self.tx_id,
            "committed": True,
            "targets": [entry.relative for entry in self._plan or []],
            "snapshot_dir": str(self.tx_dir / "snapshot"),
        }
        if self._release is not None:
            self._release()
            self._release = None
        return result

    def _prune_committed(self, *, keep: int) -> None:
        """Retention (owner decision, lean): keep the newest ``keep`` COMMITTED
        transactions' snapshots for undo; delete older COMMITTED ones. Only
        transactions that verifiably reached COMMITTED are ever pruned —
        anything unreadable or unfinished is left for resume()."""
        tx_root = self.vault_root / TX_ROOT_RELATIVE
        committed: list[Path] = []
        for candidate in sorted(tx_root.iterdir()):
            if not candidate.is_dir():
                continue
            try:
                events = {
                    entry.event
                    for entry in Journal(candidate / "journal.jsonl").read()
                }
            except JournalCorruptError:
                continue
            if "COMMITTED" in events:
                committed.append(candidate)
        for stale in committed[:-keep] if keep else committed:
            shutil.rmtree(stale, ignore_errors=True)

    # -- recovery / undo -------------------------------------------------------

    def _applied_relatives(self, entries) -> set[str]:
        return {
            entry.payload.get("relative")
            for entry in entries
            if entry.event == "APPLIED" and entry.payload.get("relative")
        }

    def rollback(self) -> dict:
        """Byte-exact restore from the snapshot; journaled; releases the lock.

        Robust against a corrupt journal: recovery proceeds best-effort from
        the snapshot manifest (assuming everything was applied — the safe
        over-approximation for restoring PRE-EXISTING files, and creations
        are then deleted only if present). The lock is always released.
        """
        try:
            entries = self.journal.read()
            events = {entry.event for entry in entries}
            applied = self._applied_relatives(entries)
            journal_ok = True
        except JournalCorruptError:
            events = set()
            applied = set()
            journal_ok = False
        restored: list[str] = []
        try:
            if journal_ok:
                if "SNAPSHOT-DONE" in events:
                    restored = self.snapshot.restore(
                        self.vault_root, created_deletions=applied
                    )
                # Before SNAPSHOT-DONE nothing was mutated: nothing to restore.
            else:
                # Journal unreadable: if a valid snapshot manifest exists,
                # restore pre-existing files from it (never wrong — it holds
                # their exact prior bytes). Files absent at capture are left
                # alone: with no journal we cannot know who created them, and
                # deleting a user's file is the one unforgivable outcome.
                try:
                    restored = self.snapshot.restore(
                        self.vault_root, created_deletions=set()
                    )
                except Exception:
                    restored = []
            if journal_ok:
                self.journal.append("ROLLED-BACK", {"restored": restored})
        finally:
            if self._release is not None:
                self._release()
                self._release = None
        return {
            "tx_id": self.tx_id,
            "committed": False,
            "restored": restored,
            "journal_ok": journal_ok,
        }

    @classmethod
    def resume(cls, vault_root: Path) -> list[dict]:
        """Recover every unfinished transaction under the vault's tx root.

        Reads each journal and converges: a transaction that reached
        SNAPSHOT-DONE but not COMMITTED is rolled back (byte-identical);
        one that recorded COMMITTED merely has its lock/lifecycle finished.
        Never leaves a half-state.
        """
        root = Path(vault_root).resolve()
        outcomes: list[dict] = []
        tx_root = root / TX_ROOT_RELATIVE
        if not tx_root.is_dir():
            return outcomes
        for tx_dir in sorted(tx_root.iterdir()):
            if not tx_dir.is_dir():
                continue
            tx = cls(root, tx_dir.name, _resumed=True)
            # One damaged transaction must never strand the recovery of the
            # others: each is handled independently and a corrupt journal is
            # quarantined (best-effort restore inside rollback), not fatal.
            try:
                try:
                    events = {entry.event for entry in tx.journal.read()}
                except JournalCorruptError:
                    events = None  # unreadable — rollback handles best-effort
                if events is not None:
                    if not events or "ROLLED-BACK" in events:
                        continue  # empty shell or already recovered
                    if "COMMITTED" in events:
                        # Fully applied and verified; a crash after the commit
                        # record only lost the lock release, which the lock's
                        # own liveness machinery recovers. Nothing to converge.
                        continue
                lock_release = acquire_owned_lock(root, f"resume:{tx_dir.name}")
                try:
                    tx._release = None  # rollback() must not double-release
                    outcome = tx.rollback()
                    outcome["resumed"] = True
                    outcomes.append(outcome)
                finally:
                    lock_release()
            except Exception as error:  # noqa: BLE001 — quarantine, keep sweeping
                outcomes.append(
                    {
                        "tx_id": tx_dir.name,
                        "committed": False,
                        "resumed": True,
                        "quarantined": str(error),
                    }
                )
        return outcomes
