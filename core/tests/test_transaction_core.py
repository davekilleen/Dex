"""The transaction core's contract, held under test.

Covers the four modules (lock, journal, snapshot, engine) plus the
fault-injection matrix: the engine is killed at every seam via
``DEX_TX_TEST_STOP_AFTER`` in a subprocess, then ``Transaction.resume`` runs
in this process and the tree must be byte-identical (pre-commit crash) or
fully applied (post-commit crash) — never mixed. The contract-authorization
gate carries a red-when-removed proof.
"""

from __future__ import annotations

import json
import os
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
        state[relative] = (
            (path.read_bytes(), path.stat().st_mode & 0o7777)
            if path.exists()
            else None
        )
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


def test_engine_authorization_gate_is_load_bearing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    Transaction.begin(
        vault, [PlanEntry("System/.installed-files.manifest", b"post-recovery\n")]
    ).run()


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
