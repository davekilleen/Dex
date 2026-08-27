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
import subprocess
from datetime import datetime, timedelta
from pathlib import Path


def get_vault_path() -> str:
    return os.environ.get("VAULT_PATH", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def get_mcp_config_path() -> Path:
    vault_root = Path(get_vault_path())
    root_config = vault_root / ".mcp.json"
    legacy_config = vault_root / "System" / ".mcp.json"
    if root_config.exists() or not legacy_config.exists():
        return root_config
    return legacy_config


def get_health_path() -> Path:
    logs_dir = Path(get_vault_path()) / ".logs"
    logs_dir.mkdir(exist_ok=True)
    return logs_dir / "mcp-health.json"


def get_error_queue_path() -> Path:
    return Path(get_vault_path()) / ".logs" / "error-queue.json"


# Map of MCP server names → their Python module files (relative to core/mcp/).
# Core servers only. An opt-in integration server (core/integrations/<name>/)
# is not listed here: preflight only covers what every install registers, and
# each integration reports its own health through its Doctor probe.
SERVER_MODULES = {
    "work-mcp": "work_server.py",
    "calendar-mcp": "calendar_server.py",
    "career-mcp": "career_server.py",
    "granola-mcp": "granola_server.py",
    "dex-improvements-mcp": "dex_improvements_server.py",
    "dex-analytics": "analytics_server.py",
    "onboarding-mcp": "onboarding_server.py",
    "resume-mcp": "resume_server.py",
    "session-memory": "session_memory_server.py",
    "customization-migration-mcp": "customization_migration_server.py",
    "update-checker": "update_checker.py",
}

WORK_MCP_NAME = "work-mcp"
# Existing Doctor / error-queue voice. Do not invent a new tester sentence.
NEVER_SPAWNED_HUMAN_ERROR = "Task Manager cannot start"

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
    "customization-migration-mcp": "Customization Migration",
    "update-checker": "Update Checker",
}


def config_hash() -> str:
    """Hash the .mcp.json config to detect changes."""
    config_path = get_mcp_config_path()
    if not config_path.exists():
        return ""
    return hashlib.md5(config_path.read_bytes()).hexdigest()[:12]


def get_configured_servers() -> list[str]:
    """Read .mcp.json and return list of configured server names."""
    return list(get_configured_server_entries())


def get_configured_server_entries() -> dict[str, dict]:
    """Read .mcp.json and return the mcpServers mapping."""
    config_path = get_mcp_config_path()
    if not config_path.exists():
        return {}
    try:
        config = json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    servers = config.get("mcpServers")
    if not isinstance(servers, dict):
        return {}
    return {
        name: entry
        for name, entry in servers.items()
        if isinstance(name, str) and isinstance(entry, dict)
    }


def script_path_for(server_name: str, entry: dict | None = None) -> Path | None:
    """Resolve the Python script a core MCP entry should run."""
    module_file = SERVER_MODULES.get(server_name)
    if not module_file:
        return None
    args = entry.get("args") if isinstance(entry, dict) else None
    if isinstance(args, list):
        for argument in args:
            if not isinstance(argument, str) or Path(argument).name != module_file:
                continue
            path = Path(os.path.expanduser(os.path.expandvars(argument)))
            if not path.is_absolute():
                path = Path(get_vault_path()) / path
            return path
    return Path(get_vault_path()) / "core" / "mcp" / module_file


def list_process_cmdlines() -> list[str] | None:
    """Best-effort process command lines, or None when the table cannot be read."""
    proc = Path("/proc")
    if proc.is_dir():
        cmdlines: list[str] = []
        try:
            pid_dirs = list(proc.iterdir())
        except OSError:
            return None
        for pid_dir in pid_dirs:
            if not pid_dir.name.isdigit():
                continue
            try:
                raw = (pid_dir / "cmdline").read_bytes()
            except OSError:
                continue
            if not raw:
                continue
            cmdlines.append(raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip())
        return cmdlines

    try:
        result = subprocess.run(
            ["ps", "-axww", "-o", "command="],
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError):
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout
    if raw is None:
        return None
    if isinstance(raw, bytes):
        stdout = raw.decode("utf-8", "replace")
    else:
        stdout = raw
    return [line.strip() for line in stdout.splitlines() if line.strip()]


def script_is_live(script_path: Path, cmdlines: list[str]) -> bool:
    """Whether any process command line is running this vault's script."""
    candidates = {os.path.normpath(str(script_path))}
    try:
        candidates.add(os.path.normpath(str(script_path.resolve())))
    except OSError:
        pass
    module = script_path.name
    if module in SERVER_MODULES.values():
        candidates.add(os.path.normpath(f"core/mcp/{module}"))
    for cmdline in cmdlines:
        normalized = os.path.normpath(cmdline)
        if any(candidate and candidate in normalized for candidate in candidates):
            return True
    return False


def never_spawned_work_mcp_result(
    servers: dict,
    *,
    cmdlines: list[str] | None = None,
    entries: dict | None = None,
) -> dict | None:
    """Error payload when work-mcp is listed, present, and has no live process.

    Stays silent when no sibling core Python MCP is live, so an idle machine
    or a checkup with no session does not look like a Task Manager failure.
    Pass ``entries`` to use an already-read config (smoke's isolated plan);
    otherwise read ``.mcp.json``.
    """
    configured = get_configured_server_entries() if entries is None else entries
    if not isinstance(configured, dict) or WORK_MCP_NAME not in configured:
        return None
    work = servers.get(WORK_MCP_NAME)
    if not isinstance(work, dict) or work.get("status") == "error":
        return None
    if work.get("status") == "unknown":
        return None

    observed = list_process_cmdlines() if cmdlines is None else cmdlines
    if observed is None:
        return None

    sibling_live = False
    for name, entry in configured.items():
        if name == WORK_MCP_NAME or name not in SERVER_MODULES:
            continue
        sibling_path = script_path_for(name, entry if isinstance(entry, dict) else None)
        if sibling_path is not None and script_is_live(sibling_path, observed):
            sibling_live = True
            break
    if not sibling_live:
        return None

    work_path = script_path_for(
        WORK_MCP_NAME,
        configured[WORK_MCP_NAME] if isinstance(configured[WORK_MCP_NAME], dict) else None,
    )
    if work_path is None or script_is_live(work_path, observed):
        return None

    return {
        "status": "error",
        "error": NEVER_SPAWNED_HUMAN_ERROR,
        "humanError": NEVER_SPAWNED_HUMAN_ERROR,
    }


def apply_never_spawned_overlay(
    health: dict,
    *,
    cmdlines: list[str] | None = None,
    entries: dict | None = None,
) -> dict:
    """Return health with a fresh work-mcp live-process overlay; never writes cache."""
    servers = health.get("servers")
    if not isinstance(servers, dict):
        return health
    notice = never_spawned_work_mcp_result(
        servers, cmdlines=cmdlines, entries=entries
    )
    if notice is None:
        return health
    overlaid = dict(health)
    overlaid_servers = dict(servers)
    work = dict(overlaid_servers.get(WORK_MCP_NAME) or {})
    work.update(notice)
    overlaid_servers[WORK_MCP_NAME] = work
    overlaid["servers"] = overlaid_servers
    return overlaid


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
    mcp_dir = Path(get_vault_path()) / "core" / "mcp"
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
        return apply_never_spawned_overlay(health)

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

    # Write cached file-check results only. Live-process overlay is always fresh.
    try:
        health_path.write_text(json.dumps(health, indent=2))
    except IOError:
        pass

    return apply_never_spawned_overlay(health)


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
