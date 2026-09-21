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
after-verify | before-finalize | after-commit-record`` makes the engine
``os._exit(137)`` at that exact point, so tests can assert recovery from every
crash window.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from core import portable_contract
from core.lifecycle.filesystem import bounded_read
from core.path_safety import unsafe_existing_parent
from core.transaction.fsync import fsync_directory
from core.transaction.journal import Journal, JournalCorruptError, JournalSchemaError
from core.transaction.lock import acquire_owned_lock
from core.transaction.snapshot import Snapshot

TX_ROOT_RELATIVE = Path("System") / ".dex" / "tx"


# Operations that only append their own small receipt. They are committed and
# byte-verified like any other transaction, but there is nothing in them a user
# would ask to undo, so they must not consume the retention budget that adoption
# and release snapshots depend on. See ``Transaction._prune_committed``.
BOOKKEEPING_OPERATIONS = frozenset({"analytics-receipt", "automation-ownership"})


class TransactionError(RuntimeError):
    """The transaction could not proceed safely."""


class PlanRejected(TransactionError):
    """At least one plan entry is not authorized by the ownership contract."""


@dataclass(frozen=True)
class PlanEntry:
    """One intended mutation at vault-relative ``relative``.

    ``content=None`` is an authorized deletion. ``expected_current_sha256``
    guards deletions (required) and content writes (optional) against a target
    changing after the plan was built. ``expected_absent`` guards a new-file
    write against a target appearing before apply. Deletions use the same
    snapshot/apply/verify/rollback lifecycle as replacements, so an updater
    can prune a retired brain file without opening a second mutation path.
    """

    relative: str
    content: bytes | None
    mode: int = 0o644
    expected_current_sha256: str | None = None
    expected_absent: bool = False

    def sha256(self) -> str | None:
        return hashlib.sha256(self.content).hexdigest() if self.content is not None else None

    @property
    def operation(self) -> str:
        return "delete" if self.content is None else "write"


def _stop_seam(seam: str) -> None:
    if os.environ.get("DEX_TX_TEST_STOP_AFTER") == seam:
        os._exit(137)


def _unsafe_infrastructure_directory(vault_root: Path, directory: Path) -> str | None:
    try:
        relative = directory.relative_to(vault_root)
    except ValueError:
        return f"path resolves outside the vault: {directory}"
    unsafe_parent = unsafe_existing_parent(
        vault_root,
        (relative / ".path-safety-check").as_posix(),
    )
    if unsafe_parent is None:
        return None
    return f"{relative.as_posix()}: {unsafe_parent}"


class Transaction:
    """A single crash-safe mutation of one vault."""

    def __init__(
        self,
        vault_root: Path,
        tx_id: str,
        *,
        operation: str = "update",
        max_read_bytes_by_relative: Mapping[str, int] | None = None,
        _resumed: bool = False,
    ) -> None:
        self.vault_root = Path(vault_root).resolve()
        self.tx_id = tx_id
        self.operation = operation
        self._max_read_bytes_by_relative = dict(max_read_bytes_by_relative or {})
        self.tx_dir = self.vault_root / TX_ROOT_RELATIVE / tx_id
        self.journal = Journal(self.tx_dir / "journal.jsonl")
        self.snapshot = Snapshot(self.tx_dir / "snapshot")
        self._release = None
        self._plan: list[PlanEntry] | None = None
        self._resumed = _resumed

    # -- lifecycle -----------------------------------------------------------

    @classmethod
    def begin(
        cls,
        vault_root: Path,
        plan: list[PlanEntry],
        *,
        allow_empty: bool = False,
        operation: str = "update",
        max_read_bytes_by_relative: Mapping[str, int] | None = None,
    ) -> "Transaction":
        """Authorize the whole plan, take the lock, journal BEGIN."""
        return cls._begin_with_id(
            vault_root,
            plan,
            allow_empty=allow_empty,
            operation=operation,
            max_read_bytes_by_relative=max_read_bytes_by_relative,
            tx_id=None,
        )

    @classmethod
    def _begin_with_id(
        cls,
        vault_root: Path,
        plan: list[PlanEntry],
        *,
        allow_empty: bool,
        operation: str,
        tx_id: str | None,
        max_read_bytes_by_relative: Mapping[str, int] | None = None,
    ) -> "Transaction":
        """Internal begin seam for plans that must persist their tx id."""
        if not plan and not allow_empty:
            raise TransactionError("a transaction needs at least one plan entry")

        read_limits = dict(max_read_bytes_by_relative or {})
        plan_paths = {entry.relative for entry in plan}
        if any(
            relative not in plan_paths
            or type(max_bytes) is not int
            or max_bytes < 0
            for relative, max_bytes in read_limits.items()
        ):
            raise PlanRejected("transaction bounded-read limits are invalid")
        required_limit = None
        if operation == "analytics-receipt":
            required_limit = {
                portable_contract.ANALYTICS_ATTEMPT_RECEIPT_RELATIVE: (
                    portable_contract.ANALYTICS_ATTEMPT_RECEIPT_TRANSACTION_MAX_BYTES
                )
            }
        elif operation == "automation-ownership":
            required_limit = {
                portable_contract.AUTOMATION_OWNERSHIP_RELATIVE: (
                    portable_contract.AUTOMATION_OWNERSHIP_TRANSACTION_MAX_BYTES
                )
            }
        if required_limit is not None and read_limits != required_limit:
            operation_name = operation.replace("-", " ")
            raise PlanRejected(
                f"{operation_name} transaction lacks the required bounded-read limit"
            )

        # Target modes are bounded: no setuid/setgid/sticky, no bits beyond
        # permissions. A buggy or hostile plan must not mint a 4777 file.
        for entry in plan:
            if entry.mode & ~0o777:
                raise PlanRejected(
                    f"{entry.relative}: mode {oct(entry.mode)} carries special "
                    "bits; only permission bits up to 0o777 are allowed"
                )
            if entry.expected_current_sha256 is not None and not re.fullmatch(
                r"[0-9a-f]{64}", entry.expected_current_sha256
            ):
                raise PlanRejected(
                    f"{entry.relative}: current-content preconditions must be a lowercase sha256"
                )
            if entry.content is None and entry.expected_current_sha256 is None:
                raise PlanRejected(f"{entry.relative}: deletions require expected_current_sha256")
            if type(entry.expected_absent) is not bool:
                raise PlanRejected(
                    f"{entry.relative}: expected_absent must be boolean"
                )
            if entry.expected_absent and entry.content is None:
                raise PlanRejected(
                    f"{entry.relative}: expected_absent is only valid on content writes"
                )
            if entry.expected_absent and entry.expected_current_sha256 is not None:
                raise PlanRejected(
                    f"{entry.relative}: an expected-absent create cannot also assert current bytes"
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
            unsafe_parent = unsafe_existing_parent(Path(vault_root), entry.relative)
            if unsafe_parent is not None:
                rejections.append(f"{entry.relative} [{unsafe_parent}]")
                continue
            verdict = portable_contract.update_write_verdict(
                entry.relative,
                exists=target.exists(),
                operation=operation,
            )
            if not verdict.allowed:
                rejections.append(f"{entry.relative} [{verdict.action}]")
        if rejections:
            raise PlanRejected("the ownership contract forbids writing: " + ", ".join(rejections))

        tx = cls(
            vault_root,
            tx_id or time.strftime("%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:8],
            operation=operation,
            max_read_bytes_by_relative=read_limits,
        )
        tx._plan = list(plan)
        unsafe_directory = _unsafe_infrastructure_directory(tx.vault_root, tx.tx_dir)
        if unsafe_directory is not None:
            raise TransactionError(
                f"refusing unsafe transaction directory {unsafe_directory}"
            )
        tx._release = acquire_owned_lock(tx.vault_root, f"transaction:{tx.tx_id}")
        try:
            unsafe_directory = _unsafe_infrastructure_directory(tx.vault_root, tx.tx_dir)
            if unsafe_directory is not None:
                raise TransactionError(
                    f"refusing unsafe transaction directory {unsafe_directory}"
                )
            tx.tx_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            tx.journal.append(
                "BEGIN",
                {
                    "tx_id": tx.tx_id,
                    "operation": operation,
                    # Recovery may need to distinguish a transaction-owned
                    # expected-absent target from a user-created one. Persist
                    # service-owned caps so that comparison cannot reopen an
                    # unbounded read after a crash.
                    "max_read_bytes_by_relative": read_limits,
                    "plan": [
                        {
                            "relative": entry.relative,
                            "operation": entry.operation,
                            "sha256": entry.sha256(),
                            "mode": entry.mode,
                            "size": len(entry.content) if entry.content is not None else None,
                            "expected_current_sha256": entry.expected_current_sha256,
                            "expected_absent": entry.expected_absent,
                        }
                        for entry in plan
                    ],
                },
            )
            # The intended content must survive a crash for resume to finish
            # the apply: stage it in the tx dir before anything mutates.
            staged = tx.tx_dir / "staged"
            unsafe_directory = _unsafe_infrastructure_directory(tx.vault_root, staged)
            if unsafe_directory is not None:
                raise TransactionError(
                    f"refusing unsafe staging directory {unsafe_directory}"
                )
            staged.mkdir(mode=0o700, exist_ok=True)
            for index, entry in enumerate(plan):
                if entry.content is None:
                    continue
                blob = staged / f"{index:06d}.bin"
                blob.write_bytes(entry.content)
                os.chmod(blob, 0o600)
            tx.journal.append("STAGED")
        except BaseException:
            tx._release()
            raise
        _stop_seam("after-begin")
        return tx

    def run(self, *, before_commit: Callable[[], None] | None = None) -> dict:
        """snapshot → apply → verify → finalize → commit.

        ``before_commit`` runs while the mutation lock is still held and before
        COMMITTED is journaled. Any failure therefore uses the normal locked
        rollback path instead of compensating after transaction success.
        """
        try:
            self._snapshot_phase()
            _stop_seam("after-snapshot")
            self._apply_phase()
            _stop_seam("after-apply")
            self._verify_phase()
            _stop_seam("after-verify")
            if before_commit is not None:
                _stop_seam("before-finalize")
                before_commit()
            return self._commit_phase()
        except BaseException:
            self.rollback()
            raise

    # -- phases ---------------------------------------------------------------

    def _snapshot_phase(self) -> None:
        assert self._plan is not None
        self.journal.append("SNAPSHOT-START")
        for entry in self._plan:
            unsafe_parent = unsafe_existing_parent(self.vault_root, entry.relative)
            if unsafe_parent is not None:
                raise PlanRejected(f"{entry.relative}: {unsafe_parent}")
            if entry.expected_absent:
                target = self.vault_root / entry.relative
                if target.exists() or target.is_symlink():
                    raise PlanRejected(
                        f"{entry.relative} appeared after the mutation plan was built; "
                        "the existing file wins and the transaction aborts"
                    )
            if entry.expected_current_sha256 is None:
                continue
            if entry.content is None:
                self._verify_deletion_precondition(
                    entry,
                    changed_when="after the mutation plan was built",
                )
            else:
                self._verify_content_precondition(
                    entry,
                    changed_when="after the mutation plan was built",
                )
        self.snapshot.capture(
            self.vault_root,
            [entry.relative for entry in self._plan],
            max_read_bytes_by_relative=self._max_read_bytes_by_relative,
        )
        self.journal.append("SNAPSHOT-DONE")

    def _apply_phase(self) -> None:
        assert self._plan is not None
        self.journal.append("APPLY-START")
        for index, entry in enumerate(self._plan):
            unsafe_parent = unsafe_existing_parent(self.vault_root, entry.relative)
            if unsafe_parent is not None:
                raise PlanRejected(f"{entry.relative}: {unsafe_parent}")
            # F1 guard: the begin()-time authorization was provisional for
            # write-if-absent paths. The vault is live — if the user (or any
            # non-transaction writer) created this file since, THEIR file
            # wins and the whole transaction aborts (all-or-nothing), rolling
            # back anything already applied.
            verdict = portable_contract.update_write_verdict(
                entry.relative,
                exists=(self.vault_root / entry.relative).exists(),
                operation=self.operation,
            )
            if not verdict.allowed:
                raise PlanRejected(
                    f"{entry.relative} appeared in the vault after authorization "
                    f"[{verdict.action}]; the existing file wins and the "
                    "transaction aborts"
                )
            if entry.content is None:
                self._verify_deletion_precondition(
                    entry,
                    changed_when="after the mutation snapshot",
                )
            self.journal.append(
                "APPLYING",
                {
                    "index": index,
                    "relative": entry.relative,
                    "expected_absent": entry.expected_absent,
                },
            )
            try:
                self._apply_one(index, entry)
            except PlanRejected:
                self.journal.append(
                    "NOT-APPLIED",
                    {"index": index, "relative": entry.relative},
                )
                raise
            self.journal.append("APPLIED", {"index": index, "relative": entry.relative})
            _stop_seam(f"mid-apply:{index}")
        self.journal.append("APPLY-DONE")

    def _verify_deletion_precondition(
        self,
        entry: PlanEntry,
        *,
        changed_when: str,
    ) -> None:
        target = self.vault_root / entry.relative
        if not target.exists():
            return
        if not self._matches_current_precondition(entry, check_mode=True):
            raise PlanRejected(
                f"{entry.relative} changed {changed_when}; the existing file wins and the transaction aborts"
            )

    def _verify_content_precondition(
        self,
        entry: PlanEntry,
        *,
        changed_when: str,
    ) -> None:
        target = self.vault_root / entry.relative
        if not target.exists() or not self._matches_current_precondition(
            entry,
            check_mode=False,
        ):
            raise PlanRejected(
                f"{entry.relative} changed {changed_when}; "
                "the existing file wins and the transaction aborts"
            )

    def _matches_current_precondition(
        self,
        entry: PlanEntry,
        *,
        check_mode: bool,
    ) -> bool:
        target = self.vault_root / entry.relative
        return (
            not target.is_symlink()
            and target.is_file()
            and hashlib.sha256(self._read_entry_bytes(entry)).hexdigest()
            == entry.expected_current_sha256
            and (not check_mode or target.stat().st_mode & 0o777 == entry.mode)
        )

    def _read_entry_bytes(self, entry: PlanEntry) -> bytes:
        """Read a planned file, honoring a service-owned cap when supplied."""
        max_bytes = self._max_read_bytes_by_relative.get(entry.relative)
        if max_bytes is not None:
            return bounded_read(self.vault_root, entry.relative, max_bytes=max_bytes)
        return (self.vault_root / entry.relative).read_bytes()

    def _apply_one(self, index: int, entry: PlanEntry) -> None:
        relative = entry.relative
        target = self.vault_root / relative
        if entry.content is None:
            if target.is_symlink() or target.is_dir():
                raise TransactionError(f"refusing to delete a non-file target: {relative}")
            self._verify_deletion_precondition(
                entry,
                changed_when="after the mutation snapshot",
            )
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            else:
                fsync_directory(target.parent)
            return

        staged = self.tx_dir / "staged" / f"{index:06d}.bin"
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}.tx-{self.tx_id}"
        shutil.copyfile(staged, temporary)
        os.chmod(temporary, entry.mode)
        descriptor = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if entry.expected_current_sha256 is not None:
            try:
                self._verify_content_precondition(
                    entry,
                    changed_when="after the mutation snapshot",
                )
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        if entry.expected_absent and (target.exists() or target.is_symlink()):
            temporary.unlink(missing_ok=True)
            raise PlanRejected(
                f"{entry.relative} appeared after the mutation snapshot; "
                "the existing file wins and the transaction aborts"
            )
        if entry.expected_absent:
            try:
                os.link(temporary, target, follow_symlinks=False)
            except FileExistsError as error:
                temporary.unlink(missing_ok=True)
                raise PlanRejected(
                    f"{entry.relative} appeared after the mutation snapshot; "
                    "the existing file wins and the transaction aborts"
                ) from error
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
            fsync_directory(target.parent)
            # Keep the hard-link source until publication is journalled. If
            # this append tears, rollback can distinguish our inode from a
            # user file that won the same window.
            self.journal.append(
                "PUBLISHED",
                {"index": index, "relative": entry.relative},
            )
            temporary.unlink()
            fsync_directory(target.parent)
            return
        os.replace(temporary, target)
        fsync_directory(target.parent)

    def _verify_phase(self) -> None:
        assert self._plan is not None
        self.journal.append("VERIFY-START")
        for entry in self._plan:
            target = self.vault_root / entry.relative
            if entry.content is None:
                if target.is_symlink() or target.exists():
                    raise TransactionError(f"verification failed for {entry.relative}: deleted target still exists")
                continue
            digest = hashlib.sha256(self._read_entry_bytes(entry)).hexdigest()
            if digest != entry.sha256():
                raise TransactionError(f"verification failed for {entry.relative}: applied bytes do not match the plan")
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
        anything unreadable or unfinished is left for resume().

        ``keep`` is applied per class. Bookkeeping operations append a receipt
        line and have nothing a user would ever ask to rewind, but they are
        frequent: ``analytics-receipt`` alone fires on every session start. When
        they shared one budget with the operations that matter, three ordinary
        session opens were enough to evict an adoption snapshot, and
        ``rewind_adoption`` would then refuse with "no longer available under
        keep-last-3 retention" through no action of the user's. Counting the two
        classes separately keeps the documented promise -- rewind available
        while the snapshot is among the newest three -- true against the
        operations that promise is about.
        """
        tx_root = self.vault_root / TX_ROOT_RELATIVE
        rewindable: list[Path] = []
        bookkeeping: list[Path] = []
        for candidate in sorted(tx_root.iterdir()):
            if not candidate.is_dir():
                continue
            try:
                entries = Journal(candidate / "journal.jsonl").read()
            except JournalCorruptError:
                continue
            if not any(entry.event == "COMMITTED" for entry in entries):
                continue
            operation = None
            for entry in entries:
                if entry.event == "BEGIN":
                    operation = entry.payload.get("operation")
                    break
            bucket = bookkeeping if operation in BOOKKEEPING_OPERATIONS else rewindable
            bucket.append(candidate)
        for group in (rewindable, bookkeeping):
            for stale in group[:-keep] if keep else group:
                shutil.rmtree(stale, ignore_errors=True)

    # -- recovery / undo -------------------------------------------------------

    @staticmethod
    def _target_matches_planned_content(
        target: Path,
        *,
        planned_sha256: str,
        planned_size: int,
        max_bytes: int | None = None,
    ) -> bool:
        if max_bytes is not None and planned_size > max_bytes:
            return False
        try:
            nofollow = os.O_NOFOLLOW
        except AttributeError:
            return False
        try:
            descriptor = os.open(
                target,
                os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0),
            )
        except OSError:
            return False
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size != planned_size
            ):
                return False
            digest = hashlib.sha256()
            remaining = planned_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 64 * 1024))
                if not chunk:
                    return False
                digest.update(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                return False
            return digest.hexdigest() == planned_sha256
        except OSError:
            return False
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass

    def _applied_relatives(self, entries) -> set[str]:
        applied: set[str] = set()
        expected_absent: set[str] = set()
        ambiguous_expected_absent: set[str] = set()
        planned_content: dict[str, tuple[str, int]] = {}
        for entry in entries:
            if entry.event != "BEGIN":
                continue
            plan = entry.payload.get("plan")
            if isinstance(plan, list):
                for planned in plan:
                    if (
                        not isinstance(planned, dict)
                        or planned.get("expected_absent") is not True
                    ):
                        continue
                    relative = planned.get("relative")
                    planned_sha256 = planned.get("sha256")
                    planned_size = planned.get("size")
                    if (
                        isinstance(relative, str)
                        and isinstance(planned_sha256, str)
                        and re.fullmatch(r"[0-9a-f]{64}", planned_sha256)
                        and type(planned_size) is int
                        and planned_size >= 0
                    ):
                        planned_content[relative] = (
                            planned_sha256,
                            planned_size,
                        )
            break
        for entry in entries:
            relative = entry.payload.get("relative")
            if not relative:
                continue
            if entry.event == "APPLYING":
                if entry.payload.get("expected_absent") is True:
                    expected_absent.add(relative)
                    ambiguous_expected_absent.add(relative)
                else:
                    applied.add(relative)
            elif entry.event in {"PUBLISHED", "APPLIED"}:
                applied.add(relative)
                ambiguous_expected_absent.discard(relative)
            elif entry.event == "NOT-APPLIED":
                applied.discard(relative)
                ambiguous_expected_absent.discard(relative)
        for relative in expected_absent:
            if unsafe_existing_parent(self.vault_root, relative) is not None:
                continue
            target = self.vault_root / relative
            temporary = target.parent / f".{target.name}.tx-{self.tx_id}"
            try:
                temporary_metadata = temporary.lstat()
            except OSError:
                temporary_metadata = None
            try:
                target_metadata = target.lstat()
            except OSError:
                target_metadata = None
            if (
                relative in ambiguous_expected_absent
                and target_metadata is not None
            ):
                planned = planned_content.get(relative)
                target_is_ours = (
                    temporary_metadata is not None
                    and stat.S_ISREG(temporary_metadata.st_mode)
                    and stat.S_ISREG(target_metadata.st_mode)
                    and (target_metadata.st_dev, target_metadata.st_ino)
                    == (temporary_metadata.st_dev, temporary_metadata.st_ino)
                ) or (
                    temporary_metadata is None
                    and planned is not None
                    and self._target_matches_planned_content(
                        target,
                        planned_sha256=planned[0],
                        planned_size=planned[1],
                        max_bytes=self._max_read_bytes_by_relative.get(relative),
                    )
                )
                if target_is_ours:
                    applied.add(relative)
                else:
                    applied.discard(relative)
            if (
                temporary_metadata is not None
                and stat.S_ISREG(temporary_metadata.st_mode)
            ):
                temporary.unlink(missing_ok=True)
        return applied

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
                        self.vault_root,
                        created_deletions=applied,
                        restore_relatives=applied,
                    )
                # Before SNAPSHOT-DONE nothing was mutated: nothing to restore.
            else:
                # Journal unreadable: if a valid snapshot manifest exists,
                # restore pre-existing files from it (never wrong — it holds
                # their exact prior bytes). Files absent at capture are left
                # alone: with no journal we cannot know who created them, and
                # deleting a user's file is the one unforgivable outcome.
                try:
                    restored = self.snapshot.restore(self.vault_root, created_deletions=set())
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

    @staticmethod
    def _read_limits_from_begin_payload(payload: dict) -> dict[str, int]:
        """Restore only valid service-owned bounded-read limits from BEGIN."""
        raw_limits = payload.get("max_read_bytes_by_relative", {})
        if not isinstance(raw_limits, dict):
            raise TransactionError("transaction bounded-read limits are invalid")
        plan = payload.get("plan", [])
        plan_paths = {
            planned.get("relative")
            for planned in plan
            if isinstance(planned, dict) and isinstance(planned.get("relative"), str)
        } if isinstance(plan, list) else set()
        if any(
            not isinstance(relative, str)
            or relative not in plan_paths
            or type(max_bytes) is not int
            or max_bytes < 0
            for relative, max_bytes in raw_limits.items()
        ):
            raise TransactionError("transaction bounded-read limits are invalid")
        read_limits = dict(raw_limits)
        operation = payload.get("operation", "update")
        required_limit = None
        if operation == "analytics-receipt":
            required_limit = {
                portable_contract.ANALYTICS_ATTEMPT_RECEIPT_RELATIVE: (
                    portable_contract.ANALYTICS_ATTEMPT_RECEIPT_TRANSACTION_MAX_BYTES
                )
            }
        elif operation == "automation-ownership":
            required_limit = {
                portable_contract.AUTOMATION_OWNERSHIP_RELATIVE: (
                    portable_contract.AUTOMATION_OWNERSHIP_TRANSACTION_MAX_BYTES
                )
            }
        if required_limit is not None and read_limits != required_limit:
            operation_name = operation.replace("-", " ")
            raise TransactionError(
                f"{operation_name} transaction lacks the required bounded-read limit"
            )
        return read_limits

    @classmethod
    def resume(
        cls,
        vault_root: Path,
        *,
        transaction_ids: Iterable[str] | None = None,
    ) -> list[dict]:
        """Recover every unfinished transaction under the vault's tx root.

        Reads each journal and converges: a transaction that reached
        SNAPSHOT-DONE but not COMMITTED is rolled back (byte-identical);
        one that recorded COMMITTED merely has its lock/lifecycle finished.
        Never leaves a half-state.
        """
        root = Path(vault_root).resolve()
        selected = None
        if transaction_ids is not None:
            selected = frozenset(transaction_ids)
            if any(
                not isinstance(tx_id, str)
                or not tx_id
                or "/" in tx_id
                or "\x00" in tx_id
                for tx_id in selected
            ):
                raise TransactionError("recovery transaction id is invalid")
        outcomes: list[dict] = []
        tx_root = root / TX_ROOT_RELATIVE
        unsafe_directory = _unsafe_infrastructure_directory(root, tx_root)
        if unsafe_directory is not None:
            raise TransactionError(
                f"refusing unsafe transaction root {unsafe_directory}"
            )
        if not tx_root.is_dir():
            return outcomes
        for tx_dir in sorted(tx_root.iterdir()):
            if not tx_dir.is_dir():
                continue
            if selected is not None and tx_dir.name not in selected:
                continue
            tx = cls(root, tx_dir.name, _resumed=True)
            # One damaged transaction must never strand the recovery of the
            # others: each is handled independently and a corrupt journal is
            # quarantined (best-effort restore inside rollback), not fatal.
            try:
                rollback_only = False
                try:
                    journal_entries = tx.journal.read()
                    events = {entry.event for entry in journal_entries}
                    begin = next(
                        (entry for entry in journal_entries if entry.event == "BEGIN"),
                        None,
                    )
                    if begin is not None:
                        tx.operation = begin.payload.get("operation", "update")
                        tx._max_read_bytes_by_relative = (
                            tx._read_limits_from_begin_payload(begin.payload)
                        )
                except JournalSchemaError:
                    events = None
                    rollback_only = True
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
                    if rollback_only:
                        outcome["rollback_only"] = True
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
