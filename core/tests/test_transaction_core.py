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

from core.transaction.engine import PlanEntry, PlanRejected, Transaction
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
        lambda path, exists: portable_contract.WriteVerdict(path, True, "replace", "brain", "x"),
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
