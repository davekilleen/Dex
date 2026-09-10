"""The transaction core's contract, held under test.

Covers the four modules (lock, journal, snapshot, engine) plus the
fault-injection matrix: the engine is killed at every seam via
``DEX_TX_TEST_STOP_AFTER`` in a subprocess, then ``Transaction.resume`` runs
in this process and the tree must be byte-identical (pre-commit crash) or
fully applied (post-commit crash) — never mixed. The contract-authorization
gate carries a red-when-removed proof.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from core import portable_contract
from core.transaction.engine import PlanEntry, PlanRejected, Transaction, TransactionError
from core.transaction.journal import Journal, JournalCorruptError
from core.transaction.lock import LockBusyError, acquire_owned_lock
from core.transaction.snapshot import Snapshot, SnapshotError

REPO_ROOT = Path(__file__).resolve().parents[2]


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "System" / ".dex").mkdir(parents=True)
    return vault


def _tree_state(vault: Path, relatives: list[str]) -> dict:
    state = {}
    for relative in relatives:
        path = vault / relative
        state[relative] = (path.read_bytes(), path.stat().st_mode & 0o7777) if path.exists() else None
    return state


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------


def test_lock_busy_refusal_release_and_stale_takeover(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    release = acquire_owned_lock(vault, "test")
    lock = vault / "System/.dex/mutation.lock"
    assert lock.is_file()
    with pytest.raises(LockBusyError):
        acquire_owned_lock(vault, "second")
    release()
    assert not lock.exists()
    # Dead-pid lock is safely taken over.
    lock.write_text('{"pid": 99999999, "kind": "dead", "token": "x"}\n')
    release2 = acquire_owned_lock(vault, "takeover")
    assert lock.is_file()
    release2()


def test_lock_release_after_takeover_is_a_noop(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    lock = vault / "System/.dex/mutation.lock"
    release_stale = acquire_owned_lock(vault, "one")
    # Simulate our process dying and another taking over: replace the file.
    lock.unlink()
    release_new = acquire_owned_lock(vault, "two")
    release_stale()  # must NOT steal the new owner's lock
    assert lock.is_file()
    release_new()


def test_lock_failed_acquisition_cleans_up_its_own_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #257 regression: the doctor tripped over its own orphaned lock.

    On Windows the directory fsync raised PermissionError AFTER the lock file
    was created (os.open cannot open directories there), so the acquisition
    failed but left a lock naming the doctor's own live PID. The doctor's
    next acquisition — writing System/.doctor-last-run.json — then reported
    "another Dex process (pid X)" where X was the doctor itself. A failure
    between creating the lock file and returning release() must remove the
    file, so the next acquisition in the same process starts clean.
    """
    import core.transaction.lock as lock_module

    vault = _vault(tmp_path)
    lock = vault / "System/.dex/mutation.lock"

    def windows_style_failure(directory: Path) -> None:
        raise PermissionError(13, "cannot open a directory handle")

    # First acquisition (the doctor's Tier-1 heal transaction) fails after
    # the lock file exists — the exact Windows failure shape.
    monkeypatch.setattr(lock_module, "fsync_directory", windows_style_failure)
    with pytest.raises(PermissionError):
        acquire_owned_lock(vault, "transaction:t1-heal")
    monkeypatch.undo()

    # The failed acquisition must not leave a lock naming our own live PID.
    assert not lock.exists()

    # Second acquisition (the doctor-report write) used to raise LockBusyError
    # naming our own PID; with the orphan gone it must simply succeed.
    release = acquire_owned_lock(vault, "transaction:doctor-report")
    assert json.loads(lock.read_text())["kind"] == "transaction:doctor-report"
    release()
    assert not lock.exists()


def test_lock_supports_the_doctors_sequential_double_acquisition(tmp_path: Path) -> None:
    """doctor --heal acquires for the heal transaction, releases, then
    acquires again in the same process to write the last-run report."""
    vault = _vault(tmp_path)
    release_heal = acquire_owned_lock(vault, "transaction:t1-heal")
    release_heal()
    release_report = acquire_owned_lock(vault, "transaction:doctor-report")
    release_report()
    assert not (vault / "System/.dex/mutation.lock").exists()


def test_fsync_directory_is_a_noop_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows cannot open a directory descriptor; the shared directory fsync
    (used by the lock, journal, snapshots, ledger, and engines) must return
    without attempting to, instead of failing after the write it guards."""
    import core.transaction.fsync as fsync_module

    monkeypatch.setattr(fsync_module.os, "name", "nt")

    def forbidden(*args: object, **kwargs: object) -> int:
        raise AssertionError("no directory descriptor may be opened on Windows")

    monkeypatch.setattr(fsync_module.os, "open", forbidden)
    fsync_module.fsync_directory(tmp_path)  # must not raise


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------


def test_journal_round_trip_and_sequence(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "j.jsonl")
    journal.append("BEGIN", {"n": 1})
    journal.append("DONE")
    entries = journal.read()
    assert [entry.event for entry in entries] == ["BEGIN", "DONE"]
    assert [entry.sequence for entry in entries] == [1, 2]


def test_journal_torn_tail_is_dropped_and_recovered_on_append(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "j.jsonl")
    journal.append("BEGIN")
    with open(journal.path, "ab") as handle:
        handle.write(b'{"torn": "wri')
    assert [entry.event for entry in journal.read()] == ["BEGIN"]
    journal.append("RESUMED")
    assert [entry.event for entry in journal.read()] == ["BEGIN", "RESUMED"]


def test_journal_missing_final_newline_is_repaired(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "j.jsonl")
    journal.append("BEGIN")
    journal.append("APPLY")
    journal.path.write_bytes(journal.path.read_bytes().rstrip(b"\n"))
    journal.append("VERIFY")
    assert [entry.event for entry in journal.read()] == ["BEGIN", "APPLY", "VERIFY"]


def test_journal_interior_tamper_fails_closed(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "j.jsonl")
    journal.append("A")
    journal.append("B")
    tampered = journal.path.read_bytes().replace(b'"event":"A"', b'"event":"X"')
    journal.path.write_bytes(tampered)
    with pytest.raises(JournalCorruptError):
        journal.read()
    with pytest.raises(JournalCorruptError):
        journal.append("C")


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_snapshot_restore_is_byte_and_mode_exact_and_deletes_created(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    (vault / "a.md").write_text("original A")
    os.chmod(vault / "a.md", 0o640)
    (vault / "sub").mkdir()
    (vault / "sub/b.md").write_text("original B")
    relatives = ["a.md", "sub/b.md", "created.md"]
    before = _tree_state(vault, relatives)

    snapshot = Snapshot(tmp_path / "tx" / "snapshot")
    snapshot.capture(vault, relatives)
    (vault / "a.md").write_text("CLOBBERED")
    (vault / "sub/b.md").unlink()
    (vault / "created.md").write_text("made by tx")

    snapshot.restore(vault)
    assert _tree_state(vault, relatives) == before


def test_snapshot_damaged_store_fails_closed(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "a.md").write_text("original")
    snapshot = Snapshot(tmp_path / "tx")
    snapshot.capture(vault, ["a.md"])
    (snapshot.root / "000000.bin").write_bytes(b"tampered")
    (vault / "a.md").write_text("mutated")
    with pytest.raises(SnapshotError):
        snapshot.restore(vault)
    assert (vault / "a.md").read_text() == "mutated"  # nothing half-restored


def test_snapshot_refuses_symlinks_and_directories(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "real.md").write_text("x")
    (vault / "link.md").symlink_to(vault / "real.md")
    with pytest.raises(SnapshotError):
        Snapshot(tmp_path / "tx1").capture(vault, ["link.md"])
    with pytest.raises(SnapshotError):
        Snapshot(tmp_path / "tx2").capture(vault, ["System"])


# ---------------------------------------------------------------------------
# Engine semantics
# ---------------------------------------------------------------------------


def test_engine_happy_path_commits_and_reports(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    result = Transaction.begin(
        vault,
        [
            PlanEntry("03-Tasks/Tasks.md", b"# Tasks\n"),
            PlanEntry("System/.installed-files.manifest", b"a\n"),
        ],
    ).run()
    assert result["committed"] is True
    assert (vault / "03-Tasks/Tasks.md").read_bytes() == b"# Tasks\n"


def test_engine_refuses_symlinked_transaction_infrastructure(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / "System" / ".dex").symlink_to(outside, target_is_directory=True)

    with pytest.raises(TransactionError, match=r"System/\.dex"):
        Transaction.begin(
            vault,
            [PlanEntry("System/.installed-files.manifest", b"new manifest\n")],
        ).run()

    assert list(outside.iterdir()) == []


def test_engine_rejects_seed_overwrite_vault_deny_and_unclassified(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    (vault / "03-Tasks").mkdir()
    (vault / "03-Tasks/Tasks.md").write_text("user's tasks")
    # Existing seed: the user's file always wins.
    with pytest.raises(PlanRejected):
        Transaction.begin(vault, [PlanEntry("03-Tasks/Tasks.md", b"clobber")])
    assert (vault / "03-Tasks/Tasks.md").read_text() == "user's tasks"
    # Vault content, hard-denied secrets, unclassified paths: all refused.
    for relative in ("04-Projects/notes.md", ".env", "totally/unknown.xyz"):
        with pytest.raises(PlanRejected):
            Transaction.begin(vault, [PlanEntry(relative, b"x")])
    # One bad entry rejects the WHOLE plan (all-or-nothing).
    with pytest.raises(PlanRejected):
        Transaction.begin(
            vault,
            [
                PlanEntry("System/.installed-files.manifest", b"fine"),
                PlanEntry(".env", b"never"),
            ],
        )
    assert not (vault / "System/.installed-files.manifest").exists()


def test_engine_default_operation_refuses_customization_capsule_path(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)

    with pytest.raises(PlanRejected):
        Transaction.begin(
            vault,
            [
                PlanEntry(
                    "System/.dex/customization-migrations/x/manifest.json",
                    b"{}\n",
                )
            ],
        )


def test_engine_customization_migration_operation_authorizes_capsule_path(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    target = "System/.dex/customization-migrations/x/manifest.json"

    result = Transaction.begin(
        vault,
        [PlanEntry(target, b"{}\n")],
        operation="customization-migration",
    ).run()

    assert result["committed"] is True
    assert (vault / target).read_bytes() == b"{}\n"
    begin = Journal(
        vault / "System/.dex/tx" / result["tx_id"] / "journal.jsonl"
    ).read()[0]
    assert begin.event == "BEGIN"
    assert begin.payload["operation"] == "customization-migration"


def test_engine_customization_migration_operation_refuses_user_content(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)

    with pytest.raises(PlanRejected, match="outside-migration-seams"):
        Transaction.begin(
            vault,
            [PlanEntry("05-Areas/People/x.md", b"never\n")],
            operation="customization-migration",
        )


def test_engine_unknown_operation_value_error_propagates(tmp_path: Path) -> None:
    vault = _vault(tmp_path)

    with pytest.raises(ValueError, match="unknown write operation: garbage"):
        Transaction.begin(
            vault,
            [PlanEntry("System/.installed-files.manifest", b"manifest\n")],
            operation="garbage",
        )


def test_engine_authorization_gate_is_load_bearing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Red-when-removed: neuter the contract verdict and the engine happily
    writes into user content — proving the gate is what stands between an
    update and the user's files."""
    from core import portable_contract
    from core.transaction import engine as engine_module

    vault = _vault(tmp_path)
    monkeypatch.setattr(
        engine_module.portable_contract,
        "update_write_verdict",
        lambda path, *, exists, operation="update": portable_contract.WriteVerdict(
            path, True, "replace", "brain", "x"
        ),
    )
    result = Transaction.begin(vault, [PlanEntry("04-Projects/notes.md", b"gate gone")]).run()
    assert result["committed"] is True  # would be PlanRejected with the gate intact


def test_engine_verify_failure_rolls_back_byte_exact(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    target = vault / "System/.installed-files.manifest"
    target.write_bytes(b"old manifest\n")

    class Sabotaged(PlanEntry):
        def sha256(self) -> str:  # applied bytes will never match this
            return "0" * 64

    tx = Transaction.begin(vault, [Sabotaged("System/.installed-files.manifest", b"new\n")])
    with pytest.raises(Exception):
        tx.run()
    assert target.read_bytes() == b"old manifest\n"


def test_engine_content_write_with_matching_precondition_applies_and_verifies(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    target = vault / "README.md"
    target.write_bytes(b"captured bytes\n")
    os.chmod(target, 0o600)
    expected = hashlib.sha256(target.read_bytes()).hexdigest()

    result = Transaction.begin(
        vault,
        [PlanEntry("README.md", b"replacement\n", 0o644, expected_current_sha256=expected)],
    ).run()

    assert result["committed"] is True
    assert target.read_bytes() == b"replacement\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_engine_content_write_precondition_mismatch_rejects_without_mutation(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    target = vault / "README.md"
    target.write_bytes(b"user changed bytes\n")
    before = _tree_state(vault, ["README.md"])

    tx = Transaction.begin(
        vault,
        [PlanEntry("README.md", b"replacement\n", expected_current_sha256="0" * 64)],
    )
    with pytest.raises(PlanRejected, match="the existing file wins and the transaction aborts"):
        tx.run()

    assert _tree_state(vault, ["README.md"]) == before


def test_engine_content_write_precondition_requires_existing_target(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    tx = Transaction.begin(
        vault,
        [PlanEntry("README.md", b"replacement\n", expected_current_sha256="0" * 64)],
    )

    with pytest.raises(PlanRejected, match="the existing file wins and the transaction aborts"):
        tx.run()

    assert not (vault / "README.md").exists()


@pytest.mark.parametrize(
    "expected",
    [
        "A" * 64,
        "not-a-sha256",
    ],
)
def test_engine_content_write_precondition_requires_lowercase_sha256(
    expected: str,
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)

    with pytest.raises(PlanRejected, match="must be a lowercase sha256"):
        Transaction.begin(
            vault,
            [PlanEntry("README.md", b"replacement\n", expected_current_sha256=expected)],
        )


def test_engine_content_write_precondition_rejects_symlink_target(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"captured bytes\n")
    target = vault / "README.md"
    target.symlink_to(outside)
    expected = hashlib.sha256(outside.read_bytes()).hexdigest()
    tx = Transaction.begin(
        vault,
        [PlanEntry("README.md", b"replacement\n", expected_current_sha256=expected)],
    )

    with pytest.raises(PlanRejected, match="the existing file wins and the transaction aborts"):
        tx.run()

    assert target.is_symlink()
    assert outside.read_bytes() == b"captured bytes\n"


def test_engine_expected_absent_write_commits_and_is_journalled(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)

    result = Transaction.begin(
        vault,
        [PlanEntry("CLAUDE-custom.md", b"# Migrated\n", expected_absent=True)],
        operation="customization-migration",
    ).run()

    assert result["committed"] is True
    assert (vault / "CLAUDE-custom.md").read_bytes() == b"# Migrated\n"
    begin = Journal(
        vault / "System/.dex/tx" / result["tx_id"] / "journal.jsonl"
    ).read()[0]
    assert begin.payload["plan"][0]["expected_absent"] is True


def test_engine_expected_absent_rejects_target_present_at_snapshot(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    tx = Transaction.begin(
        vault,
        [
            PlanEntry(
                "System/.dex/customization-migrations/x/receipt.json",
                b"{}\n",
            ),
            PlanEntry(
                "CLAUDE-custom.md",
                b"# Migrated\n",
                expected_absent=True,
            ),
        ],
        operation="customization-migration",
    )
    target = vault / "CLAUDE-custom.md"
    target.write_bytes(b"# User created this\n")

    with pytest.raises(
        PlanRejected,
        match="the existing file wins and the transaction aborts",
    ):
        tx.run()

    assert target.read_bytes() == b"# User created this\n"
    assert not (
        vault / "System/.dex/customization-migrations/x/receipt.json"
    ).exists()


def test_engine_expected_absent_rechecks_before_write_and_rolls_back(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    first = "System/.dex/customization-migrations/x/receipt.json"
    guarded = vault / "CLAUDE-custom.md"
    tx = Transaction.begin(
        vault,
        [
            PlanEntry(first, b"{}\n"),
            PlanEntry(
                "CLAUDE-custom.md",
                b"# Migrated\n",
                expected_absent=True,
            ),
        ],
        operation="customization-migration",
    )
    original_append = tx.journal.append

    def create_after_first_apply(event: str, payload=None) -> None:
        original_append(event, payload)
        if event == "APPLIED" and payload["index"] == 0:
            guarded.write_bytes(b"# User won the race\n")

    tx.journal.append = create_after_first_apply

    with pytest.raises(
        PlanRejected,
        match="the existing file wins and the transaction aborts",
    ):
        tx.run()

    assert guarded.read_bytes() == b"# User won the race\n"
    assert not (vault / first).exists()


def test_engine_expected_absent_publication_cannot_clobber_final_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.transaction import engine as engine_module

    vault = _vault(tmp_path)
    target = vault / "CLAUDE-custom.md"
    original_link = os.link

    def user_wins_immediately_before_publish(source, destination, **kwargs) -> None:
        target.write_bytes(b"# User created at the final boundary\n")
        original_link(source, destination, **kwargs)

    monkeypatch.setattr(engine_module.os, "link", user_wins_immediately_before_publish)
    tx = Transaction.begin(
        vault,
        [PlanEntry("CLAUDE-custom.md", b"# Migrated\n", expected_absent=True)],
        operation="customization-migration",
    )

    with pytest.raises(
        PlanRejected,
        match="the existing file wins and the transaction aborts",
    ):
        tx.run()

    assert target.read_bytes() == b"# User created at the final boundary\n"


def test_engine_expected_absent_applying_record_never_owns_a_user_file(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    target = vault / "CLAUDE-custom.md"
    tx = Transaction.begin(
        vault,
        [PlanEntry("CLAUDE-custom.md", b"# Migrated\n", expected_absent=True)],
        operation="customization-migration",
    )
    original_append = tx.journal.append

    def interrupt_after_apply_intent(event: str, payload=None) -> None:
        original_append(event, payload)
        if event == "APPLYING":
            target.write_bytes(b"# User created before publication\n")
            raise RuntimeError("crash before expected-absent publication")

    tx.journal.append = interrupt_after_apply_intent

    with pytest.raises(RuntimeError, match="crash before"):
        tx.run()

    assert target.read_bytes() == b"# User created before publication\n"


def test_resume_removes_expected_absent_publish_when_temp_is_gone_but_target_matches_begin(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    relative = "CLAUDE-custom.md"
    planned = b"# Migrated\n"
    entry = PlanEntry(relative, planned, expected_absent=True)
    tx = Transaction.begin(
        vault,
        [entry],
        operation="customization-migration",
    )
    tx._snapshot_phase()
    tx.journal.append("APPLY-START")
    tx.journal.append(
        "APPLYING",
        {"index": 0, "relative": relative, "expected_absent": True},
    )
    original_append = tx.journal.append

    def tear_before_published(event: str, payload=None) -> None:
        if event == "PUBLISHED":
            raise RuntimeError("crash after link before publication record")
        original_append(event, payload)

    tx.journal.append = tear_before_published

    with pytest.raises(RuntimeError, match="after link"):
        tx._apply_one(0, entry)

    target = vault / relative
    temporary = target.parent / f".{target.name}.tx-{tx.tx_id}"
    assert target.read_bytes() == planned
    assert (target.stat().st_dev, target.stat().st_ino) == (
        temporary.stat().st_dev,
        temporary.stat().st_ino,
    )
    temporary.unlink()
    assert tx._release is not None
    tx._release()
    tx._release = None

    Transaction.resume(vault)

    assert not target.exists()


def test_resume_rehydrates_a_receipt_read_cap_before_comparing_a_target(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    relative = "System/.dex/analytics-attempts.jsonl"
    planned = b'{"event":"task_created"}\n'
    max_read_bytes = portable_contract.ANALYTICS_ATTEMPT_RECEIPT_TRANSACTION_MAX_BYTES
    tx = Transaction.begin(
        vault,
        [PlanEntry(relative, planned, expected_absent=True)],
        operation="analytics-receipt",
        max_read_bytes_by_relative={relative: max_read_bytes},
    )
    begin = Journal(tx.tx_dir / "journal.jsonl").read()[0]
    assert begin.payload["max_read_bytes_by_relative"] == {
        relative: max_read_bytes,
    }
    tx._snapshot_phase()
    tx.journal.append("APPLY-START")
    tx.journal.append(
        "APPLYING",
        {"index": 0, "relative": relative, "expected_absent": True},
    )
    target = vault / relative
    target.write_bytes(planned)
    assert tx._release is not None
    tx._release()
    tx._release = None

    Transaction.resume(vault)

    assert not target.exists()


def test_engine_analytics_receipt_requires_its_exact_bounded_read_limit(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    relative = "System/.dex/analytics-attempts.jsonl"

    with pytest.raises(PlanRejected, match="required bounded-read limit"):
        Transaction.begin(
            vault,
            [PlanEntry(relative, b"{}\n", expected_absent=True)],
            operation="analytics-receipt",
        )


def test_resume_quarantines_analytics_receipt_without_a_persisted_read_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path)
    tx_id = "20260812T000000-receipt"
    relative = "System/.dex/analytics-attempts.jsonl"
    target = vault / relative
    target.write_bytes(b"private bytes must not be read")
    journal = Journal(vault / "System/.dex/tx" / tx_id / "journal.jsonl")
    journal.append(
        "BEGIN",
        {
            "tx_id": tx_id,
            "operation": "analytics-receipt",
            "plan": [
                {
                    "relative": relative,
                    "sha256": hashlib.sha256(b"{}\n").hexdigest(),
                    "size": 3,
                    "expected_absent": True,
                }
            ],
        },
    )
    monkeypatch.setattr(
        Transaction,
        "_target_matches_planned_content",
        staticmethod(lambda *_args, **_kwargs: pytest.fail("receipt target was read")),
    )

    outcomes = Transaction.resume(vault)

    assert outcomes == [
        {
            "tx_id": tx_id,
            "committed": False,
            "resumed": True,
            "quarantined": "analytics receipt transaction lacks the required bounded-read limit",
        }
    ]
    assert target.read_bytes() == b"private bytes must not be read"


def test_engine_automation_ownership_requires_its_exact_bounded_read_limit(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    relative = portable_contract.AUTOMATION_OWNERSHIP_RELATIVE

    with pytest.raises(PlanRejected, match="required bounded-read limit"):
        Transaction.begin(
            vault,
            [PlanEntry(relative, b'{"claims":[],"schema_version":1}\n', expected_absent=True)],
            operation="automation-ownership",
        )


def test_resume_quarantines_automation_ownership_without_a_persisted_read_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path)
    tx_id = "20260813T000000-automation-ownership"
    relative = portable_contract.AUTOMATION_OWNERSHIP_RELATIVE
    target = vault / relative
    target.write_bytes(b"private bytes must not be read")
    journal = Journal(vault / "System/.dex/tx" / tx_id / "journal.jsonl")
    journal.append(
        "BEGIN",
        {
            "tx_id": tx_id,
            "operation": "automation-ownership",
            "plan": [
                {
                    "relative": relative,
                    "sha256": hashlib.sha256(b"{}\n").hexdigest(),
                    "size": 3,
                    "expected_absent": True,
                }
            ],
        },
    )
    monkeypatch.setattr(
        Transaction,
        "_target_matches_planned_content",
        staticmethod(lambda *_args, **_kwargs: pytest.fail("automation ownership target was read")),
    )

    outcomes = Transaction.resume(vault)

    assert outcomes == [
        {
            "tx_id": tx_id,
            "committed": False,
            "resumed": True,
            "quarantined": "automation ownership transaction lacks the required bounded-read limit",
        }
    ]
    assert target.read_bytes() == b"private bytes must not be read"


def test_resume_preserves_expected_absent_user_file_matching_plan_when_temp_inode_differs(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    relative = "CLAUDE-custom.md"
    planned = b"# Migrated\n"
    tx = Transaction.begin(
        vault,
        [PlanEntry(relative, planned, expected_absent=True)],
        operation="customization-migration",
    )
    tx._snapshot_phase()
    tx.journal.append("APPLY-START")
    tx.journal.append(
        "APPLYING",
        {"index": 0, "relative": relative, "expected_absent": True},
    )
    target = vault / relative
    temporary = target.parent / f".{target.name}.tx-{tx.tx_id}"
    temporary.write_bytes(planned)
    target.write_bytes(planned)
    assert (target.stat().st_dev, target.stat().st_ino) != (
        temporary.stat().st_dev,
        temporary.stat().st_ino,
    )
    assert tx._release is not None
    tx._release()
    tx._release = None

    Transaction.resume(vault)

    assert target.read_bytes() == planned


def test_resume_preserves_expected_absent_user_file_when_temp_is_gone_and_bytes_differ(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    relative = "CLAUDE-custom.md"
    tx = Transaction.begin(
        vault,
        [PlanEntry(relative, b"# Migrated\n", expected_absent=True)],
        operation="customization-migration",
    )
    tx._snapshot_phase()
    tx.journal.append("APPLY-START")
    tx.journal.append(
        "APPLYING",
        {"index": 0, "relative": relative, "expected_absent": True},
    )
    target = vault / relative
    user_bytes = b"# User created during recovery window\n"
    target.write_bytes(user_bytes)
    assert tx._release is not None
    tx._release()
    tx._release = None

    Transaction.resume(vault)

    assert target.read_bytes() == user_bytes


def test_target_matches_planned_content_refuses_symlink_target(
    tmp_path: Path,
) -> None:
    planned = b"# Migrated\n"
    real_target = tmp_path / "real-target.md"
    real_target.write_bytes(planned)
    symlink_target = tmp_path / "symlink-target.md"
    symlink_target.symlink_to(real_target)

    assert not Transaction._target_matches_planned_content(
        symlink_target,
        planned_sha256=hashlib.sha256(planned).hexdigest(),
        planned_size=len(planned),
    )


def test_engine_expected_absent_is_mutually_exclusive_with_current_hash(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)

    with pytest.raises(PlanRejected, match="cannot also assert current bytes"):
        Transaction.begin(
            vault,
            [
                PlanEntry(
                    "CLAUDE-custom.md",
                    b"# Migrated\n",
                    expected_current_sha256="0" * 64,
                    expected_absent=True,
                )
            ],
            operation="customization-migration",
        )


def test_engine_expected_absent_is_invalid_for_deletion(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    target = vault / "README.md"
    target.write_bytes(b"shipped bytes\n")
    expected = hashlib.sha256(target.read_bytes()).hexdigest()

    with pytest.raises(PlanRejected, match="only valid on content writes"):
        Transaction.begin(
            vault,
            [
                PlanEntry(
                    "README.md",
                    None,
                    expected_current_sha256=expected,
                    expected_absent=True,
                )
            ],
        )

    assert target.read_bytes() == b"shipped bytes\n"


def test_engine_rechecks_content_precondition_and_rolls_back_applied_entries(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    first = vault / "System/.installed-files.manifest"
    first.write_bytes(b"old manifest\n")
    guarded = vault / "README.md"
    guarded.write_bytes(b"captured bytes\n")
    expected = hashlib.sha256(guarded.read_bytes()).hexdigest()
    tx = Transaction.begin(
        vault,
        [
            PlanEntry("System/.installed-files.manifest", b"new manifest\n"),
            PlanEntry("README.md", b"replacement\n", expected_current_sha256=expected),
        ],
    )
    original_append = tx.journal.append

    def swap_after_first_apply(event: str, payload=None) -> None:
        original_append(event, payload)
        if event == "APPLIED" and payload["index"] == 0:
            guarded.write_bytes(b"user edit in snapshot-to-apply window\n")

    tx.journal.append = swap_after_first_apply

    with pytest.raises(PlanRejected, match="changed after the mutation snapshot"):
        tx.run()

    assert first.read_bytes() == b"old manifest\n"
    assert guarded.read_bytes() == b"user edit in snapshot-to-apply window\n"


def test_engine_delete_entry_commits_and_rolls_back_byte_exact(tmp_path: Path) -> None:
    """Updater removals use the same snapshot/apply/verify/undo path as writes."""
    vault = _vault(tmp_path)
    target = vault / "README.md"
    target.write_bytes(b"old shipped bytes\r\nwith\x00data")
    os.chmod(target, 0o640)

    original_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    deleted = Transaction.begin(
        vault,
        [PlanEntry("README.md", None, 0o640, expected_current_sha256=original_sha)],
    ).run()

    assert deleted["committed"] is True
    assert not target.exists()

    target.write_bytes(b"restorable shipped bytes\n")
    os.chmod(target, 0o600)
    restorable_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    tx = Transaction.begin(
        vault,
        [PlanEntry("README.md", None, 0o600, expected_current_sha256=restorable_sha)],
    )
    original_verify = tx._verify_phase

    def verify_then_fail() -> None:
        original_verify()
        raise RuntimeError("simulated updater verification failure")

    tx._verify_phase = verify_then_fail
    with pytest.raises(RuntimeError, match="simulated updater"):
        tx.run()

    assert target.read_bytes() == b"restorable shipped bytes\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_engine_rejects_deletion_without_current_content_precondition(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    target = vault / "README.md"
    target.write_bytes(b"shipped bytes\n")

    with pytest.raises(PlanRejected, match="deletions require"):
        Transaction.begin(vault, [PlanEntry("README.md", None)])

    assert target.read_bytes() == b"shipped bytes\n"


def test_engine_delete_precondition_preserves_a_file_changed_after_planning(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    target = vault / "README.md"
    target.write_bytes(b"unchanged shipped bytes\n")
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    tx = Transaction.begin(
        vault,
        [PlanEntry("README.md", None, 0o644, expected_current_sha256=expected)],
    )
    target.write_bytes(b"user changed this after planning\n")

    with pytest.raises(PlanRejected, match="changed after the mutation plan"):
        tx.run()

    assert target.read_bytes() == b"user changed this after planning\n"


def test_engine_rechecks_deletion_content_immediately_before_unlink(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    target = vault / "README.md"
    target.write_bytes(b"shipped bytes\n")
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    tx = Transaction.begin(
        vault,
        [PlanEntry("README.md", None, 0o644, expected_current_sha256=expected)],
    )
    tx._snapshot_phase()
    original_append = tx.journal.append

    def change_after_apply_intent(event: str, payload=None) -> None:
        original_append(event, payload)
        if event == "APPLYING":
            target.write_bytes(b"changed immediately before unlink\n")

    tx.journal.append = change_after_apply_intent

    with pytest.raises(PlanRejected, match="changed after the mutation snapshot"):
        tx._apply_phase()
    tx.rollback()

    assert target.read_bytes() == b"changed immediately before unlink\n"


def test_engine_holds_the_single_mutator_lock(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    tx = Transaction.begin(vault, [PlanEntry("System/.installed-files.manifest", b"a\n")])
    with pytest.raises(LockBusyError):
        acquire_owned_lock(vault, "other-engine")
    tx.run()  # commit releases
    release = acquire_owned_lock(vault, "other-engine")
    release()


# ---------------------------------------------------------------------------
# Fault injection: kill the engine at every seam, resume, converge
# ---------------------------------------------------------------------------

_WORKER = r"""
import sys
sys.path.insert(0, sys.argv[2])
from pathlib import Path
from core.transaction.engine import Transaction, PlanEntry
vault = Path(sys.argv[1])
Transaction.begin(vault, [
    PlanEntry("03-Tasks/Tasks.md", b"# New Tasks\n"),
    PlanEntry("System/.installed-files.manifest", b"regenerated\n"),
]).run()
"""

_RELATIVES = ["03-Tasks/Tasks.md", "System/.installed-files.manifest"]

_PRECONDITION_WORKER = r"""
import hashlib
import sys
sys.path.insert(0, sys.argv[2])
from pathlib import Path
from core.transaction.engine import Transaction, PlanEntry
vault = Path(sys.argv[1])
target = vault / "README.md"
expected = hashlib.sha256(target.read_bytes()).hexdigest()
Transaction.begin(vault, [
    PlanEntry("README.md", b"replacement\n", 0o600, expected_current_sha256=expected),
    PlanEntry("System/.installed-files.manifest", b"regenerated\n"),
]).run()
"""

_MIGRATION_OPERATION_WORKER = r"""
import sys
sys.path.insert(0, sys.argv[2])
from pathlib import Path
from core.transaction.engine import Transaction, PlanEntry
vault = Path(sys.argv[1])
Transaction.begin(
    vault,
    [PlanEntry("System/.dex/customization-migrations/x/manifest.json", b"{}\n")],
    operation="customization-migration",
).run()
"""


@pytest.mark.parametrize(
    "seam",
    [
        "after-begin",
        "after-snapshot",
        "mid-apply:0",
        "after-apply",
        "after-verify",
        "after-commit-record",
    ],
)
def test_crash_at_every_seam_converges(seam: str, tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "System/.installed-files.manifest").write_bytes(b"old manifest\n")
    before = _tree_state(vault, _RELATIVES)

    env = dict(os.environ, DEX_TX_TEST_STOP_AFTER=seam)
    process = subprocess.run(
        [sys.executable, "-c", _WORKER, str(vault), str(REPO_ROOT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert process.returncode == 137, (seam, process.stderr[-300:])

    outcomes = Transaction.resume(vault)
    after = _tree_state(vault, _RELATIVES)

    if seam == "after-commit-record":
        # The commit record exists: the applied, verified work stands.
        assert after["03-Tasks/Tasks.md"][0] == b"# New Tasks\n"
        assert outcomes == []
    else:
        # No commit record: the tree is byte-identical to before the crash.
        assert after == before, seam
        assert len(outcomes) == 1 and outcomes[0]["resumed"] is True

    # Either way the vault must be immediately usable again.
    Transaction.begin(vault, [PlanEntry("System/.installed-files.manifest", b"post-recovery\n")]).run()


def test_resume_is_idempotent(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    env = dict(os.environ, DEX_TX_TEST_STOP_AFTER="after-apply")
    subprocess.run(
        [sys.executable, "-c", _WORKER, str(vault), str(REPO_ROOT)],
        env=env,
        capture_output=True,
        timeout=60,
    )
    first = Transaction.resume(vault)
    second = Transaction.resume(vault)
    assert len(first) == 1
    assert second == []


def test_resume_restores_operation_from_begin_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path)
    environment = dict(os.environ, DEX_TX_TEST_STOP_AFTER="after-begin")
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            _MIGRATION_OPERATION_WORKER,
            str(vault),
            str(REPO_ROOT),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert process.returncode == 137
    observed: list[str] = []
    original = Transaction.rollback

    def capture_operation(transaction: Transaction) -> dict:
        observed.append(transaction.operation)
        return original(transaction)

    monkeypatch.setattr(Transaction, "rollback", capture_operation)

    Transaction.resume(vault)

    assert observed == ["customization-migration"]


def test_resume_rolls_back_content_precondition_plan_byte_exact(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    target = vault / "README.md"
    target.write_bytes(b"original bytes\r\nwith\x00data")
    os.chmod(target, 0o640)
    relatives = ["README.md", "System/.installed-files.manifest"]
    before = _tree_state(vault, relatives)
    env = dict(os.environ, DEX_TX_TEST_STOP_AFTER="mid-apply:0")

    process = subprocess.run(
        [sys.executable, "-c", _PRECONDITION_WORKER, str(vault), str(REPO_ROOT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert process.returncode == 137, process.stderr[-300:]

    outcomes = Transaction.resume(vault)

    assert _tree_state(vault, relatives) == before
    assert len(outcomes) == 1 and outcomes[0]["resumed"] is True


# ---------------------------------------------------------------------------
# Adversarial-review fixes (F1-F5, F9), each pinned
# ---------------------------------------------------------------------------


def test_seed_created_mid_window_wins_and_aborts_transaction(tmp_path: Path) -> None:
    """F1: a seed file appearing AFTER authorization (user, Obsidian, background
    sync) must survive — the transaction aborts and rolls back, and the user's
    file is untouched by the rollback."""
    vault = _vault(tmp_path)
    tx = Transaction.begin(
        vault,
        [
            PlanEntry("System/.installed-files.manifest", b"regen\n"),
            PlanEntry("03-Tasks/Tasks.md", b"SEED CLOBBER\n"),
        ],
    )
    # Simulate a concurrent writer creating the seed inside the window.
    (vault / "03-Tasks").mkdir()
    (vault / "03-Tasks/Tasks.md").write_text("USER'S PRECIOUS TASKS")
    with pytest.raises(PlanRejected):
        tx.run()
    assert (vault / "03-Tasks/Tasks.md").read_text() == "USER'S PRECIOUS TASKS"
    # The already-applied manifest entry was rolled back too (all-or-nothing).
    assert not (vault / "System/.installed-files.manifest").exists()


def test_resume_quarantines_a_corrupt_journal_and_recovers_the_rest(
    tmp_path: Path,
) -> None:
    """F2: one poisoned journal must not strand recovery of other transactions."""
    vault = _vault(tmp_path)
    (vault / "System/.installed-files.manifest").write_bytes(b"old\n")
    env = dict(os.environ, DEX_TX_TEST_STOP_AFTER="after-apply")
    subprocess.run(
        [sys.executable, "-c", _WORKER, str(vault), str(REPO_ROOT)],
        env=env,
        capture_output=True,
        timeout=60,
    )
    # Plant a corrupt transaction that sorts FIRST.
    poison = vault / "System/.dex/tx/00000000T000000-poison"
    poison.mkdir(parents=True)
    journal = Journal(poison / "journal.jsonl")
    journal.append("BEGIN")
    tampered = journal.path.read_bytes().replace(b'"event":"BEGIN"', b'"event":"XEGIN"')
    journal.path.write_bytes(tampered)

    outcomes = Transaction.resume(vault)

    by_id = {outcome["tx_id"]: outcome for outcome in outcomes}
    assert any("poison" in tx_id for tx_id in by_id)  # quarantined, not fatal
    real = [o for o in outcomes if "poison" not in o["tx_id"]]
    assert len(real) == 1 and real[0]["resumed"] is True
    assert (vault / "System/.installed-files.manifest").read_bytes() == b"old\n"


def test_rollback_removes_directories_the_transaction_created(tmp_path: Path) -> None:
    """F3: rollback removes empty directories the apply created."""
    vault = _vault(tmp_path)
    tx = Transaction.begin(vault, [PlanEntry("System/Templates/New/Deep/t.md", b"x\n")])
    tx._snapshot_phase()
    tx._apply_phase()
    tx.rollback()
    assert not (vault / "System/Templates/New/Deep").exists()
    assert not (vault / "System/Templates/New").exists()
    assert not (vault / "System/Templates").exists()
    assert (vault / "System").exists()  # pre-existing dirs stay


def test_rollback_never_deletes_a_user_created_file_without_applied_record(
    tmp_path: Path,
) -> None:
    """F1 companion: rollback deletes a created-class file ONLY when the
    journal proves the transaction wrote it."""
    vault = _vault(tmp_path)
    tx = Transaction.begin(vault, [PlanEntry("03-Tasks/Tasks.md", b"seed\n")])
    tx._snapshot_phase()  # captured existed=False
    # A concurrent writer creates the file; the transaction never applies it.
    (vault / "03-Tasks").mkdir()
    (vault / "03-Tasks/Tasks.md").write_text("USER FILE")
    tx.rollback()
    assert (vault / "03-Tasks/Tasks.md").read_text() == "USER FILE"


def test_special_mode_bits_are_rejected(tmp_path: Path) -> None:
    """F5: no setuid/setgid/sticky or non-permission bits."""
    vault = _vault(tmp_path)
    with pytest.raises(PlanRejected):
        Transaction.begin(vault, [PlanEntry("System/.installed-files.manifest", b"x", mode=0o4777)])


def test_verify_checks_mode_as_well_as_bytes(tmp_path: Path) -> None:
    """F9: a mode mismatch after apply fails verification and rolls back."""
    vault = _vault(tmp_path)
    tx = Transaction.begin(vault, [PlanEntry("System/.installed-files.manifest", b"x\n", mode=0o600)])
    original_verify = tx._verify_phase

    def sabotage_then_verify() -> None:
        os.chmod(vault / "System/.installed-files.manifest", 0o644)
        original_verify()

    tx._verify_phase = sabotage_then_verify
    with pytest.raises(Exception):
        tx.run()
    assert not (vault / "System/.installed-files.manifest").exists()  # rolled back


def test_commit_prunes_to_last_three_snapshots(tmp_path: Path) -> None:
    """F4: retention (owner decision, lean) — keep the newest 3 committed
    transactions' snapshots, prune older ones."""
    vault = _vault(tmp_path)
    for index in range(5):
        Transaction.begin(
            vault,
            [PlanEntry("System/.installed-files.manifest", f"gen {index}\n".encode())],
        ).run()
    tx_root = vault / "System/.dex/tx"
    remaining = [p for p in tx_root.iterdir() if p.is_dir()]
    assert len(remaining) == 3


def _committed_tx_operations(vault: Path) -> list[str | None]:
    """The BEGIN operation of every surviving committed transaction, oldest first."""
    operations: list[str | None] = []
    for candidate in sorted((vault / "System" / ".dex" / "tx").iterdir()):
        if not candidate.is_dir():
            continue
        entries = Journal(candidate / "journal.jsonl").read()
        if not any(entry.event == "COMMITTED" for entry in entries):
            continue
        begin = next((entry for entry in entries if entry.event == "BEGIN"), None)
        operations.append(begin.payload.get("operation") if begin else None)
    return operations


def test_bookkeeping_transactions_do_not_evict_rewindable_snapshots(tmp_path: Path) -> None:
    """Retention is per class, so routine receipts cannot cost a user their undo.

    ``analytics-receipt`` is written on every session start. Sharing one
    keep-last-3 budget meant three ordinary session opens evicted an adoption
    snapshot, after which ``rewind_adoption`` refuses with "no longer available
    under keep-last-3 retention" through no action of the user's.
    """
    vault = _vault(tmp_path)
    for index in range(3):
        Transaction.begin(
            vault,
            [PlanEntry("System/.installed-files.manifest", f"manifest {index}\n".encode())],
        ).run()
    assert _committed_tx_operations(vault).count("update") == 3

    receipt = portable_contract.ANALYTICS_ATTEMPT_RECEIPT_RELATIVE
    for index in range(6):
        Transaction.begin(
            vault,
            [PlanEntry(receipt, f"{{\"n\": {index}}}\n".encode())],
            operation="analytics-receipt",
            max_read_bytes_by_relative={
                receipt: portable_contract.ANALYTICS_ATTEMPT_RECEIPT_TRANSACTION_MAX_BYTES
            },
        ).run()

    surviving = _committed_tx_operations(vault)
    assert surviving.count("update") == 3, (
        "routine bookkeeping evicted a rewindable snapshot: " f"{surviving}"
    )
    assert surviving.count("analytics-receipt") == 3, (
        "bookkeeping should keep its own newest three, not grow without bound: " f"{surviving}"
    )
