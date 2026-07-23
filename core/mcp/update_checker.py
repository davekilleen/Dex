#!/usr/bin/env python3
"""Dex Update Checker MCP server backed by immutable release evidence."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.utils.update_verifier import (  # noqa: E402
    CANONICAL_RELEASE_PAGE,
    UpdateVerifier,
    _default_state_root,
    _read_state,
    _session_start_output,
)

try:
    from core.utils.dex_logger import log_error as _log_health_error
    from core.utils.dex_logger import mark_healthy as _mark_healthy

    _HAS_HEALTH = True
except ImportError:
    _HAS_HEALTH = False

mcp = FastMCP("Dex Update Checker")
if _HAS_HEALTH:
    _mark_healthy("update-checker")


def get_vault_path() -> Path:
    return Path(os.environ.get("VAULT_PATH", os.getcwd())).resolve()


def parse_version(version_str: str) -> tuple[int, int, int]:
    """Compatibility parser for callers that display prerelease versions.

    Release evidence does not use this permissive helper; UpdateVerifier uses
    its closed SemVer parser for candidate selection.
    """
    release = version_str.lstrip("v").split("-", 1)[0].split("+", 1)[0]
    parts = release.split(".")
    try:
        components = tuple(int(parts[index]) if index < len(parts) else 0 for index in range(3))
        return components[0], components[1], components[2]
    except (TypeError, ValueError):
        return (0, 0, 0)


def _check(*, force: bool = False, doctor_redisplay: bool = False) -> dict[str, object]:
    return UpdateVerifier(get_vault_path()).check(force=force, doctor_redisplay=doctor_redisplay)


@mcp.tool()
async def check_for_updates(force: bool = False, doctor_redisplay: bool = False) -> dict[str, object]:
    """Run the bounded fetch-only check; Doctor may explicitly redisplay an exact notice."""
    try:
        return _check(force=force, doctor_redisplay=doctor_redisplay)
    except Exception as error:
        if _HAS_HEALTH:
            _log_health_error(
                source="update-checker",
                message=str(error),
                human_message="Update evidence check failed",
                context={"tool": "check_for_updates"},
            )
        raise


@mcp.tool()
async def get_pending_update_notification() -> dict[str, object]:
    """Compatibility tool: SessionStart owns the once-per-exact-release notice."""
    return {"should_notify": False, "status": "skipped", "skip_reason": "session-start-owned"}


@mcp.tool()
async def mark_update_notified() -> dict[str, object]:
    """Compatibility no-op; notice dedup is committed atomically with the notice."""
    return {"success": True, "dedup_scope": "exact-release"}


@mcp.tool()
async def dismiss_update() -> dict[str, object]:
    """Keep immutable notice history; installed version evidence changes after an update."""
    return {"success": True, "message": "Exact-release notice history retained"}


@mcp.tool()
async def get_changelog_from_github(version: str | None = None) -> str:
    """Return guidance without making a second, unaudited network request."""
    suffix = version or "the exact immutable tag shown by the evidence check"
    return f"Review {suffix} on its canonical release page. Dex did not fetch separate changelog content."


@mcp.tool()
async def get_update_status() -> dict[str, object]:
    """Read local attempt state without contacting a network or claiming currentness."""
    vault = get_vault_path()
    state_path = _default_state_root(vault) / "state.json"
    try:
        state = _read_state(state_path)
    except Exception:
        return {"status": "UNKNOWN", "check_due": True}
    last_attempt = state.get("last_attempt_date")
    return {
        "status": state.get("last_status", "UNKNOWN"),
        "last_attempt_date": last_attempt,
        "check_due": last_attempt != datetime.now(timezone.utc).date().isoformat(),
        "release_page_template": CANONICAL_RELEASE_PAGE,
        "currentness_claim": False,
    }


def main(argv: list[str]) -> int:
    if "--session-start" in argv:
        _session_start_output(_check())
        return 0
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
