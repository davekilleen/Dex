"""Read today's Dex brief without writing anything."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from core.context.session_boot import build_session_boot
from core.paths import DAILY_PLANS_DIR, resolve_for_vault

DAILY_PLAN_LIMIT = 24


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _daily_plan_lines(vault: Path, today: date) -> list[str]:
    path = resolve_for_vault(vault, DAILY_PLANS_DIR) / f"{today.isoformat()}.md"
    if not path.is_file():
        return []
    lines: list[str] = []
    for raw in _read_text(path).splitlines():
        text = raw.strip()
        if not text:
            continue
        lines.append(text)
        if len(lines) >= DAILY_PLAN_LIMIT:
            break
    return lines


def build_today_brief(
    vault: str | Path | None,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Return today's brief from local vault files. Never writes."""
    stamp = today or date.today()
    payload = build_session_boot(vault, today=stamp)
    root = Path(vault).expanduser() if vault is not None else None
    payload["daily_plan"] = (
        _daily_plan_lines(root, stamp) if root is not None and root.is_dir() else []
    )
    return payload
