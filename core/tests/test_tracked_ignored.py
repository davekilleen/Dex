"""Exact-policy and preservation tests for tracked-despite-ignored paths."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from core.migrations import preserve_local_only_paths as migration

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "core" / "migrations" / "tracked-ignored-policy.yaml"
CHECKER = ROOT / "scripts" / "check-tracked-ignored.py"
TRANSITION = Path("System/.local-only-preservation-transition.json")
VERSION = "1.61.0"


def _load_checker():
    spec = importlib.util.spec_from_file_location("tracked_ignored_checker", CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _policy_rows(policy: Path = POLICY) -> list[dict[str, str]]:
    return yaml.safe_load(policy.read_text(encoding="utf-8"))["paths"]


def _set_transition(repo: Path, phase: str) -> None:
    (repo / "package.json").write_text(json.dumps({"version": VERSION}) + "\n", encoding="utf-8")
    target = repo / TRANSITION
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"schema_version": 1, "phase": phase, "release_version": VERSION}) + "\n",
        encoding="utf-8",
    )


def _prepare_untrack(repo: Path, journal: Path) -> None:
    migration.capture(repo, journal)
    _set_transition(repo, "untrack-v1")


def _rewind(repo: Path, journal: Path) -> dict:
    _set_transition(repo, "bootstrap-v1")
    return migration.rewind(repo, journal)


@pytest.fixture
def tracked_ignored_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "vault"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "Fixture")
    rows = _policy_rows()
    ignore_lines = []
    for index, row in enumerate(rows):
        relative = row["path"]
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"fixture-{index}\n".encode())
        ignore_lines.append(f"/{relative}")
    fixture_policy = repo / migration.POLICY_RELATIVE
    fixture_policy.parent.mkdir(parents=True, exist_ok=True)
    fixture_policy.write_bytes(POLICY.read_bytes())
    _set_transition(repo, "bootstrap-v1")
    (repo / ".gitignore").write_text("\n".join(ignore_lines) + "\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "package.json", TRANSITION.as_posix(), migration.POLICY_RELATIVE.as_posix())
    _git(repo, "add", "-f", "--", *[row["path"] for row in rows])
    _git(repo, "commit", "-qm", "baseline")
    return repo


def _run_checker(repo: Path, policy: Path = POLICY) -> tuple[int, dict]:
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--repo", str(repo), "--policy", str(policy)],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, json.loads(result.stdout)


def _journal_payload(journal: Path) -> dict:
    return json.loads((journal / migration.MANIFEST_NAME).read_text(encoding="utf-8"))


def _write_journal_payload(journal: Path, payload: dict) -> None:
    (journal / migration.MANIFEST_NAME).write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _index_evidence(repo: Path, relative: str) -> tuple[str, str, str]:
    debug = _git(repo, "ls-files", "--debug", "--", relative).stdout
    flags = next(line.rsplit("flags: ", 1)[1] for line in debug.splitlines() if "flags: " in line)
    return (
        _git(repo, "ls-files", "--stage", "--", relative).stdout,
        flags,
        _git(repo, "diff", "--cached", "--name-status", "--", relative).stdout,
    )


def test_repository_policy_is_exact_23_seed_one_release_doc_three_local_only():
    rows = checker.load_policy(POLICY)
    by_class: dict[str, list[str]] = {}
    for row in rows:
        by_class.setdefault(row.classification, []).append(row.path)

    assert len(by_class["intentional-seed"]) == 23
    assert by_class["release-doc"] == ["System/Beta_Communications/2026-02-04_hardcoded_paths_fix.md"]
    assert tuple(by_class["local-only-must-be-untracked"]) == migration.LOCAL_ONLY_PATHS


def test_checker_reports_bootstrap_pending_then_future_untrack_clean(tracked_ignored_repo):
    before_code, before = _run_checker(tracked_ignored_repo)
    assert before_code == 0
    assert before == {
        "actual_tracked_ignored": 27,
        "errors": [],
        "expected_tracked": 24,
        "ok": True,
        "policy_rows": 27,
        "status": "migration-pending",
        "transition_phase": "bootstrap-v1",
    }

    original = {relative: (tracked_ignored_repo / relative).read_bytes() for relative in migration.LOCAL_ONLY_PATHS}
    _git(tracked_ignored_repo, "rm", "--cached", "--", *migration.LOCAL_ONLY_PATHS)
    _set_transition(tracked_ignored_repo, "untrack-v1")

    after_code, after = _run_checker(tracked_ignored_repo)
    assert after_code == 0
    assert after == {
        "actual_tracked_ignored": 24,
        "errors": [],
        "expected_tracked": 24,
        "ok": True,
        "policy_rows": 27,
        "status": "clean",
        "transition_phase": "untrack-v1",
    }
    assert {
        relative: (tracked_ignored_repo / relative).read_bytes() for relative in migration.LOCAL_ONLY_PATHS
    } == original


def test_checker_rejects_unknown_stale_duplicate_and_non_git_states(tracked_ignored_repo, tmp_path):
    _git(tracked_ignored_repo, "rm", "--cached", "--", *migration.LOCAL_ONLY_PATHS)
    _set_transition(tracked_ignored_repo, "untrack-v1")
    unknown = tracked_ignored_repo / "System" / "Session_Learnings" / "Case-É.md"
    unknown.write_text("unknown\n", encoding="utf-8")
    with (tracked_ignored_repo / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("/System/Session_Learnings/Case-É.md\n")
    _git(tracked_ignored_repo, "add", "-f", "--intent-to-add", str(unknown.relative_to(tracked_ignored_repo)))
    _, result = _run_checker(tracked_ignored_repo)
    assert result["errors"] == [{"code": "unknown-tracked-ignored", "paths": ["System/Session_Learnings/Case-É.md"]}]

    _git(tracked_ignored_repo, "reset", "--", str(unknown.relative_to(tracked_ignored_repo)))
    stale = _policy_rows()[0]["path"]
    _git(tracked_ignored_repo, "rm", "--cached", "--", stale)
    _, result = _run_checker(tracked_ignored_repo)
    assert result["errors"] == [{"code": "stale-policy-row", "paths": [stale]}]

    duplicate_policy = tmp_path / "duplicate.yaml"
    payload = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    payload["paths"][-1] = dict(payload["paths"][0])
    duplicate_policy.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    code, result = _run_checker(tracked_ignored_repo, duplicate_policy)
    assert code == 1
    assert "duplicate" in result["errors"][0]["detail"]

    code, result = _run_checker(tmp_path / "not-a-repo")
    assert code == 1
    assert result["errors"][0]["code"] == "check-failed"


@pytest.mark.parametrize("content", ["[]\n", "null\n"])
def test_non_mapping_policy_roots_fail_with_controlled_errors(tracked_ignored_repo, tmp_path, content):
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text(content, encoding="utf-8")

    code, result = _run_checker(tracked_ignored_repo, malformed)
    assert code == 1
    assert result["errors"] == [{"code": "check-failed", "detail": "tracked-ignore policy root must be a mapping"}]
    with pytest.raises(migration.MigrationError, match="root must be a mapping"):
        migration.capture(tracked_ignored_repo, tmp_path / "journal", malformed)


def test_transition_cli_uses_shared_strict_pair_parser(tracked_ignored_repo, tmp_path, capsys):
    transition = tmp_path / "target-transition.json"
    package = tmp_path / "target-package.json"
    transition.write_text(
        '{"schema_version":1,"phase":"untrack-v1","release_version":"2.0.0"}\n',
        encoding="utf-8",
    )
    package.write_text('{"version":"2.0.0"}\n', encoding="utf-8")

    assert migration.main(
        [
            "transition",
            "--repo",
            str(tracked_ignored_repo),
            "--transition",
            str(transition),
            "--package",
            str(package),
        ]
    ) == 0
    assert capsys.readouterr().out == "untrack-v1\n"

    package.write_text('{"version":"2.0.0","version":"2.0.0"}\n', encoding="utf-8")
    assert migration.main(
        [
            "transition",
            "--repo",
            str(tracked_ignored_repo),
            "--transition",
            str(transition),
            "--package",
            str(package),
        ]
    ) == 1
    assert "duplicate local-only preservation transition key: version" in capsys.readouterr().out

    package.write_text('{"version":"2.0.1"}\n', encoding="utf-8")
    assert migration.main(
        [
            "transition",
            "--repo",
            str(tracked_ignored_repo),
            "--transition",
            str(transition),
            "--package",
            str(package),
        ]
    ) == 1
    assert "version does not match package metadata" in capsys.readouterr().out


def test_nested_ignore_negation_case_and_unicode_remain_exact(tracked_ignored_repo):
    _git(tracked_ignored_repo, "rm", "--cached", "--", *migration.LOCAL_ONLY_PATHS)
    _set_transition(tracked_ignored_repo, "untrack-v1")
    nested = tracked_ignored_repo / "00-Inbox" / ".gitignore"
    nested.write_text("!README.md\n", encoding="utf-8")
    _git(tracked_ignored_repo, "add", "-f", "00-Inbox/.gitignore")
    _git(tracked_ignored_repo, "commit", "-qm", "nested negation")

    _, result = _run_checker(tracked_ignored_repo)
    assert result["errors"] == [
        {
            "code": "stale-policy-row",
            "paths": [
                "00-Inbox/Daily_Plans/README.md",
                "00-Inbox/Ideas/README.md",
                "00-Inbox/Meetings/README.md",
                "00-Inbox/README.md",
            ],
        }
    ]

    nested.write_text(
        "Daily_Plans/README.md\nIdeas/README.md\nMeetings/README.md\nREADME.md\n",
        encoding="utf-8",
    )
    _git(tracked_ignored_repo, "add", "00-Inbox/.gitignore")
    assert _run_checker(tracked_ignored_repo)[0] == 0


def test_migration_preserves_modified_deleted_and_modes_then_rewinds_current_copy(tracked_ignored_repo, tmp_path):
    first, second, third = migration.LOCAL_ONLY_PATHS
    modified = tracked_ignored_repo / first
    deleted = tracked_ignored_repo / second
    later_modified = tracked_ignored_repo / third
    modified.write_bytes(b"locally modified\r\nbytes\x00")
    modified.chmod(0o600)
    deleted.unlink()
    later_modified.chmod(0o640)
    expected_modified = modified.read_bytes()
    journal = tmp_path / "journal"

    _prepare_untrack(tracked_ignored_repo, journal)
    result = migration.apply(tracked_ignored_repo, journal)

    assert result["phase"] == "applied"
    assert modified.read_bytes() == expected_modified
    assert stat.S_IMODE(modified.stat().st_mode) == 0o600
    assert not deleted.exists()
    assert stat.S_IMODE(later_modified.stat().st_mode) == 0o640
    assert set(migration._query_tracked_ignored(tracked_ignored_repo)) == {
        row["path"] for row in _policy_rows() if row["classification"] != "local-only-must-be-untracked"
    }
    journal_payload = json.loads((journal / migration.MANIFEST_NAME).read_text())
    assert [entry["worktree"]["state"] for entry in journal_payload["entries"]] == [
        "present",
        "deleted",
        "present",
    ]

    deleted.write_bytes(b"created after migration\n")
    later_modified.write_bytes(b"newest local slack state\n")
    later_modified.chmod(0o600)
    rewind_expected = {
        relative: (
            (tracked_ignored_repo / relative).read_bytes(),
            stat.S_IMODE((tracked_ignored_repo / relative).stat().st_mode),
        )
        for relative in migration.LOCAL_ONLY_PATHS
    }

    rewound = _rewind(tracked_ignored_repo, journal)

    assert rewound["phase"] == "rewound"
    assert set(migration._query_tracked_ignored(tracked_ignored_repo)) == {row["path"] for row in _policy_rows()}
    assert {
        relative: (
            (tracked_ignored_repo / relative).read_bytes(),
            stat.S_IMODE((tracked_ignored_repo / relative).stat().st_mode),
        )
        for relative in migration.LOCAL_ONLY_PATHS
    } == rewind_expected


def test_migration_recovers_interruption_after_one_exact_index_removal(tracked_ignored_repo, tmp_path, monkeypatch):
    journal = tmp_path / "journal"
    _prepare_untrack(tracked_ignored_repo, journal)
    original_git = migration._git
    interrupted = False

    def interrupt_after_mutation(repo, *arguments, **kwargs):
        nonlocal interrupted
        result = original_git(repo, *arguments, **kwargs)
        if not interrupted and arguments[:2] == ("update-index", "--force-remove"):
            interrupted = True
            raise migration.MigrationError("simulated interruption")
        return result

    monkeypatch.setattr(migration, "_git", interrupt_after_mutation)
    with pytest.raises(migration.MigrationError, match="simulated interruption"):
        migration.apply(tracked_ignored_repo, journal)

    monkeypatch.setattr(migration, "_git", original_git)
    assert migration.apply(tracked_ignored_repo, journal)["phase"] == "applied"
    assert _run_checker(tracked_ignored_repo)[0] == 0


@pytest.mark.parametrize(
    "tamper",
    [
        lambda payload: payload["entries"][0].__setitem__("path", "../outside"),
        lambda payload: payload["entries"][0].__setitem__("path", "/absolute"),
        lambda payload: payload["entries"][0].__setitem__("path", "System/pillars.yaml"),
        lambda payload: payload["entries"].reverse(),
        lambda payload: payload["entries"].__setitem__(1, dict(payload["entries"][0])),
        lambda payload: payload["entries"].pop(),
        lambda payload: payload["entries"][0]["worktree"].__setitem__("payload", "../../outside"),
    ],
    ids=("traversal", "absolute", "other-seed", "reordered", "duplicate", "missing", "payload-name"),
)
def test_journal_identity_tampering_fails_before_git_or_repo_file_access(
    tracked_ignored_repo, tmp_path, monkeypatch, tamper
):
    journal = tmp_path / "journal"
    migration.capture(tracked_ignored_repo, journal)
    payload = _journal_payload(journal)
    tamper(payload)
    _write_journal_payload(journal, payload)

    monkeypatch.setattr(migration, "_load_policy", lambda *_args, **_kwargs: pytest.fail("policy accessed"))
    monkeypatch.setattr(migration, "_query_tracked_ignored", lambda *_args: pytest.fail("Git accessed"))
    with pytest.raises(migration.MigrationError, match="journal"):
        migration.apply(tracked_ignored_repo, journal)


def test_journal_identity_validation_guard_removal_mutation_loses_rejection(
    tracked_ignored_repo, tmp_path, monkeypatch
):
    journal = tmp_path / "journal"
    migration.capture(tracked_ignored_repo, journal)
    payload = _journal_payload(journal)
    payload["entries"][0]["path"] = "../outside"
    _write_journal_payload(journal, payload)
    with pytest.raises(migration.MigrationError, match="identities"):
        migration._read_journal(journal)

    monkeypatch.setattr(migration, "_validate_journal", lambda value: value)
    assert migration._read_journal(journal)["entries"][0]["path"] == "../outside"


def test_journal_rejects_duplicate_json_keys(tracked_ignored_repo, tmp_path):
    journal = tmp_path / "journal"
    migration.capture(tracked_ignored_repo, journal)
    journal_path = journal / migration.MANIFEST_NAME
    source = journal_path.read_text(encoding="utf-8")
    journal_path.write_text(source.replace('{\n  "entries"', '{\n  "phase": "applied",\n  "entries"'), encoding="utf-8")

    with pytest.raises(migration.MigrationError, match="duplicate preservation journal key: phase"):
        migration._read_journal(journal)


@pytest.mark.parametrize("tamper", ["payload-bytes", "payload-missing", "payload-extra", "payload-mode"])
def test_storage_tamper_fails_before_policy_or_any_git_command(
    tracked_ignored_repo, tmp_path, monkeypatch, tamper
):
    journal = tmp_path / "journal"
    migration.capture(tracked_ignored_repo, journal)
    payload = journal / "payloads" / "apply-0.bin"
    if tamper == "payload-bytes":
        data = payload.read_bytes()
        payload.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    elif tamper == "payload-missing":
        payload.unlink()
    elif tamper == "payload-extra":
        extra = journal / "payloads" / "unexpected.bin"
        extra.write_bytes(b"unexpected")
        extra.chmod(0o600)
    else:
        payload.chmod(0o644)

    git_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        migration,
        "_git",
        lambda _repo, *arguments, **_kwargs: git_calls.append(arguments),
    )
    monkeypatch.setattr(migration, "_load_policy", lambda *_args, **_kwargs: pytest.fail("policy accessed"))
    with pytest.raises(migration.MigrationError, match="preservation (payload|storage)"):
        migration.apply(tracked_ignored_repo, journal)
    assert git_calls == []


def test_symlinked_journal_root_fails_before_policy_or_git(tracked_ignored_repo, tmp_path, monkeypatch):
    journal = tmp_path / "journal"
    migration.capture(tracked_ignored_repo, journal)
    real = tmp_path / "real-journal"
    journal.rename(real)
    journal.symlink_to(real, target_is_directory=True)

    monkeypatch.setattr(migration, "_load_policy", lambda *_args, **_kwargs: pytest.fail("policy accessed"))
    monkeypatch.setattr(migration, "_git", lambda *_args, **_kwargs: pytest.fail("Git accessed"))
    with pytest.raises(migration.MigrationError, match="invalid type"):
        migration.apply(tracked_ignored_repo, journal)


@pytest.mark.parametrize("symlink_part", ["root", "parent", "payloads"])
def test_cli_rejects_journal_symlinks_before_policy_or_git(
    tracked_ignored_repo, tmp_path, monkeypatch, capsys, symlink_part
):
    parent = tmp_path / "private-parent"
    parent.mkdir(mode=0o700)
    journal = parent / "journal"
    migration.capture(tracked_ignored_repo, journal)
    _set_transition(tracked_ignored_repo, "untrack-v1")
    if symlink_part == "root":
        real = parent / "real-journal"
        journal.rename(real)
        journal.symlink_to(real, target_is_directory=True)
    elif symlink_part == "parent":
        real = tmp_path / "real-parent"
        parent.rename(real)
        parent.symlink_to(real, target_is_directory=True)
    else:
        payloads = journal / "payloads"
        real = journal / "real-payloads"
        payloads.rename(real)
        payloads.symlink_to(real, target_is_directory=True)

    monkeypatch.setattr(migration, "_load_policy", lambda *_args, **_kwargs: pytest.fail("policy accessed"))
    monkeypatch.setattr(migration, "_query_tracked_ignored", lambda *_args: pytest.fail("Git queried"))
    monkeypatch.setattr(migration, "_git", lambda *_args, **_kwargs: pytest.fail("Git mutated"))

    assert migration.main(
        ["apply", "--repo", str(tracked_ignored_repo), "--journal", str(journal)]
    ) == 1
    assert "preservation storage" in capsys.readouterr().out


def test_closed_rewound_journal_recaptures_to_opaque_archive(tracked_ignored_repo, tmp_path):
    journal = tmp_path / "journal"
    _prepare_untrack(tracked_ignored_repo, journal)
    migration.apply(tracked_ignored_repo, journal)
    _rewind(tracked_ignored_repo, journal)

    recaptured = migration.capture(tracked_ignored_repo, journal)

    assert recaptured["phase"] == "captured"
    archives = [path for path in tmp_path.iterdir() if path.name.startswith("archive-")]
    assert len(archives) == 1
    assert len(archives[0].name) == len("archive-") + 32
    assert _journal_payload(archives[0])["phase"] == "rewound"


def test_initial_capture_interruption_never_publishes_incomplete_generation(
    tracked_ignored_repo, tmp_path, monkeypatch
):
    journal = tmp_path / "journal"
    original_snapshot = migration._snapshot_worktree
    snapshots = 0

    def interrupt_generation(repo, relative, payload):
        nonlocal snapshots
        result = original_snapshot(repo, relative, payload)
        snapshots += 1
        if snapshots == 2:
            raise migration.MigrationError("simulated initial generation interruption")
        return result

    monkeypatch.setattr(migration, "_snapshot_worktree", interrupt_generation)
    with pytest.raises(migration.MigrationError, match="initial generation interruption"):
        migration.capture(tracked_ignored_repo, journal)
    assert not journal.exists()

    monkeypatch.setattr(migration, "_snapshot_worktree", original_snapshot)
    assert migration.capture(tracked_ignored_repo, journal)["phase"] == "captured"
    assert migration._read_journal(journal)["phase"] == "captured"


def test_recapture_build_interruption_retains_rewound_generation(
    tracked_ignored_repo, tmp_path, monkeypatch
):
    journal = tmp_path / "journal"
    _prepare_untrack(tracked_ignored_repo, journal)
    migration.apply(tracked_ignored_repo, journal)
    _rewind(tracked_ignored_repo, journal)
    original_snapshot = migration._snapshot_worktree

    def interrupt_generation(repo, relative, payload):
        original_snapshot(repo, relative, payload)
        raise migration.MigrationError("simulated recapture generation interruption")

    monkeypatch.setattr(migration, "_snapshot_worktree", interrupt_generation)
    with pytest.raises(migration.MigrationError, match="recapture generation interruption"):
        migration.capture(tracked_ignored_repo, journal)

    assert migration._read_journal(journal)["phase"] == "rewound"
    assert not list(tmp_path.glob("archive-*"))


def test_recapture_publish_failure_restores_old_generation(tracked_ignored_repo, tmp_path, monkeypatch):
    journal = tmp_path / "journal"
    _prepare_untrack(tracked_ignored_repo, journal)
    migration.apply(tracked_ignored_repo, journal)
    _rewind(tracked_ignored_repo, journal)
    original_replace = migration.os.replace
    interrupted = False

    def interrupt_publish(source, destination):
        nonlocal interrupted
        if not interrupted and Path(source).name.startswith(".journal-generation-") and Path(destination) == journal:
            interrupted = True
            raise OSError("simulated atomic publish interruption")
        return original_replace(source, destination)

    monkeypatch.setattr(migration.os, "replace", interrupt_publish)
    with pytest.raises(OSError, match="atomic publish interruption"):
        migration.capture(tracked_ignored_repo, journal)

    assert migration._read_journal(journal)["phase"] == "rewound"
    assert not list(tmp_path.glob("archive-*"))


def test_recapture_retries_after_kill_between_archive_and_generation_publish(tracked_ignored_repo, tmp_path):
    journal = tmp_path / "journal"
    _prepare_untrack(tracked_ignored_repo, journal)
    migration.apply(tracked_ignored_repo, journal)
    _rewind(tracked_ignored_repo, journal)
    _, _, policy_hash = migration._load_policy(tracked_ignored_repo)
    generation, _ = migration._create_journal_generation(
        tracked_ignored_repo,
        journal,
        policy_hash,
        VERSION,
    )
    archive = tmp_path / "archive-00000000000000000000000000000000"
    migration._write_publication_intent(journal, generation, archive)

    # Exact on-disk state left by a kill after retaining the old generation but
    # before the validated replacement generation reaches the canonical path.
    os.replace(journal, archive)
    assert not journal.exists()
    assert migration._read_journal(generation)["phase"] == "captured"

    assert migration.capture(tracked_ignored_repo, journal)["phase"] == "captured"
    assert migration._read_journal(journal)["phase"] == "captured"
    assert migration._read_journal(archive)["phase"] == "rewound"


def test_capture_rewind_recovers_process_death_between_publication_renames(
    tracked_ignored_repo, tmp_path
):
    journal = tmp_path / "journal"
    _prepare_untrack(tracked_ignored_repo, journal)
    migration.apply(tracked_ignored_repo, journal)
    first = tracked_ignored_repo / migration.LOCAL_ONLY_PATHS[0]
    first.write_bytes(b"captured before process death\n")
    prior = migration._read_journal(journal)
    generation, replacement = migration._create_rewind_generation(tracked_ignored_repo, journal, prior)
    archive = tmp_path / "archive-11111111111111111111111111111111"
    migration._write_publication_intent(journal, generation, archive)

    # Exact durable state after SIGKILL/power loss between canonical -> archive
    # and validated generation -> canonical.
    os.replace(journal, archive)
    assert not journal.exists()
    assert migration._read_journal(archive) == prior
    assert migration._read_journal(generation) == replacement

    recovered = migration.capture_rewind(tracked_ignored_repo, journal)

    assert recovered["phase"] == "rewind-captured"
    assert migration._read_journal(journal) == recovered
    assert migration._read_journal(archive) == prior
    assert not migration._publication_intent_path(journal).exists()


def test_capture_rewind_retries_atomic_generation_after_present_to_deleted_change(
    tracked_ignored_repo, tmp_path, monkeypatch
):
    journal = tmp_path / "journal"
    _prepare_untrack(tracked_ignored_repo, journal)
    migration.apply(tracked_ignored_repo, journal)
    expected = {}
    for ordinal, relative in enumerate(migration.LOCAL_ONLY_PATHS):
        target = tracked_ignored_repo / relative
        target.write_bytes(f"post-update-{ordinal}\n".encode())
        target.chmod(0o600 + ordinal)
        expected[relative] = (target.read_bytes(), stat.S_IMODE(target.stat().st_mode))

    original_snapshot = migration._snapshot_worktree
    snapshots = 0

    def interrupt_pending_rewind(repo, relative, payload):
        nonlocal snapshots
        result = original_snapshot(repo, relative, payload)
        snapshots += 1
        if snapshots == 2:
            raise migration.MigrationError("simulated rewind capture interruption")
        return result

    monkeypatch.setattr(migration, "_snapshot_worktree", interrupt_pending_rewind)
    with pytest.raises(migration.MigrationError, match="rewind capture interruption"):
        migration.capture_rewind(tracked_ignored_repo, journal)
    assert migration._read_journal(journal)["phase"] == "applied"

    first = tracked_ignored_repo / migration.LOCAL_ONLY_PATHS[0]
    first.unlink()
    expected.pop(migration.LOCAL_ONLY_PATHS[0])

    monkeypatch.setattr(migration, "_snapshot_worktree", original_snapshot)
    captured = migration.capture_rewind(tracked_ignored_repo, journal)
    assert captured["phase"] == "rewind-captured"
    assert captured["rewind_worktree"][0] == {"state": "absent"}
    assert migration._read_journal(journal) == captured
    _set_transition(tracked_ignored_repo, "bootstrap-v1")
    assert migration.rewind(tracked_ignored_repo, journal)["phase"] == "rewound"
    assert not first.exists()
    assert {
        relative: (
            (tracked_ignored_repo / relative).read_bytes(),
            stat.S_IMODE((tracked_ignored_repo / relative).stat().st_mode),
        )
        for relative in expected
    } == expected


def test_rewind_recapture_interruption_keeps_prior_generation_readable_and_retryable(
    tracked_ignored_repo, tmp_path, monkeypatch
):
    journal = tmp_path / "journal"
    _prepare_untrack(tracked_ignored_repo, journal)
    migration.apply(tracked_ignored_repo, journal)
    first = tracked_ignored_repo / migration.LOCAL_ONLY_PATHS[0]
    first.write_bytes(b"first rewind generation\n")
    prior = migration.capture_rewind(tracked_ignored_repo, journal)
    prior_payload = migration._rewind_payload_path(journal, 0).read_bytes()
    first.write_bytes(b"second rewind generation\n")
    original_snapshot = migration._snapshot_worktree

    def interrupt_recapture(repo, relative, payload):
        original_snapshot(repo, relative, payload)
        raise migration.MigrationError("simulated rewind recapture interruption")

    monkeypatch.setattr(migration, "_snapshot_worktree", interrupt_recapture)
    with pytest.raises(migration.MigrationError, match="rewind recapture interruption"):
        migration.capture_rewind(tracked_ignored_repo, journal)

    assert migration._read_journal(journal) == prior
    assert migration._rewind_payload_path(journal, 0).read_bytes() == prior_payload

    monkeypatch.setattr(migration, "_snapshot_worktree", original_snapshot)
    replacement = migration.capture_rewind(tracked_ignored_repo, journal)
    assert replacement["phase"] == "rewind-captured"
    assert migration._rewind_payload_path(journal, 0).read_bytes() == b"second rewind generation\n"
    assert migration._read_journal(journal) == replacement


def test_rewind_recapture_publish_failure_restores_prior_generation(
    tracked_ignored_repo, tmp_path, monkeypatch
):
    journal = tmp_path / "journal"
    _prepare_untrack(tracked_ignored_repo, journal)
    migration.apply(tracked_ignored_repo, journal)
    prior = migration.capture_rewind(tracked_ignored_repo, journal)
    first = tracked_ignored_repo / migration.LOCAL_ONLY_PATHS[0]
    first.write_bytes(b"replacement rewind bytes\n")
    original_replace = migration.os.replace
    interrupted = False

    def interrupt_publish(source, destination):
        nonlocal interrupted
        if not interrupted and Path(source).name.startswith(".journal-generation-") and Path(destination) == journal:
            interrupted = True
            raise OSError("simulated rewind generation publish failure")
        return original_replace(source, destination)

    monkeypatch.setattr(migration.os, "replace", interrupt_publish)
    with pytest.raises(OSError, match="rewind generation publish failure"):
        migration.capture_rewind(tracked_ignored_repo, journal)

    assert migration._read_journal(journal) == prior


def test_bootstrap_apply_is_non_mutating_and_reports_installed_state(tracked_ignored_repo, tmp_path):
    journal = tmp_path / "journal"
    migration.capture(tracked_ignored_repo, journal)
    before = _git(tracked_ignored_repo, "ls-files", "--stage").stdout

    with pytest.raises(migration.MigrationError, match="bootstrap remains tracked"):
        migration.apply(tracked_ignored_repo, journal)

    assert _git(tracked_ignored_repo, "ls-files", "--stage").stdout == before
    assert migration.preview(tracked_ignored_repo) == {
        "ok": True,
        "state": "bootstrap-installed",
        "actual_count": 27,
    }


def test_update_journey_capture_before_release_restores_files_removed_by_release(tracked_ignored_repo, tmp_path):
    first, second, third = migration.LOCAL_ONLY_PATHS
    (tracked_ignored_repo / first).write_bytes(b"current session learning\n")
    (tracked_ignored_repo / first).chmod(0o600)
    (tracked_ignored_repo / second).unlink()
    (tracked_ignored_repo / third).write_bytes(b"current slack preferences\n")
    expected = {
        first: (b"current session learning\n", 0o600),
        third: (b"current slack preferences\n", 0o644),
    }
    journal = tmp_path / "update-journal"

    assert migration.capture(tracked_ignored_repo, journal)["phase"] == "captured"
    _git(tracked_ignored_repo, "rm", "--cached", "--", *migration.LOCAL_ONLY_PATHS)
    _set_transition(tracked_ignored_repo, "untrack-v1")
    (tracked_ignored_repo / first).unlink()
    (tracked_ignored_repo / third).unlink()

    assert migration.apply(tracked_ignored_repo, journal)["phase"] == "applied"
    assert not (tracked_ignored_repo / second).exists()
    assert {
        relative: (
            (tracked_ignored_repo / relative).read_bytes(),
            stat.S_IMODE((tracked_ignored_repo / relative).stat().st_mode),
        )
        for relative in (first, third)
    } == expected


def test_real_fast_forward_and_rollback_preserve_local_only_bytes_modes_and_deletions(tracked_ignored_repo, tmp_path):
    first, second, third = migration.LOCAL_ONLY_PATHS
    first_target = tracked_ignored_repo / first
    second_target = tracked_ignored_repo / second
    third_target = tracked_ignored_repo / third
    first_target.write_bytes(b"private learning\r\nwith\x00bytes")
    third_target.write_bytes(b"private slack config\n")
    third_target.chmod(0o600)
    _git(tracked_ignored_repo, "add", "-f", "--", first, third)
    _git(tracked_ignored_repo, "commit", "-qm", "local base state")
    base = _git(tracked_ignored_repo, "rev-parse", "HEAD").stdout.strip()
    _git(tracked_ignored_repo, "rm", "--cached", "--", *migration.LOCAL_ONLY_PATHS)
    _set_transition(tracked_ignored_repo, "untrack-v1")
    _git(tracked_ignored_repo, "add", "--", TRANSITION.as_posix())
    _git(tracked_ignored_repo, "commit", "-qm", "release untracks local-only files")
    release = _git(tracked_ignored_repo, "rev-parse", "HEAD").stdout.strip()
    _git(tracked_ignored_repo, "reset", "--hard", base)
    third_target.chmod(0o600)
    second_target.unlink()
    expected = {
        first: (first_target.read_bytes(), 0o644),
        third: (third_target.read_bytes(), 0o600),
    }
    journal = tmp_path / "journal"

    migration.capture(tracked_ignored_repo, journal)
    _git(tracked_ignored_repo, "merge", "--ff-only", release)
    migration.apply(tracked_ignored_repo, journal)

    assert not second_target.exists()
    assert {
        relative: (
            (tracked_ignored_repo / relative).read_bytes(),
            stat.S_IMODE((tracked_ignored_repo / relative).stat().st_mode),
        )
        for relative in (first, third)
    } == expected

    first_target.write_bytes(b"newest post-update learning\n")
    third_target.write_bytes(b"newest post-update slack\n")
    third_target.chmod(0o600)
    migration.capture_rewind(tracked_ignored_repo, journal)
    _git(tracked_ignored_repo, "reset", "--hard", base)
    migration.rewind(tracked_ignored_repo, journal)

    assert first_target.read_bytes() == b"newest post-update learning\n"
    assert not second_target.exists()
    assert third_target.read_bytes() == b"newest post-update slack\n"
    assert stat.S_IMODE(third_target.stat().st_mode) == 0o600


def test_migration_refuses_live_query_drift_without_broad_mutation(tracked_ignored_repo, tmp_path):
    unknown = tracked_ignored_repo / "System" / "unexpected-local.md"
    unknown.write_text("unknown\n", encoding="utf-8")
    with (tracked_ignored_repo / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("/System/unexpected-local.md\n")
    _git(tracked_ignored_repo, "add", "-f", "System/unexpected-local.md")
    before = _git(tracked_ignored_repo, "ls-files", "-s").stdout

    with pytest.raises(migration.MigrationError, match="differs from the exact 27-row baseline"):
        migration.capture(tracked_ignored_repo, tmp_path / "journal")

    assert _git(tracked_ignored_repo, "ls-files", "-s").stdout == before
    assert not (tmp_path / "journal").exists()


def test_rewind_restores_staged_index_identity_without_overwriting_newer_worktree_bytes(tracked_ignored_repo, tmp_path):
    relative = migration.LOCAL_ONLY_PATHS[0]
    target = tracked_ignored_repo / relative
    target.write_bytes(b"staged local version\n")
    _git(tracked_ignored_repo, "add", "-f", "--", relative)
    staged_entry = _git(tracked_ignored_repo, "ls-files", "-s", "--", relative).stdout
    target.write_bytes(b"newer unstaged local version\n")
    journal = tmp_path / "journal"

    _prepare_untrack(tracked_ignored_repo, journal)
    migration.apply(tracked_ignored_repo, journal)
    _rewind(tracked_ignored_repo, journal)

    assert _git(tracked_ignored_repo, "ls-files", "-s", "--", relative).stdout == staged_entry
    assert target.read_bytes() == b"newer unstaged local version\n"


@pytest.mark.parametrize("index_state", ["regular-staged", "intent-to-add", "assume-unchanged", "skip-worktree"])
def test_rewind_restores_exact_index_flags_and_cached_diff(tracked_ignored_repo, tmp_path, index_state):
    relative = migration.LOCAL_ONLY_PATHS[0]
    target = tracked_ignored_repo / relative
    if index_state == "regular-staged":
        target.write_bytes(b"staged identity\n")
        _git(tracked_ignored_repo, "add", "-f", "--", relative)
    elif index_state == "intent-to-add":
        _git(tracked_ignored_repo, "rm", "--cached", "--", relative)
        _git(tracked_ignored_repo, "add", "-f", "--intent-to-add", "--", relative)
    elif index_state == "assume-unchanged":
        _git(tracked_ignored_repo, "update-index", "--assume-unchanged", "--", relative)
    else:
        _git(tracked_ignored_repo, "update-index", "--skip-worktree", "--", relative)
    before = _index_evidence(tracked_ignored_repo, relative)
    journal = tmp_path / "journal"

    _prepare_untrack(tracked_ignored_repo, journal)
    migration.apply(tracked_ignored_repo, journal)
    _rewind(tracked_ignored_repo, journal)

    assert _index_evidence(tracked_ignored_repo, relative) == before


def test_interrupted_intent_and_flag_restore_resumes_exactly(tracked_ignored_repo, tmp_path, monkeypatch):
    relative = migration.LOCAL_ONLY_PATHS[0]
    _git(tracked_ignored_repo, "rm", "--cached", "--", relative)
    _git(tracked_ignored_repo, "add", "-f", "--intent-to-add", "--", relative)
    _git(tracked_ignored_repo, "update-index", "--skip-worktree", "--", relative)
    _git(tracked_ignored_repo, "update-index", "--assume-unchanged", "--", relative)
    before = _index_evidence(tracked_ignored_repo, relative)
    journal = tmp_path / "journal"
    _prepare_untrack(tracked_ignored_repo, journal)
    migration.apply(tracked_ignored_repo, journal)
    _set_transition(tracked_ignored_repo, "bootstrap-v1")
    original_git = migration._git
    interrupted = False

    def interrupt_after_intent(repo, *arguments, **kwargs):
        nonlocal interrupted
        result = original_git(repo, *arguments, **kwargs)
        if not interrupted and arguments[:3] == ("add", "-f", "--intent-to-add"):
            interrupted = True
            raise migration.MigrationError("simulated flag restore interruption")
        return result

    monkeypatch.setattr(migration, "_git", interrupt_after_intent)
    with pytest.raises(migration.MigrationError, match="flag restore interruption"):
        migration.rewind(tracked_ignored_repo, journal)
    monkeypatch.setattr(migration, "_git", original_git)

    assert migration.rewind(tracked_ignored_repo, journal)["phase"] == "rewound"
    assert _index_evidence(tracked_ignored_repo, relative) == before


@pytest.mark.parametrize("fail_after", [1, 2, 3])
def test_interrupted_rewind_derives_exact_progress_from_live_index(
    tracked_ignored_repo, tmp_path, monkeypatch, fail_after
):
    journal = tmp_path / "journal"
    _prepare_untrack(tracked_ignored_repo, journal)
    migration.apply(tracked_ignored_repo, journal)
    _set_transition(tracked_ignored_repo, "bootstrap-v1")
    original_git = migration._git
    restores = 0

    def interrupt_after_restore(repo, *arguments, **kwargs):
        nonlocal restores
        result = original_git(repo, *arguments, **kwargs)
        if arguments[:2] == ("update-index", "--add"):
            restores += 1
            if restores == fail_after:
                raise migration.MigrationError("simulated rewind interruption")
        return result

    monkeypatch.setattr(migration, "_git", interrupt_after_restore)
    with pytest.raises(migration.MigrationError, match="rewind interruption"):
        migration.rewind(tracked_ignored_repo, journal)
    monkeypatch.setattr(migration, "_git", original_git)

    assert migration.rewind(tracked_ignored_repo, journal)["phase"] == "rewound"
    assert migration._query_tracked_ignored(tracked_ignored_repo) == {row["path"] for row in _policy_rows()}


def test_rewind_resumes_when_all_index_restores_precede_final_journal_write(
    tracked_ignored_repo, tmp_path, monkeypatch
):
    journal = tmp_path / "journal"
    _prepare_untrack(tracked_ignored_repo, journal)
    migration.apply(tracked_ignored_repo, journal)
    _set_transition(tracked_ignored_repo, "bootstrap-v1")
    original_write = migration._write_journal
    failed = False

    def interrupt_final_write(journal_dir, payload):
        nonlocal failed
        if payload["phase"] == "rewound" and not failed:
            failed = True
            raise migration.MigrationError("simulated final journal interruption")
        return original_write(journal_dir, payload)

    monkeypatch.setattr(migration, "_write_journal", interrupt_final_write)
    with pytest.raises(migration.MigrationError, match="final journal interruption"):
        migration.rewind(tracked_ignored_repo, journal)
    monkeypatch.setattr(migration, "_write_journal", original_write)

    assert migration.rewind(tracked_ignored_repo, journal)["phase"] == "rewound"


def test_preview_recognizes_absent_files_after_exact_migration(tracked_ignored_repo, tmp_path):
    journal = tmp_path / "journal"
    _prepare_untrack(tracked_ignored_repo, journal)
    migration.apply(tracked_ignored_repo, journal)
    for relative in migration.LOCAL_ONLY_PATHS:
        (tracked_ignored_repo / relative).unlink()

    assert migration.preview(tracked_ignored_repo) == {
        "ok": True,
        "state": "already-applied",
        "actual_count": 24,
    }


def test_checker_and_migration_ignore_hostile_git_environment(tracked_ignored_repo, tmp_path, monkeypatch):
    hostile = tmp_path / "hostile"
    hostile.mkdir()
    _git(hostile, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(hostile / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(hostile))
    monkeypatch.setenv("GIT_INDEX_FILE", str(hostile / ".git" / "hostile-index"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(hostile / "hooks"))
    excludes = tmp_path / "hostile-excludes"
    excludes.write_text("*\n", encoding="utf-8")
    _git(tracked_ignored_repo, "config", "core.excludesFile", str(excludes))
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", f"'core.excludesFile={excludes}'")

    assert len(checker.query_tracked_ignored(tracked_ignored_repo)) == 27
    journal = tmp_path / "journal"
    _prepare_untrack(tracked_ignored_repo, journal)
    assert migration.apply(tracked_ignored_repo, journal)["phase"] == "applied"
    assert not (hostile / ".git" / "hostile-index").exists()
    assert "GIT_CONFIG_PARAMETERS" not in checker.query_tracked_ignored.__globals__["sanitized_git_env"]()
