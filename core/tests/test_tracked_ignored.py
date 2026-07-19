"""Exact-policy and preservation tests for tracked-despite-ignored paths."""

from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from core.migrations import preserve_local_only_paths as migration

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "scripts" / "tracked-ignored-policy.yaml"
CHECKER = ROOT / "scripts" / "check-tracked-ignored.py"


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
    (repo / ".gitignore").write_text("\n".join(ignore_lines) + "\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", migration.POLICY_RELATIVE.as_posix())
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


def test_repository_policy_is_exact_23_seed_one_release_doc_three_local_only():
    rows = checker.load_policy(POLICY)
    by_class: dict[str, list[str]] = {}
    for row in rows:
        by_class.setdefault(row.classification, []).append(row.path)

    assert len(by_class["intentional-seed"]) == 23
    assert by_class["release-doc"] == [
        "System/Beta_Communications/2026-02-04_hardcoded_paths_fix.md"
    ]
    assert tuple(by_class["local-only-must-be-untracked"]) == migration.LOCAL_ONLY_PATHS


def test_checker_fails_until_only_the_exact_three_are_untracked(tracked_ignored_repo):
    before_code, before = _run_checker(tracked_ignored_repo)
    assert before_code == 1
    assert before["errors"] == [
        {
            "code": "local-only-still-tracked",
            "paths": sorted(migration.LOCAL_ONLY_PATHS),
        }
    ]

    original = {
        relative: (tracked_ignored_repo / relative).read_bytes()
        for relative in migration.LOCAL_ONLY_PATHS
    }
    _git(tracked_ignored_repo, "rm", "--cached", "--", *migration.LOCAL_ONLY_PATHS)

    after_code, after = _run_checker(tracked_ignored_repo)
    assert after_code == 0
    assert after == {
        "actual_tracked_ignored": 24,
        "errors": [],
        "expected_tracked": 24,
        "ok": True,
        "policy_rows": 27,
    }
    assert {
        relative: (tracked_ignored_repo / relative).read_bytes()
        for relative in migration.LOCAL_ONLY_PATHS
    } == original


def test_checker_rejects_unknown_stale_duplicate_and_non_git_states(
    tracked_ignored_repo, tmp_path
):
    _git(tracked_ignored_repo, "rm", "--cached", "--", *migration.LOCAL_ONLY_PATHS)
    unknown = tracked_ignored_repo / "System" / "Session_Learnings" / "Case-É.md"
    unknown.write_text("unknown\n", encoding="utf-8")
    with (tracked_ignored_repo / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("/System/Session_Learnings/Case-É.md\n")
    _git(tracked_ignored_repo, "add", "-f", "--intent-to-add", str(unknown.relative_to(tracked_ignored_repo)))
    _, result = _run_checker(tracked_ignored_repo)
    assert result["errors"] == [
        {"code": "unknown-tracked-ignored", "paths": ["System/Session_Learnings/Case-É.md"]}
    ]

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


def test_nested_ignore_negation_case_and_unicode_remain_exact(tracked_ignored_repo):
    _git(tracked_ignored_repo, "rm", "--cached", "--", *migration.LOCAL_ONLY_PATHS)
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


def test_migration_preserves_modified_deleted_and_modes_then_rewinds_current_copy(
    tracked_ignored_repo, tmp_path
):
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

    result = migration.apply(tracked_ignored_repo, journal)

    assert result["phase"] == "applied"
    assert modified.read_bytes() == expected_modified
    assert stat.S_IMODE(modified.stat().st_mode) == 0o600
    assert not deleted.exists()
    assert stat.S_IMODE(later_modified.stat().st_mode) == 0o640
    assert set(migration._query_tracked_ignored(tracked_ignored_repo)) == {
        row["path"]
        for row in _policy_rows()
        if row["classification"] != "local-only-must-be-untracked"
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

    rewound = migration.rewind(tracked_ignored_repo, journal)

    assert rewound["phase"] == "rewound"
    assert set(migration._query_tracked_ignored(tracked_ignored_repo)) == {
        row["path"] for row in _policy_rows()
    }
    assert {
        relative: (
            (tracked_ignored_repo / relative).read_bytes(),
            stat.S_IMODE((tracked_ignored_repo / relative).stat().st_mode),
        )
        for relative in migration.LOCAL_ONLY_PATHS
    } == rewind_expected


def test_migration_recovers_interruption_after_one_exact_index_removal(
    tracked_ignored_repo, tmp_path, monkeypatch
):
    journal = tmp_path / "journal"
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


def test_update_journey_capture_before_release_restores_files_removed_by_release(
    tracked_ignored_repo, tmp_path
):
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


def test_migration_refuses_live_query_drift_without_broad_mutation(
    tracked_ignored_repo, tmp_path
):
    unknown = tracked_ignored_repo / "System" / "unexpected-local.md"
    unknown.write_text("unknown\n", encoding="utf-8")
    with (tracked_ignored_repo / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("/System/unexpected-local.md\n")
    _git(tracked_ignored_repo, "add", "-f", "System/unexpected-local.md")
    before = _git(tracked_ignored_repo, "ls-files", "-s").stdout

    with pytest.raises(migration.MigrationError, match="differs from the exact 27-row baseline"):
        migration.apply(tracked_ignored_repo, tmp_path / "journal")

    assert _git(tracked_ignored_repo, "ls-files", "-s").stdout == before
    assert not (tmp_path / "journal").exists()


def test_rewind_restores_staged_index_identity_without_overwriting_newer_worktree_bytes(
    tracked_ignored_repo, tmp_path
):
    relative = migration.LOCAL_ONLY_PATHS[0]
    target = tracked_ignored_repo / relative
    target.write_bytes(b"staged local version\n")
    _git(tracked_ignored_repo, "add", "-f", "--", relative)
    staged_entry = _git(tracked_ignored_repo, "ls-files", "-s", "--", relative).stdout
    target.write_bytes(b"newer unstaged local version\n")
    journal = tmp_path / "journal"

    migration.apply(tracked_ignored_repo, journal)
    migration.rewind(tracked_ignored_repo, journal)

    assert _git(tracked_ignored_repo, "ls-files", "-s", "--", relative).stdout == staged_entry
    assert target.read_bytes() == b"newer unstaged local version\n"


def test_preview_recognizes_absent_files_after_exact_migration(tracked_ignored_repo, tmp_path):
    migration.apply(tracked_ignored_repo, tmp_path / "journal")
    for relative in migration.LOCAL_ONLY_PATHS:
        (tracked_ignored_repo / relative).unlink()

    assert migration.preview(tracked_ignored_repo) == {
        "ok": True,
        "state": "already-applied",
        "actual_count": 24,
    }


def test_checker_and_migration_ignore_hostile_git_environment(
    tracked_ignored_repo, tmp_path, monkeypatch
):
    hostile = tmp_path / "hostile"
    hostile.mkdir()
    _git(hostile, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(hostile / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(hostile))
    monkeypatch.setenv("GIT_INDEX_FILE", str(hostile / ".git" / "hostile-index"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(hostile / "hooks"))

    assert len(checker.query_tracked_ignored(tracked_ignored_repo)) == 27
    journal = tmp_path / "journal"
    assert migration.apply(tracked_ignored_repo, journal)["phase"] == "applied"
    assert not (hostile / ".git" / "hostile-index").exists()
