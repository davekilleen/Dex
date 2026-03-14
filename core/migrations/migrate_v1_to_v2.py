#!/usr/bin/env python3
"""Executable v1 -> v2 migration with rollback support.

Current transform:
- Rename `03-Tasks` -> `03-Backlog`
- Replace textual references in markdown/yaml files
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

FROM_DIR = "03-Tasks"
TO_DIR = "03-Backlog"
MANIFEST_REL = Path("System/.migration-manifest-v1-to-v2.json")
BACKUP_ROOT_REL = Path("System/.migration-backups/v1-to-v2")


@dataclass
class MigrationResult:
    moved_dir: bool
    updated_files: list[str]
    manifest_path: Path
    backup_root: Path


def _iter_text_files(vault_root: Path):
    ex = {".git", ".venv", "node_modules", ".pytest_cache", "__pycache__"}
    for path in vault_root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ex for part in path.parts):
            continue
        if path.suffix.lower() not in {".md", ".yaml", ".yml"}:
            continue
        if "System/.migration-backups" in path.as_posix():
            continue
        yield path


def _backup_file(vault_root: Path, src: Path, backup_root: Path) -> Path:
    rel = src.relative_to(vault_root)
    dest = backup_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def run_migration(vault_root: Path, dry_run: bool) -> MigrationResult:
    from_path = vault_root / FROM_DIR
    to_path = vault_root / TO_DIR
    manifest_path = vault_root / MANIFEST_REL
    backup_root = vault_root / BACKUP_ROOT_REL

    moved_dir = False
    updated_files: list[str] = []
    backup_map: dict[str, str] = {}

    if from_path.exists() and not to_path.exists():
        moved_dir = True
        if not dry_run:
            to_path.parent.mkdir(parents=True, exist_ok=True)
            from_path.rename(to_path)

    # Update references in text files.
    for text_file in _iter_text_files(vault_root):
        content = text_file.read_text(encoding="utf-8")
        if FROM_DIR not in content:
            continue
        updated_files.append(str(text_file.relative_to(vault_root)))
        if dry_run:
            continue
        backup = _backup_file(vault_root, text_file, backup_root)
        backup_map[str(text_file.relative_to(vault_root))] = str(backup.relative_to(vault_root))
        text_file.write_text(content.replace(FROM_DIR, TO_DIR), encoding="utf-8")

    if not dry_run:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "migration": "v1-to-v2",
            "timestamp": datetime.now(UTC).isoformat(),
            "from_dir": FROM_DIR,
            "to_dir": TO_DIR,
            "moved_dir": moved_dir,
            "updated_files": updated_files,
            "backup_map": backup_map,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return MigrationResult(
        moved_dir=moved_dir,
        updated_files=updated_files,
        manifest_path=manifest_path,
        backup_root=backup_root,
    )


def rollback_migration(vault_root: Path) -> MigrationResult:
    manifest_path = vault_root / MANIFEST_REL
    if not manifest_path.exists():
        raise FileNotFoundError(f"Migration manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    from_dir = manifest["from_dir"]
    to_dir = manifest["to_dir"]
    moved_dir = bool(manifest.get("moved_dir", False))
    updated_files = list(manifest.get("updated_files", []))
    backup_map = dict(manifest.get("backup_map", {}))

    if moved_dir:
        to_path = vault_root / to_dir
        from_path = vault_root / from_dir
        if to_path.exists() and not from_path.exists():
            to_path.rename(from_path)

    for rel_file in updated_files:
        backup_rel = backup_map.get(rel_file)
        if not backup_rel:
            continue
        backup_path = vault_root / backup_rel
        target = vault_root / rel_file
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_path, target)

    return MigrationResult(
        moved_dir=moved_dir,
        updated_files=updated_files,
        manifest_path=manifest_path,
        backup_root=vault_root / BACKUP_ROOT_REL,
    )


def _print_result(result: MigrationResult, action: str) -> None:
    print(f"{action} complete")
    print(f"  moved_dir: {result.moved_dir}")
    print(f"  updated_files: {len(result.updated_files)}")
    print(f"  manifest: {result.manifest_path}")
    print(f"  backup_root: {result.backup_root}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Dex v1->v2 migration runner")
    parser.add_argument("--vault-root", default=".", help="Vault root path")
    parser.add_argument("--dry-run", action="store_true", help="Preview migration without writing")
    parser.add_argument("--apply", action="store_true", help="Apply migration")
    parser.add_argument("--rollback", action="store_true", help="Rollback last migration")
    args = parser.parse_args()

    vault_root = Path(args.vault_root).resolve()
    if args.rollback:
        result = rollback_migration(vault_root)
        _print_result(result, "Rollback")
        return 0

    # Default mode is dry-run preview if no mode provided.
    dry_run = args.dry_run or not args.apply
    result = run_migration(vault_root, dry_run=dry_run)
    _print_result(result, "Dry-run" if dry_run else "Migration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
