#!/usr/bin/env python3
"""Destructive-command and unsafe-path gate shared by MCP and Claude.

The MCP result is advisory: a non-Claude harness must invoke this check before
its own tool call, and only a verified pre-tool interceptor can enforce a
refusal. Claude's wrapper exits 2 after the same function returns a block.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.path_safety import unsafe_existing_parent


DECISION_BLOCK = "block"
DECISION_ALLOW = "allow"

CODE_ALLOW = "allow"
CODE_MIGRATION_LOCK = "migration_lock"
CODE_DESTRUCTIVE_RM_ROOT = "destructive_rm_root"
CODE_DESTRUCTIVE_RM_RF_SLASH = "destructive_rm_rf_slash"
CODE_DISK_WIPE = "disk_wipe"
CODE_FORCE_PUSH_MAIN = "force_push_main"
CODE_SQL_DROP = "sql_drop"
CODE_GITHUB_REPO_DELETE = "github_repo_delete"
CODE_UNSAFE_PATH = "unsafe_path"
CODE_CHMOD_777 = "chmod_777"
CODE_KILL_9 = "kill_9"

REASON_MIGRATION_LOCK = (
    "A brain/vault migration is active. Do not use raw Git repair commands. "
    "Run the migrator with --resume to continue or --restore to return to "
    "the pre-split layout."
)
REASON_RM_ROOT = "Blocked: recursive delete targeting root, home, or /Users"
REASON_RM_RF_SLASH = "Blocked: rm -rf /"
REASON_DISK_WIPE = "Blocked: disk wipe/format command"
REASON_FORCE_PUSH = "Blocked: force push to main/master"
REASON_SQL_DROP = "Blocked: SQL DROP command"
REASON_GITHUB_DELETE = "Blocked: GitHub repo deletion"
REASON_UNSAFE_PATH = "Blocked: unsafe path (root, home, or outside the vault)"
REASON_CHMOD_777 = (
    "WARNING: chmod 777 grants full permissions to all users. "
    "Consider more restrictive permissions."
)
REASON_KILL_9 = (
    "WARNING: kill -9 force-terminates without cleanup. "
    "Ensure this is the intended process."
)

GIT_MUTATION = re.compile(
    r"(^|[;&|\s])git\s+"
    r"(add|am|apply|bisect\s+(good|bad|reset|start)|"
    r"branch\s+.*(-[dDmM]|--delete|--move)|"
    r"checkout|cherry-pick|clean|commit|merge|mv|rebase|reset|"
    r"restore|revert|rm|stash|switch|tag)"
    r"([\s;&]|$)"
)
RM_ROOT = re.compile(
    r"rm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)?(-[a-zA-Z]*r[a-zA-Z]*\s+)?"
    r"(/|~/?(?:\s|$)|\"\$HOME\"|/Users)"
)
RM_RF_SLASH = re.compile(r"rm\s+-rf\s+/")
DISK_WIPE = re.compile(r"(diskutil\s+eraseDisk|mkfs\s|dd\s+if=)", re.IGNORECASE)
FORCE_PUSH_MAIN = re.compile(
    r"git\s+push\s+.*(--force.*\s+(main|master)|\s+(main|master).*--force)"
)
SQL_DROP = re.compile(r"(DROP\s+TABLE|DROP\s+DATABASE)", re.IGNORECASE)
GITHUB_REPO_DELETE = re.compile(r"gh\s+repo\s+delete")
CHMOD_777 = re.compile(r"chmod\s+777")
KILL_9 = re.compile(r"kill\s+-9")
CATASTROPHIC_BARE_PATHS = frozenset({"/", "~", "$HOME", "/Users"})
MIGRATION_LOCK_RELATIVE = Path("System") / ".dex" / "mutation.lock"


@dataclass(frozen=True)
class GateDecision:
    """Allow, warn, or refuse one proposed action."""

    decision: str
    reason: str
    code: str
    hook_exit: int

    @property
    def refused(self) -> bool:
        return self.decision == DECISION_BLOCK

    def as_payload(self) -> dict[str, Any]:
        return {
            "success": not self.refused,
            "refused": self.refused,
            "decision": self.decision,
            "reason": self.reason,
            "code": self.code,
        }

    def as_hook_json(self) -> str:
        return json.dumps({"decision": self.decision, "reason": self.reason}, ensure_ascii=True)


ALLOW = GateDecision(DECISION_ALLOW, "", CODE_ALLOW, 0)


def _safe_string(value: Any) -> str:
    try:
        return "" if value is None else str(value)
    except Exception:
        return ""


def process_is_running(pid: Any) -> bool:
    """True when *pid* is live; query-only and never sends a kill."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            handle = kernel32.OpenProcess(0x1000 | 0x00100000, False, pid)
            if not handle:
                return ctypes.get_last_error() == 5
            try:
                return kernel32.WaitForSingleObject(handle, 0) != 0
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (OSError, OverflowError, ValueError):
        return False


def resolve_vault(explicit: str | Path | None = None) -> Path:
    """Resolve an explicit vault, environment vault, or current directory."""
    candidate: Any = explicit
    if candidate is None:
        for key in ("CLAUDE_PROJECT_DIR", "VAULT_PATH"):
            value = os.environ.get(key)
            if value:
                candidate = value
                break
    if candidate is None:
        candidate = Path.cwd()
    try:
        return Path(candidate).expanduser()
    except (TypeError, ValueError, OSError):
        return Path.cwd()


def _migration_lock_is_live(vault: Path) -> bool:
    lock_path = vault / MIGRATION_LOCK_RELATIVE
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or payload.get("kind") != "migration":
        return False
    try:
        pid = int(payload["pid"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return process_is_running(pid)


def _unsafe_path_reason(path: Any, vault: Path | None) -> str | None:
    candidate = _safe_string(path).strip()
    if not candidate:
        return None
    collapsed = candidate.rstrip("/") or "/"
    if collapsed in CATASTROPHIC_BARE_PATHS or candidate.startswith(("~/", "$HOME/")):
        return REASON_UNSAFE_PATH
    if vault is None:
        return None

    try:
        expanded = os.path.expanduser(os.path.expandvars(candidate))
        expanded_path = Path(expanded)
    except (OSError, TypeError, ValueError):
        return REASON_UNSAFE_PATH
    if expanded_path.is_absolute():
        try:
            expanded_path.resolve().relative_to(vault.resolve())
        except (OSError, ValueError):
            return REASON_UNSAFE_PATH
        return None
    try:
        reason = unsafe_existing_parent(vault, candidate)
    except (OSError, TypeError, ValueError):
        return REASON_UNSAFE_PATH
    return REASON_UNSAFE_PATH if reason else None


def evaluate_safety_gate(
    *,
    tool_name: Any = "",
    command: Any = "",
    path: Any = "",
    vault: str | Path | None = None,
) -> GateDecision:
    """Refuse known destructive commands and paths; warnings still allow."""
    _ = tool_name  # Reserved for future shared interceptors.
    root = resolve_vault(vault)
    command_text = _safe_string(command)
    path_text = _safe_string(path)

    if command_text and _migration_lock_is_live(root) and GIT_MUTATION.search(command_text):
        return GateDecision(DECISION_BLOCK, REASON_MIGRATION_LOCK, CODE_MIGRATION_LOCK, 2)
    if command_text:
        if RM_ROOT.search(command_text):
            return GateDecision(DECISION_BLOCK, REASON_RM_ROOT, CODE_DESTRUCTIVE_RM_ROOT, 2)
        if RM_RF_SLASH.search(command_text):
            return GateDecision(DECISION_BLOCK, REASON_RM_RF_SLASH, CODE_DESTRUCTIVE_RM_RF_SLASH, 2)
        if DISK_WIPE.search(command_text):
            return GateDecision(DECISION_BLOCK, REASON_DISK_WIPE, CODE_DISK_WIPE, 2)
        if FORCE_PUSH_MAIN.search(command_text):
            return GateDecision(DECISION_BLOCK, REASON_FORCE_PUSH, CODE_FORCE_PUSH_MAIN, 2)
        if SQL_DROP.search(command_text):
            return GateDecision(DECISION_BLOCK, REASON_SQL_DROP, CODE_SQL_DROP, 2)
        if GITHUB_REPO_DELETE.search(command_text):
            return GateDecision(DECISION_BLOCK, REASON_GITHUB_DELETE, CODE_GITHUB_REPO_DELETE, 2)

    path_reason = _unsafe_path_reason(path_text, root)
    if path_reason:
        return GateDecision(DECISION_BLOCK, path_reason, CODE_UNSAFE_PATH, 2)
    if command_text:
        if CHMOD_777.search(command_text):
            return GateDecision(DECISION_ALLOW, REASON_CHMOD_777, CODE_CHMOD_777, 0)
        if KILL_9.search(command_text):
            return GateDecision(DECISION_ALLOW, REASON_KILL_9, CODE_KILL_9, 0)
    return ALLOW


def evaluate_hook_payload(payload: Mapping[str, Any] | None, *, vault: str | Path | None = None) -> GateDecision:
    """Evaluate one Claude Code PreToolUse JSON object safely."""
    data: Mapping[str, Any] = payload if isinstance(payload, Mapping) else {}
    raw_input = data.get("tool_input")
    tool_input: Mapping[str, Any] = raw_input if isinstance(raw_input, Mapping) else {}
    command = tool_input.get("command") or ""
    path = tool_input.get("file_path") or tool_input.get("path") or data.get("path") or ""
    return evaluate_safety_gate(
        tool_name=data.get("tool_name") or "",
        command=command,
        path=path,
        vault=vault,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refuse destructive commands and unsafe paths")
    parser.add_argument("--hook", action="store_true", help="Read Claude PreToolUse JSON on stdin; exit 2 to block")
    parser.add_argument("--vault", default=None, help="Vault root")
    parser.add_argument("--tool-name", default="", help="Tool name (MCP path)")
    parser.add_argument("--command", default="", help="Shell command to evaluate")
    parser.add_argument("--path", default="", help="Filesystem path to evaluate")
    parser.add_argument("--format", choices=("json", "hook-json"), default="json")
    args = parser.parse_args(argv)
    vault = resolve_vault(args.vault)
    if args.hook:
        raw = sys.stdin.read()
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return 0
        if not isinstance(payload, dict):
            return 0
        decision = evaluate_hook_payload(payload, vault=vault)
        if decision.reason:
            sys.stdout.write(decision.as_hook_json() + "\n")
        return decision.hook_exit

    decision = evaluate_safety_gate(
        tool_name=args.tool_name,
        command=args.command,
        path=args.path,
        vault=vault,
    )
    if args.format == "hook-json":
        if decision.reason:
            sys.stdout.write(decision.as_hook_json() + "\n")
        return decision.hook_exit
    json.dump(decision.as_payload(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if not decision.refused else 2


if __name__ == "__main__":
    raise SystemExit(main())
