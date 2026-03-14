#!/usr/bin/env python3
"""
Dex Pre-flight Health Checker

Fast checks that configured MCP servers can actually start.
Called from session-start.sh — outputs plain-language results.

Checks:
1. Does the Python file exist?
2. Can core dependencies import?
3. Is VAULT_PATH accessible?

Caches results in .logs/mcp-health.json — re-checks when config changes or > 24h old.
Target: < 500ms total.
"""

import hashlib
import importlib.util
import json
import os
from datetime import datetime, timedelta
from pathlib import Path


def get_vault_path() -> str:
    return os.environ.get("VAULT_PATH", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def get_mcp_config_path() -> Path:
    return Path(get_vault_path()) / ".mcp.json"


def get_health_path() -> Path:
    logs_dir = Path(get_vault_path()) / ".logs"
    logs_dir.mkdir(exist_ok=True)
    return logs_dir / "mcp-health.json"


def get_error_queue_path() -> Path:
    return Path(get_vault_path()) / ".logs" / "error-queue.json"


# Map of MCP server names → their Python module files (relative to dex-core/core/mcp/)
SERVER_MODULES = {
    "work-mcp": "work_server.py",
    "calendar-mcp": "calendar_server.py",
    "career-mcp": "career_server.py",
    "granola-mcp": "granola_server.py",
    "dex-improvements-mcp": "dex_improvements_server.py",
    "dex-analytics": "analytics_server.py",
    "onboarding-mcp": "onboarding_server.py",
    "resume-mcp": "resume_server.py",
    "beta-mcp": "beta_server.py",
    "update-checker": "update_checker.py",
    "commitment-mcp": "commitment_server.py",
    "demo-mode-mcp": "demo_mode_server.py",
}

# Human-friendly names
SERVER_LABELS = {
    "work-mcp": "Task Manager",
    "calendar-mcp": "Calendar",
    "career-mcp": "Career Tracker",
    "granola-mcp": "Granola (meetings)",
    "dex-improvements-mcp": "Improvements Backlog",
    "dex-analytics": "Analytics",
    "onboarding-mcp": "Onboarding",
    "resume-mcp": "Resume Builder",
    "beta-mcp": "Beta Features",
    "update-checker": "Update Checker",
    "commitment-mcp": "Commitment Detection",
    "demo-mode-mcp": "Demo Mode",
}


def config_hash() -> str:
    """Hash the .mcp.json config to detect changes."""
    config_path = get_mcp_config_path()
    if not config_path.exists():
        return ""
    return hashlib.md5(config_path.read_bytes()).hexdigest()[:12]


def get_configured_servers() -> list[str]:
    """Read .mcp.json and return list of configured server names."""
    config_path = get_mcp_config_path()
    if not config_path.exists():
        return []
    try:
        config = json.loads(config_path.read_text())
        return list(config.get("mcpServers", {}).keys())
    except (json.JSONDecodeError, IOError):
        return []


def needs_recheck(health: dict) -> bool:
    """Check if we need to re-run health checks."""
    current_hash = config_hash()

    # Config changed
    if health.get("configHash") != current_hash:
        return True

    # Last check > 24 hours ago
    last_check = health.get("lastCheck")
    if not last_check:
        return True
    try:
        last_dt = datetime.fromisoformat(last_check.replace("Z", "+00:00"))
        if datetime.now(last_dt.tzinfo) - last_dt > timedelta(hours=24):
            return True
    except (ValueError, TypeError):
        return True

    # Check if any errors were queued since last check for any server
    error_queue_path = get_error_queue_path()
    if error_queue_path.exists():
        try:
            errors = json.loads(error_queue_path.read_text())
            for err in errors:
                if not err.get("acknowledged") and err.get("timestamp", "") > (last_check or ""):
                    return True
        except (json.JSONDecodeError, IOError):
            pass

    return False


def check_server(server_name: str) -> dict:
    """Run fast health check for a single MCP server."""
    mcp_dir = Path(get_vault_path()) / "dex-core" / "core" / "mcp"
    module_file = SERVER_MODULES.get(server_name)

    if not module_file:
        # Not a known dex-core server — might be user-added, skip
        return {"status": "unknown", "note": "Not a core Dex server"}

    full_path = mcp_dir / module_file
    label = SERVER_LABELS.get(server_name, server_name)

    # Check 1: Does the file exist?
    if not full_path.exists():
        return {
            "status": "error",
            "error": f"Server file not found: {module_file}",
            "humanError": f"{label} is missing — dex-core may need reinstalling",
        }

    # Check 2: Can Python parse it? (syntax check, no execution)
    try:
        import py_compile
        py_compile.compile(str(full_path), doraise=True)
    except py_compile.PyCompileError as e:
        return {
            "status": "error",
            "error": str(e),
            "humanError": f"{label} has a syntax error — may need updating",
        }

    # Check 3: Can core MCP dependency import?
    try:
        # Check if mcp package is available (all servers need this)
        spec = importlib.util.find_spec("mcp")
        if spec is None:
            return {
                "status": "error",
                "error": "mcp package not found",
                "humanError": f"{label} can't start: 'mcp' package missing (pip install mcp)",
            }
    except (ModuleNotFoundError, ValueError):
        return {
            "status": "error",
            "error": "mcp package not importable",
            "humanError": f"{label} can't start: 'mcp' package broken",
        }

    return {"status": "ok"}


def run_preflight() -> dict:
    """Run pre-flight checks on all configured servers. Returns health dict."""
    configured = get_configured_servers()
    health_path = get_health_path()

    # Load existing health data
    health = {}
    if health_path.exists():
        try:
            health = json.loads(health_path.read_text())
        except (json.JSONDecodeError, IOError):
            health = {}

    # Check if we need to re-run
    if not needs_recheck(health):
        return health

    # Run checks
    now = datetime.now(tz=None).astimezone().isoformat()
    servers = {}

    for server_name in configured:
        result = check_server(server_name)
        result["checkedAt"] = now
        servers[server_name] = result

    health = {
        "lastCheck": now,
        "configHash": config_hash(),
        "servers": servers,
    }

    # Write cached results
    try:
        health_path.write_text(json.dumps(health, indent=2))
    except IOError:
        pass

    return health


def format_output(health: dict) -> str:
    """Format health check results for session-start hook output."""
    servers = health.get("servers", {})
    if not servers:
        return ""

    errors = []
    ok_count = 0
    total = 0

    for name, info in servers.items():
        if info.get("status") == "unknown":
            continue
        total += 1
        if info.get("status") == "error":
            human_err = info.get("humanError", f"{name} has an issue")
            errors.append(f"  ❌ {human_err}")
        else:
            ok_count += 1

    if not errors:
        return ""  # All healthy — stay silent

    lines = ["--- 🩺 Dex Pre-flight ---"]
    lines.extend(errors)
    lines.append(f"  ✅ {ok_count}/{total} MCP servers ready")
    lines.append("Say: 'health check' to investigate")
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def format_errors(max_errors: int = 3) -> str:
    """Format unacknowledged errors for session-start hook output."""
    error_queue_path = get_error_queue_path()
    if not error_queue_path.exists():
        return ""

    try:
        errors = json.loads(error_queue_path.read_text())
    except (json.JSONDecodeError, IOError):
        return ""

    unacked = [e for e in errors if not e.get("acknowledged", False)]
    if not unacked:
        return ""

    lines = [f"--- ⚠️ Recent Errors ({len(unacked)}) ---"]
    for err in unacked[-max_errors:]:
        source = err.get("source", "?")
        human = err.get("humanMessage", err.get("message", "Unknown"))[:100]
        ts = err.get("timestamp", "")[:16]
        count = err.get("count", 1)
        count_str = f" (×{count})" if count > 1 else ""
        lines.append(f"  [{source}] {ts} — {human}{count_str}")

    if len(unacked) > max_errors:
        lines.append(f"  ... and {len(unacked) - max_errors} more")

    lines.append("Say: 'show me the recent errors' to investigate")
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    # Called from session-start.sh
    health = run_preflight()
    preflight_output = format_output(health)
    error_output = format_errors()

    if preflight_output:
        print(preflight_output)
    if error_output:
        print(error_output)
