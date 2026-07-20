from __future__ import annotations

from pathlib import Path

import pytest

from core.migrations import preserve_local_only_paths as preservation
from core.migrations.migrate_v1_to_v2 import rollback_migration, run_migration
from core.utils.tracked_ignored import FUTURE_LOCAL_ONLY_PATHS, LOCAL_ONLY_PATHS


def _seed_vault(root: Path) -> None:
    (root / "03-Tasks").mkdir(parents=True, exist_ok=True)
    (root / "03-Tasks/Tasks.md").write_text("# Tasks\n", encoding="utf-8")
    (root / "04-Projects").mkdir(parents=True, exist_ok=True)
    (root / "04-Projects/Alpha.md").write_text("Ref: 03-Tasks/Tasks.md\n", encoding="utf-8")
    (root / "System").mkdir(parents=True, exist_ok=True)


def test_migration_dry_run_does_not_modify_files(tmp_path: Path):
    _seed_vault(tmp_path)
    before = (tmp_path / "04-Projects/Alpha.md").read_text(encoding="utf-8")

    result = run_migration(tmp_path, dry_run=True)

    assert result.moved_dir is True
    assert "04-Projects/Alpha.md" in result.updated_files
    assert (tmp_path / "03-Tasks").exists()
    assert not (tmp_path / "03-Backlog").exists()
    assert (tmp_path / "04-Projects/Alpha.md").read_text(encoding="utf-8") == before


def test_migration_apply_then_rollback(tmp_path: Path):
    _seed_vault(tmp_path)

    applied = run_migration(tmp_path, dry_run=False)
    assert applied.moved_dir is True
    assert (tmp_path / "03-Backlog").exists()
    assert not (tmp_path / "03-Tasks").exists()
    assert "03-Backlog/Tasks.md" in (tmp_path / "04-Projects/Alpha.md").read_text(encoding="utf-8")
    assert applied.manifest_path.exists()

    rolled_back = rollback_migration(tmp_path)
    assert rolled_back.moved_dir is True
    assert (tmp_path / "03-Tasks").exists()
    assert not (tmp_path / "03-Backlog").exists()
    assert "03-Tasks/Tasks.md" in (tmp_path / "04-Projects/Alpha.md").read_text(encoding="utf-8")


def _preservation_journal(schema_version: int, paths: tuple[str, ...]) -> dict:
    return {
        "schema_version": schema_version,
        "policy_sha256": "a" * 64,
        "source_transition": {
            "phase": f"bootstrap-v{schema_version}",
            "release_version": "1.62.0",
        },
        "phase": "captured",
        "entries": [
            {
                "path": path,
                "index": {
                    "tracked": True,
                    "mode": "100644",
                    "oid": "b" * 40,
                    "stage": 0,
                    "flags": "0",
                },
                "worktree": {"state": "absent"},
            }
            for path in paths
        ],
        "rewind_worktree": None,
    }


def test_preservation_journal_versions_keep_their_original_path_meaning() -> None:
    historical = _preservation_journal(1, LOCAL_ONLY_PATHS)
    future = _preservation_journal(2, FUTURE_LOCAL_ONLY_PATHS)

    assert [entry["path"] for entry in preservation._validate_journal(historical)["entries"]] == list(
        LOCAL_ONLY_PATHS
    )
    assert [entry["path"] for entry in preservation._validate_journal(future)["entries"]] == list(
        FUTURE_LOCAL_ONLY_PATHS
    )


def test_preservation_journal_schema_guard_is_red_when_removed() -> None:
    unsupported = _preservation_journal(3, FUTURE_LOCAL_ONLY_PATHS)

    with pytest.raises(preservation.MigrationError, match="journal schema or phase is unsupported"):
        preservation._validate_journal(unsupported)
