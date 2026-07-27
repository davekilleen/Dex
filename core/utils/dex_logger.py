"""
Dex Health System — Shared Logger for MCP Servers

Provides error queue persistence, dedup, and human-friendly error messages.
Imported by all MCP servers to capture failures instantly.

Usage:
    from core.utils.dex_logger import log_error, log_warning, mark_healthy

    # When a tool call fails:
    log_error("work-mcp", str(e), human_message="Task creation failed", context={"tool": "create_task"})

    # When server starts successfully:
    mark_healthy("work-mcp")
"""

import fcntl
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

STALE_ERROR_DAYS = 30
MAX_ERROR_ENTRIES = 50
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _get_vault_path() -> str:
    """Get vault path from env, with fallback."""
    return os.environ.get("VAULT_PATH", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _get_logs_dir() -> Path:
    """Get or create .logs directory."""
    logs_dir = Path(_get_vault_path()) / ".logs"
    logs_dir.mkdir(exist_ok=True)

    # Ensure .gitignore exists
    gitignore = logs_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")

    return logs_dir


def _get_queue_path() -> Path:
    return _get_logs_dir() / "error-queue.json"


def _get_health_path() -> Path:
    return _get_logs_dir() / "mcp-health.json"


def _installed_dex_version() -> Optional[str]:
    """Read the installed version without ever disrupting error reporting."""
    try:
        package_path = Path(_get_vault_path()) / "package.json"
        if package_path.is_symlink() or not package_path.is_file():
            return None
        package = json.loads(package_path.read_text())
        version = package.get("version") if isinstance(package, dict) else None
        if not isinstance(version, str) or _SEMVER_RE.fullmatch(version) is None:
            return None
        return version
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Error-to-human message mapping
# ---------------------------------------------------------------------------

_ERROR_PATTERNS = [
    ("ModuleNotFoundError", "{source} can't start: missing Python package"),
    ("No module named", "{source} can't start: missing Python package"),
    ("ECONNREFUSED", "{source} isn't responding"),
    ("FileNotFoundError", "{source} can't find a required file"),
    ("JSONDecodeError", "{source} got corrupted data — may need a file fix"),
    ("PermissionError", "{source} can't write to a file — check permissions"),
    ("ANTHROPIC_API_KEY", "API key missing — add it to your .env file"),
    ("VAULT_PATH", "Vault path not configured — check your .mcp.json"),
    ("yaml", "{source} can't read config — YAML file may be corrupted"),
    ("TimeoutError", "{source} timed out"),
    ("ConnectionError", "{source} can't connect"),
]


def _generate_human_message(source: str, message: str) -> str:
    """Map technical error to plain-language description."""
    for pattern, template in _ERROR_PATTERNS:
        if pattern.lower() in message.lower():
            return template.format(source=source)
    return f"{source} hit an unexpected error"


# ---------------------------------------------------------------------------
# Queue I/O (with file locking for concurrent MCP servers)
# ---------------------------------------------------------------------------

def _read_queue_with_status() -> tuple[str, list]:
    """Read the queue without throwing and preserve whether it was readable."""
    try:
        queue_path = _get_queue_path()
        if not queue_path.exists():
            return "missing", []
        with open(queue_path, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                entries = json.load(f)
                if not isinstance(entries, list):
                    return "unreadable", []
                return "readable", entries
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        return "unreadable", []


def _read_queue() -> list:
    """Read error queue with file locking."""
    _status, entries = _read_queue_with_status()
    return entries


def _normalized_now(now: Optional[datetime] = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _entry_timestamp(entry: object) -> Optional[datetime]:
    if not isinstance(entry, dict):
        return None
    timestamp = entry.get("timestamp")
    if not isinstance(timestamp, str):
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_stale(entry: object, *, now: datetime) -> bool:
    timestamp = _entry_timestamp(entry)
    if timestamp is None:
        return False
    return timestamp < now - timedelta(days=STALE_ERROR_DAYS)


def _prune_queue(entries: list, *, now: Optional[datetime] = None) -> list:
    """Apply the queue's age policy and size bound in one place."""
    reference_time = _normalized_now(now)
    recent_or_unknown = [
        entry for entry in entries if not _is_stale(entry, now=reference_time)
    ]
    return recent_or_unknown[-MAX_ERROR_ENTRIES:]


def _write_queue(entries: list, *, now: Optional[datetime] = None) -> None:
    """Write error queue with file locking."""
    queue_path = _get_queue_path()
    queue_path.parent.mkdir(exist_ok=True)
    with open(queue_path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(_prune_queue(entries, now=now), f, indent=2)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def log_error(
    source: str,
    message: str,
    human_message: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log an error to the queue. Called from MCP server except blocks.

    Args:
        source: MCP server name (e.g., "work-mcp")
        message: Technical error message
        human_message: Plain-language description (auto-generated if not provided)
        context: Additional context (tool name, args summary, etc.)
    """
    try:
        queue = _read_queue()
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat().replace("+00:00", "Z")
        dex_version = _installed_dex_version()

        # Dedup: if same source+message within last 5 minutes, increment count
        dedup_cutoff = now.timestamp() - 300  # 5 minutes
        for entry in reversed(queue):
            if (
                entry.get("source") == source
                and entry.get("message") == message
                and not entry.get("acknowledged", False)
            ):
                try:
                    entry_time = datetime.fromisoformat(
                        entry["timestamp"].replace("Z", "+00:00")
                    ).timestamp()
                    if entry_time > dedup_cutoff:
                        entry["count"] = entry.get("count", 1) + 1
                        entry["timestamp"] = timestamp
                        if dex_version is not None:
                            entry["dexVersion"] = dex_version
                        _write_queue(queue, now=now)
                        return
                except (ValueError, KeyError):
                    pass

        # New entry
        entry = {
            "id": f"err-{int(time.time())}-{os.urandom(2).hex()}",
            "source": source,
            "severity": "error",
            "message": message,
            "humanMessage": human_message or _generate_human_message(source, message),
            "timestamp": timestamp,
            "acknowledged": False,
            "count": 1,
        }
        if dex_version is not None:
            entry["dexVersion"] = dex_version
        if context:
            entry["context"] = context

        queue.append(entry)
        _write_queue(queue, now=now)
    except Exception:
        pass  # Never throw from error logging code


def log_warning(
    source: str,
    message: str,
    human_message: Optional[str] = None,
) -> None:
    """Log a warning (less severe than error, same queue)."""
    try:
        queue = _read_queue()
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat().replace("+00:00", "Z")
        dex_version = _installed_dex_version()

        entry = {
            "id": f"wrn-{int(time.time())}-{os.urandom(2).hex()}",
            "source": source,
            "severity": "warning",
            "message": message,
            "humanMessage": human_message or _generate_human_message(source, message),
            "timestamp": timestamp,
            "acknowledged": False,
            "count": 1,
        }
        if dex_version is not None:
            entry["dexVersion"] = dex_version

        queue.append(entry)
        _write_queue(queue, now=now)
    except Exception:
        pass


def mark_healthy(source: str) -> None:
    """Record that an MCP server started successfully."""
    try:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        health_path = _get_health_path()
        health = {}
        if health_path.exists():
            try:
                health = json.loads(health_path.read_text())
            except (json.JSONDecodeError, IOError):
                health = {}

        if "servers" not in health:
            health["servers"] = {}

        health["servers"][source] = {
            "status": "ok",
            "checkedAt": now,
        }
        health["lastCheck"] = now

        health_path.write_text(json.dumps(health, indent=2))
    except Exception:
        pass


def get_error_queue_status() -> str:
    """Return missing, readable, or unreadable without disrupting callers."""
    status, _entries = _read_queue_with_status()
    return status


def _partition_unacknowledged_errors(
    *, now: Optional[datetime] = None
) -> tuple[list, list]:
    reference_time = _normalized_now(now)
    current_version = _installed_dex_version()
    current = []
    historical = []
    for entry in _read_queue():
        if not isinstance(entry, dict) or entry.get("acknowledged", False):
            continue
        entry_version = entry.get("dexVersion")
        from_other_version = (
            current_version is not None
            and isinstance(entry_version, str)
            and entry_version != current_version
        )
        if _is_stale(entry, now=reference_time) or from_other_version:
            historical.append(entry)
        else:
            current.append(entry)
    return current, historical


def get_unacknowledged_errors(*, now: Optional[datetime] = None) -> list:
    """Get recent unacknowledged errors from this Dex version."""
    try:
        current, _historical = _partition_unacknowledged_errors(now=now)
        return current
    except Exception:
        return []


def get_historical_errors(*, now: Optional[datetime] = None) -> list:
    """Get unacknowledged errors that are stale or from an older Dex version."""
    try:
        _current, historical = _partition_unacknowledged_errors(now=now)
        return historical
    except Exception:
        return []
