from __future__ import annotations

from pathlib import Path

from core.migrations.migrate_v1_to_v2 import rollback_migration, run_migration


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
