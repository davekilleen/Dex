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
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

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
    ("ANTHROPIC_API_KEY", "API key missing — run /ai-setup"),
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

def _read_queue() -> list:
    """Read error queue with file locking."""
    queue_path = _get_queue_path()
    if not queue_path.exists():
        return []
    try:
        with open(queue_path, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except (json.JSONDecodeError, IOError):
        return []


def _write_queue(entries: list) -> None:
    """Write error queue with file locking."""
    queue_path = _get_queue_path()
    queue_path.parent.mkdir(exist_ok=True)
    with open(queue_path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(entries[-50:], f, indent=2)  # Cap at 50 entries
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
        now = datetime.utcnow().isoformat() + "Z"

        # Dedup: if same source+message within last 5 minutes, increment count
        dedup_cutoff = time.time() - 300  # 5 minutes
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
                        entry["timestamp"] = now
                        _write_queue(queue)
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
            "timestamp": now,
            "acknowledged": False,
            "count": 1,
        }
        if context:
            entry["context"] = context

        queue.append(entry)
        _write_queue(queue)
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
        now = datetime.utcnow().isoformat() + "Z"

        entry = {
            "id": f"wrn-{int(time.time())}-{os.urandom(2).hex()}",
            "source": source,
            "severity": "warning",
            "message": message,
            "humanMessage": human_message or _generate_human_message(source, message),
            "timestamp": now,
            "acknowledged": False,
            "count": 1,
        }

        queue.append(entry)
        _write_queue(queue)
    except Exception:
        pass


def mark_healthy(source: str) -> None:
    """Record that an MCP server started successfully."""
    try:
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
            "checkedAt": datetime.utcnow().isoformat() + "Z",
        }
        health["lastCheck"] = datetime.utcnow().isoformat() + "Z"

        health_path.write_text(json.dumps(health, indent=2))
    except Exception:
        pass


def acknowledge_errors(ids: Optional[list] = None) -> int:
    """
    Mark errors as acknowledged. Returns count of acknowledged errors.
    If ids is None, acknowledges all.
    """
    try:
        queue = _read_queue()
        count = 0
        for entry in queue:
            if entry.get("acknowledged"):
                continue
            if ids is None or entry.get("id") in ids:
                entry["acknowledged"] = True
                count += 1
        _write_queue(queue)
        return count
    except Exception:
        return 0


def get_unacknowledged_errors() -> list:
    """Get all unacknowledged errors for session start display."""
    try:
        queue = _read_queue()
        return [e for e in queue if not e.get("acknowledged", False)]
    except Exception:
        return []
