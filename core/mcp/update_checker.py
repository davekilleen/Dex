#!/usr/bin/env python3
"""
Dex Update Checker MCP Server

Checks for Dex updates from GitHub and notifies users of new versions.
Writes a persistent .update-available file so Dex can remind users once
per day across multiple chat sessions.
"""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Health system — error queue and health reporting
try:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from core.utils.dex_logger import log_error as _log_health_error
    from core.utils.dex_logger import mark_healthy as _mark_healthy
    _HAS_HEALTH = True
except ImportError:
    _HAS_HEALTH = False

# Initialize MCP server
mcp = FastMCP("Dex Update Checker")

# Mark healthy on import (FastMCP servers start on import)
if _HAS_HEALTH:
    _mark_healthy("update-checker")

# Constants
GITHUB_REPO = "davekilleen/dex"
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_REPO}"
CHECK_INTERVAL_DAYS = 1
UPDATE_NOTIFICATION_FILE = ".update-available"


def get_vault_path() -> Path:
    """Get the vault path from environment"""
    vault_path = os.environ.get("VAULT_PATH", os.getcwd())
    return Path(vault_path)


def get_current_version() -> str:
    """Read current version from package.json"""
    vault = get_vault_path()
    package_file = vault / "package.json"
    
    try:
        with open(package_file, 'r') as f:
            package_data = json.load(f)
            return package_data.get("version", "1.0.0")
    except Exception as e:
        return "1.0.0"


def get_last_check_time() -> datetime | None:
    """Get timestamp of last update check"""
    vault = get_vault_path()
    check_file = vault / "System" / ".last-update-check"
    
    if not check_file.exists():
        return None
    
    try:
        with open(check_file, 'r') as f:
            timestamp_str = f.read().strip()
            return datetime.fromisoformat(timestamp_str)
    except Exception:
        return None


def save_last_check_time():
    """Save current timestamp as last update check"""
    vault = get_vault_path()
    check_file = vault / "System" / ".last-update-check"
    
    check_file.parent.mkdir(parents=True, exist_ok=True)
    with open(check_file, 'w') as f:
        f.write(datetime.now().isoformat())


def should_check_for_updates() -> bool:
    """Determine if enough time has passed since last check"""
    last_check = get_last_check_time()
    if last_check is None:
        return True
    
    days_since_check = (datetime.now() - last_check).days
    return days_since_check >= CHECK_INTERVAL_DAYS


# --- Persistent update notification file ---

def _notification_path() -> Path:
    return get_vault_path() / "System" / UPDATE_NOTIFICATION_FILE


def write_update_notification(latest_version: str, current_version: str, release_url: str, update_type: str, breaking: bool):
    """Write .update-available file when an update is found."""
    path = _notification_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "latest_version": latest_version,
        "current_version": current_version,
        "release_url": release_url,
        "update_type": update_type,
        "breaking_changes": breaking,
        "discovered_at": datetime.now().isoformat(),
        "last_notified": None,
    }
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def read_update_notification() -> dict | None:
    """Read .update-available file. Returns None if no pending update."""
    path = _notification_path()
    if not path.exists():
        return None
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def clear_update_notification():
    """Delete .update-available file (called after successful /dex-update)."""
    path = _notification_path()
    if path.exists():
        path.unlink()


def mark_user_notified():
    """Stamp today's date into last_notified so we don't nag again today."""
    path = _notification_path()
    data = read_update_notification()
    if data is None:
        return
    data["last_notified"] = date.today().isoformat()
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def should_notify_user() -> bool:
    """True if .update-available exists and we haven't notified today."""
    data = read_update_notification()
    if data is None:
        return False
    last_notified = data.get("last_notified")
    if last_notified is None:
        return True
    try:
        return date.fromisoformat(last_notified) < date.today()
    except (ValueError, TypeError):
        return True


async def fetch_latest_release():
    """Fetch latest release info from GitHub"""
    import aiohttp
    
    url = f"{GITHUB_API_BASE}/releases/latest"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    return await response.json()
                return None
    except Exception as e:
        return None


def parse_version(version_str: str) -> tuple[int, int, int]:
    """Parse version string into tuple (major, minor, patch)"""
    version_str = version_str.lstrip('v')
    parts = version_str.split('.')
    
    try:
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major, minor, patch)
    except ValueError:
        return (0, 0, 0)


def compare_versions(current: str, latest: str) -> str:
    """Compare two version strings. Returns: 'older', 'same', or 'newer'"""
    current_tuple = parse_version(current)
    latest_tuple = parse_version(latest)
    
    if current_tuple < latest_tuple:
        return "older"
    elif current_tuple == latest_tuple:
        return "same"
    else:
        return "newer"


@mcp.tool()
async def check_for_updates(force: bool = False) -> dict:
    """
    Check if a newer version of Dex is available on GitHub.

    Args:
        force: If True, check even if checked recently. Default: False

    Returns:
        dict with keys:
        - update_available: bool
        - current_version: str
        - latest_version: str (if available)
        - release_notes: str (if available)
        - release_url: str (if available)
        - breaking_changes: bool
    """
    try:
        # Check if we should skip (unless forced)
        if not force and not should_check_for_updates():
            last_check = get_last_check_time()
            days_ago = (datetime.now() - last_check).days if last_check else 0
            return {
                "update_available": False,
                "current_version": get_current_version(),
                "message": f"Last checked {days_ago} days ago. Use force=True to check now.",
                "skip_reason": "too_recent"
            }

        current_version = get_current_version()

        # Fetch latest release from GitHub
        release_data = await fetch_latest_release()

        if not release_data:
            return {
                "update_available": False,
                "current_version": current_version,
                "error": "Could not fetch release data from GitHub",
                "skip_reason": "network_error"
            }

        # Save check timestamp
        save_last_check_time()

        # Parse release data
        latest_version = release_data.get("tag_name", "").lstrip('v')
        release_notes = release_data.get("body", "")
        release_url = release_data.get("html_url", "")

        # Compare versions
        comparison = compare_versions(current_version, latest_version)

        # Check for breaking changes
        breaking_changes = "BREAKING" in release_notes.upper() or "⚠️" in release_notes

        # Determine update type
        current_tuple = parse_version(current_version)
        latest_tuple = parse_version(latest_version)

        update_type = "patch"
        if latest_tuple[0] > current_tuple[0]:
            update_type = "major"
        elif latest_tuple[1] > current_tuple[1]:
            update_type = "minor"

        update_available = comparison == "older"

        # Persist notification file when update is found
        if update_available:
            write_update_notification(latest_version, current_version, release_url, update_type, breaking_changes)
        else:
            # No update — clear any stale notification
            clear_update_notification()

        result = {
            "update_available": update_available,
            "current_version": current_version,
            "latest_version": latest_version,
            "release_notes": release_notes,
            "release_url": release_url,
            "breaking_changes": breaking_changes,
            "update_type": update_type,
            "comparison": comparison
        }

        return result
    except Exception as e:
        if _HAS_HEALTH:
            _log_health_error(
                source="update-checker",
                message=str(e),
                human_message="Update check failed",
                context={"tool": "check_for_updates"}
            )
        raise


@mcp.tool()
async def get_pending_update_notification() -> dict:
    """
    Check if there's a pending update notification the user hasn't seen today.

    Call this at the start of any conversation. If should_notify is True,
    mention the update once and then call mark_notified() so the user
    isn't reminded again until tomorrow.

    Returns:
        dict with:
        - should_notify: bool — True if user should be told about an update
        - latest_version: str (if available)
        - current_version: str (if available)
        - update_type: str (if available)
        - release_url: str (if available)
    """
    try:
        if not should_notify_user():
            return {"should_notify": False}

        data = read_update_notification()
        if data is None:
            return {"should_notify": False}

        return {
            "should_notify": True,
            "latest_version": data.get("latest_version"),
            "current_version": data.get("current_version"),
            "update_type": data.get("update_type", "patch"),
            "release_url": data.get("release_url", ""),
            "breaking_changes": data.get("breaking_changes", False),
        }
    except Exception as e:
        if _HAS_HEALTH:
            _log_health_error(
                source="update-checker",
                message=str(e),
                human_message="Pending update notification check failed",
                context={"tool": "get_pending_update_notification"}
            )
        raise


@mcp.tool()
async def mark_update_notified() -> dict:
    """
    Mark that the user has been notified about the pending update today.
    Call this AFTER showing the update notification so they aren't reminded
    again in subsequent chats today.

    Returns:
        dict with success status
    """
    try:
        mark_user_notified()
        return {"success": True, "notified_date": date.today().isoformat()}
    except Exception as e:
        if _HAS_HEALTH:
            _log_health_error(
                source="update-checker",
                message=str(e),
                human_message="Failed to mark update as notified",
                context={"tool": "mark_update_notified"}
            )
        raise


@mcp.tool()
async def dismiss_update() -> dict:
    """
    Clear the update notification entirely (e.g. after successful /dex-update).

    Returns:
        dict with success status
    """
    try:
        clear_update_notification()
        return {"success": True, "message": "Update notification cleared"}
    except Exception as e:
        if _HAS_HEALTH:
            _log_health_error(
                source="update-checker",
                message=str(e),
                human_message="Failed to dismiss update notification",
                context={"tool": "dismiss_update"}
            )
        raise


@mcp.tool()
async def get_changelog_from_github(version: str | None = None) -> str:
    """
    Fetch CHANGELOG.md from GitHub (latest or specific version).

    Args:
        version: Specific version to fetch (e.g., "v1.2.0"). If None, fetches latest.

    Returns:
        Contents of CHANGELOG.md
    """
    try:
        import aiohttp

        # Construct raw GitHub URL
        branch_or_tag = version if version else "main"
        url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{branch_or_tag}/CHANGELOG.md"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        return await response.text()
                    return f"Error: Could not fetch CHANGELOG.md (status {response.status})"
        except Exception as e:
            return f"Error fetching CHANGELOG.md: {str(e)}"
    except Exception as e:
        if _HAS_HEALTH:
            _log_health_error(
                source="update-checker",
                message=str(e),
                human_message="Failed to fetch changelog from GitHub",
                context={"tool": "get_changelog_from_github"}
            )
        raise


@mcp.tool()
async def get_update_status() -> dict:
    """
    Get current update status without checking GitHub.
    Shows when last check was performed and current version.

    Returns:
        dict with current version, last check time, and whether check is due
    """
    try:
        current_version = get_current_version()
        last_check = get_last_check_time()
        check_due = should_check_for_updates()

        result = {
            "current_version": current_version,
            "check_due": check_due
        }

        if last_check:
            result["last_check"] = last_check.isoformat()
            result["days_since_check"] = (datetime.now() - last_check).days
        else:
            result["last_check"] = None
            result["message"] = "Never checked for updates"

        return result
    except Exception as e:
        if _HAS_HEALTH:
            _log_health_error(
                source="update-checker",
                message=str(e),
                human_message="Failed to get update status",
                context={"tool": "get_update_status"}
            )
        raise


if __name__ == "__main__":
    mcp.run()
