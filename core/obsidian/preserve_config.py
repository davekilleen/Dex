"""Keep a user's Obsidian settings when Dex writes shipped defaults.

Updates and ``generate_obsidian_config`` both go through this helper so a
customised app, appearance, hotkeys, or workspace file is merged rather than
replaced, and a timestamped backup is saved first.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OBSIDIAN_SETTING_FILES = (
    "app.json",
    "appearance.json",
    "hotkeys.json",
    "workspace.json",
)


def backup_suffix(when: datetime | None = None) -> str:
    """Return ``bak-YYYYMMDD-HHMMSS`` in UTC."""
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"bak-{stamp}"


def backup_relative(filename: str, when: datetime | None = None) -> str:
    """Vault-relative backup path under ``.obsidian/``."""
    return f".obsidian/{filename}.{backup_suffix(when)}"


def _load_object(raw: bytes) -> dict[str, Any] | None:
    try:
        loaded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _merge_objects(shipped: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge objects. The user's value wins on a conflict."""
    merged = dict(shipped)
    for key, value in existing.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge_objects(current, value)
        else:
            merged[key] = value
    return merged


def merge_obsidian_json(
    existing: bytes | None,
    shipped: bytes,
    *,
    filename: str,
) -> bytes:
    """Return JSON to write. Workspace layout is kept whole when valid."""
    shipped_obj = _load_object(shipped) or {}
    existing_obj = _load_object(existing) if existing else None
    if existing_obj is None:
        payload = shipped_obj
    elif filename == "workspace.json":
        payload = existing_obj
    else:
        payload = _merge_objects(shipped_obj, existing_obj)
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def write_obsidian_json(
    path: Path,
    shipped: dict[str, Any],
    *,
    now: datetime | None = None,
) -> Path | None:
    """Write one settings file. Backup first when the live file already exists.

    Returns the backup path when one was written, otherwise None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    shipped_bytes = (json.dumps(shipped, indent=2) + "\n").encode("utf-8")
    existing = path.read_bytes() if path.is_file() else None
    merged = merge_obsidian_json(existing, shipped_bytes, filename=path.name)
    backup_path: Path | None = None
    if existing is not None and existing != merged:
        candidate = path.with_name(f"{path.name}.{backup_suffix(now)}")
        suffix = 1
        while candidate.exists():
            candidate = path.with_name(f"{path.name}.{backup_suffix(now)}-{suffix}")
            suffix += 1
        candidate.write_bytes(existing)
        backup_path = candidate
    if existing != merged:
        path.write_bytes(merged)
    elif not path.exists():
        path.write_bytes(merged)
    return backup_path
