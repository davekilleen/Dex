"""Resolve where a vault already keeps daily plans.

New vaults use ``00-Inbox/Daily_Plans``. An existing vault that already writes
dated daily plans somewhere else keeps that folder. Updates must not move those
files to the new default.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from core.paths import (
    ARCHIVES_DIR,
    DAILY_PLANS_DIR,
    INBOX_DIR,
    MEETINGS_DIR,
    SYSTEM_DIR,
    VAULT_ROOT,
)

# Vault-relative PARA roots derived from the canonical core.paths constants
# (POSIX strings, computed at import time). Using these instead of raw PARA
# path literals keeps the path-contract gate satisfied.
DEFAULT_DAILY_PLANS_RELATIVE = DAILY_PLANS_DIR.relative_to(VAULT_ROOT).as_posix()
FOLDER_MAP_RELATIVE = (SYSTEM_DIR / "folder-paths.yaml").relative_to(VAULT_ROOT).as_posix()
_MEETINGS_RELATIVE = MEETINGS_DIR.relative_to(VAULT_ROOT).as_posix()
DATED_DAILY_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
DAILY_PLAN_TYPE = re.compile(r"(?m)^type:\s*daily-plan\s*$")
DAILY_PLAN_HEADING = re.compile(r"(?im)^#\s+daily plan\b")
LEGACY_CANDIDATES = (
    (ARCHIVES_DIR / "Plans").relative_to(VAULT_ROOT).as_posix(),
    (INBOX_DIR / "Daily_Prep").relative_to(VAULT_ROOT).as_posix(),
)
PLAN_FOLDER_NAMES = frozenset(
    {
        "daily_plans",
        "daily-plans",
        "dailyplans",
        "daily_prep",
        "daily-prep",
        "dailyprep",
        "daily",
        "plans",
    }
)
SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".dex",
        ".claude",
        ".agents",
        ".scripts",
        ".cursor",
        "node_modules",
        "core",
        "packages",
        "scripts",
        "docs",
        "system",
        "meetings",
    }
)
MAX_WALK_DIRS = 400
MAX_PLAN_FILES = 200


def _normalize_relative(value: str) -> str | None:
    text = value.strip().strip("\"'").replace("\\", "/")
    if not text or text.startswith("#"):
        return None
    if text.startswith("/") or text.startswith("~") or ":" in text.split("/", 1)[0]:
        return None
    parts: list[str] = []
    for part in text.split("/"):
        if part in {"", "."}:
            continue
        if part == ".." or part.startswith("."):
            return None
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)


def _read_folder_map_daily_plans(vault_root: Path) -> str | None:
    path = vault_root / FOLDER_MAP_RELATIVE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        if key.strip() != "daily_plans":
            continue
        return _normalize_relative(raw_value.split(" #", 1)[0])
    return None


def _relative_to_vault(vault_root: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(vault_root.resolve()).as_posix()
    except (OSError, ValueError):
        return None


def _looks_like_daily_plan(path: Path, *, parent_name: str) -> bool:
    try:
        sample = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return False
    if DAILY_PLAN_TYPE.search(sample) or DAILY_PLAN_HEADING.search(sample):
        return True
    return parent_name.casefold().replace("-", "_") in PLAN_FOLDER_NAMES


def _collect_plan_directories(vault_root: Path) -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {}
    walked = 0
    root = vault_root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        walked += 1
        if walked > MAX_WALK_DIRS:
            break
        current = Path(dirpath)
        rel_dir = _relative_to_vault(root, current)
        if rel_dir is None:
            dirnames[:] = []
            continue
        if rel_dir == _MEETINGS_RELATIVE or rel_dir.startswith(f"{_MEETINGS_RELATIVE}/"):
            dirnames[:] = []
            continue
        dirnames[:] = [
            name
            for name in dirnames
            if name.casefold() not in SKIP_DIR_NAMES and not name.startswith(".")
        ]
        parent_name = current.name
        for name in filenames:
            if not DATED_DAILY_NAME.fullmatch(name):
                continue
            path = current / name
            if not _looks_like_daily_plan(path, parent_name=parent_name):
                continue
            found.setdefault(rel_dir, []).append(path)
            if sum(len(group) for group in found.values()) >= MAX_PLAN_FILES:
                return found
    return found


def detect_existing_daily_plans_relative(vault_root: str | Path) -> str | None:
    """Return a non-default folder that already holds dated daily plans."""
    root = Path(vault_root)
    mapped = _read_folder_map_daily_plans(root)
    if mapped and mapped != DEFAULT_DAILY_PLANS_RELATIVE:
        return mapped

    groups = _collect_plan_directories(root)
    default_files = groups.pop(DEFAULT_DAILY_PLANS_RELATIVE, [])
    if default_files:
        return None

    for candidate in LEGACY_CANDIDATES:
        if groups.get(candidate):
            return candidate

    nonempty = {path: files for path, files in groups.items() if files}
    if len(nonempty) == 1:
        return next(iter(nonempty))
    if not nonempty:
        return None

    def _newest_mtime(files: list[Path]) -> int:
        newest = 0
        for file in files:
            try:
                newest = max(newest, file.stat().st_mtime_ns)
            except OSError:
                continue
        return newest

    return max(nonempty.items(), key=lambda item: (_newest_mtime(item[1]), len(item[1]), item[0]))[0]


def resolve_daily_plans_relative(vault_root: str | Path) -> str:
    """Folder-map first, then an existing custom/legacy folder, else the default."""
    root = Path(vault_root)
    mapped = _read_folder_map_daily_plans(root)
    if mapped:
        return mapped
    detected = detect_existing_daily_plans_relative(root)
    return detected or DEFAULT_DAILY_PLANS_RELATIVE


def resolve_daily_plans_dir(vault_root: str | Path) -> Path:
    root = Path(vault_root)
    return root / resolve_daily_plans_relative(root)


def should_seed_default_daily_plans(vault_root: str | Path) -> bool:
    """Seed the inbox folder only when this vault has no other daily-plan home."""
    return resolve_daily_plans_relative(vault_root) == DEFAULT_DAILY_PLANS_RELATIVE


def skip_default_daily_plans_seed(path: str, vault_root: str | Path) -> bool:
    """True when an update must not create the new inbox daily-plan folder."""
    return (
        path == f"{DEFAULT_DAILY_PLANS_RELATIVE}/README.md"
        and not should_seed_default_daily_plans(vault_root)
    )
