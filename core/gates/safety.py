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
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.path_safety import unsafe_existing_parent
from core.vault_folders import mkdir_targets, new_top_level_folder_reason, shell_write_targets
from core.vault_selection import VaultSelectionError, select_vault

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
CODE_PROTECTED_LOCATION = "protected_location"
CODE_NEW_TOP_LEVEL_FOLDER = "new_top_level_folder"
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
REASON_PROTECTED_LOCATION = "Blocked: system or home-root folder"
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
_PROTECTED_SYSTEM_PREFIXES = (
    "/etc",
    "/System",
    "/usr",
    "/bin",
    "/sbin",
    "/Library",
    "/opt",
    "/root",
    "/Applications",
)
_PROTECTED_VAR_PREFIXES = ("/var", "/private")
_PROTECTED_HOME_CHILDREN = frozenset({"Library", ".ssh", ".gnupg", ".config", ".claude"})
_FOREIGN_HOME_ROOTS = frozenset({"Users", "home"})
_WINDOWS_PROTECTED = re.compile(
    r"^[A-Za-z]:[\\/](?:Windows|Program Files)",
    re.IGNORECASE,
)
MIGRATION_LOCK_RELATIVE = Path("System") / ".dex" / "mutation.lock"
# Temp-root values that must never become an outside-vault allowance. Home
# itself is checked separately so a Windows temp folder under the profile
# can still be used as scratch.
_UNSAFE_TEMP_ROOTS = frozenset(
    {
        "/",
        "/Users",
        "/home",
        "/etc",
        "/System",
        "/usr",
        "/bin",
        "/sbin",
        "/Library",
        "/opt",
        "/var",
        "/private",
        "/root",
        "/Applications",
    }
)
_TEMP_ENV_PREFIXES = (
    ("TMPDIR", "$TMPDIR/"),
    ("TEMP", "$TEMP/"),
    ("TMP", "$TMP/"),
)


def _is_temp_env_specifier(candidate: str) -> bool:
    """True for $TMPDIR/$TEMP/$TMP, with or without a path under them."""
    for _env_name, prefix in _TEMP_ENV_PREFIXES:
        if candidate == prefix[:-1] or candidate.startswith(prefix):
            return True
    return False


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
    """Resolve a selected vault without silently overriding configuration."""
    return select_vault(explicit=explicit)


def refusal(reason: str, code: str = "invalid_tool_input") -> GateDecision:
    return GateDecision(DECISION_BLOCK, reason, code, 2)


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


def _is_catastrophic_path(candidate: str) -> bool:
    collapsed = candidate.rstrip("/\\") or "/"
    return collapsed in CATASTROPHIC_BARE_PATHS


def _is_unjoined_shell_target(candidate: str) -> bool:
    """True when the caller named an absolute, home, or temp path, not cwd-relative."""
    if not candidate:
        return False
    if _is_catastrophic_path(candidate) or _is_temp_env_specifier(candidate):
        return True
    if candidate.startswith(("~/", "$HOME/", "~\\", "$HOME\\")):
        return True
    try:
        return Path(candidate).is_absolute()
    except (OSError, TypeError, ValueError):
        return False


def _claude_project_slugs(vault: Path) -> frozenset[str]:
    """Claude Code's project folder name: every non-alphanumeric character becomes '-'."""
    slugs = {re.sub(r"[^A-Za-z0-9]", "-", raw) for raw in {str(vault), str(vault.resolve())}}
    named = os.environ.get("CLAUDE_CODE_PROJECT_DIR_NAME", "").strip()
    if named and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,200}", named):
        slugs.add(named)
    return frozenset(slugs)


def _claude_config_bases() -> list[Path]:
    bases = [Path.home() / ".claude"]
    configured = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if configured:
        try:
            bases.append(Path(configured).expanduser())
        except (OSError, TypeError, ValueError):
            pass
    return bases


def _absolute_home_or_literal(candidate: str) -> Path | None:
    """Expand only the home prefixes this gate already recognizes as shorthand."""
    collapsed = candidate.rstrip("/\\") or candidate
    if collapsed in {"~", "$HOME"}:
        return Path.home()
    if candidate.startswith("~/"):
        return Path.home() / candidate[2:]
    if candidate.startswith("$HOME/"):
        return Path.home() / candidate[6:]
    if candidate.startswith("~\\"):
        return Path.home() / candidate[2:]
    if candidate.startswith("$HOME\\"):
        return Path.home() / candidate[6:]
    try:
        path = Path(candidate)
    except (OSError, TypeError, ValueError):
        return None
    return path if path.is_absolute() else None


def _expand_temp_shorthand(candidate: str) -> Path | None:
    """Expand $TMPDIR/$TEMP/$TMP prefixes, or return an absolute literal path."""
    expanded = _absolute_home_or_literal(candidate)
    if expanded is not None:
        return expanded
    for env_name, prefix in _TEMP_ENV_PREFIXES:
        if candidate == prefix[:-1]:
            raw = os.environ.get(env_name, "").strip()
            return Path(raw) if raw else None
        if candidate.startswith(prefix):
            raw = os.environ.get(env_name, "").strip()
            if not raw:
                return None
            return Path(raw) / candidate[len(prefix) :]
    return None


def _temp_root_is_safe(root: Path) -> bool:
    """False when a claimed temp root is home, the filesystem root, or a system dir."""
    try:
        resolved = root.resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    collapsed = str(resolved).rstrip("/") or "/"
    if collapsed.startswith("/private/") and collapsed != "/private":
        # macOS: /etc, /tmp, and /var are shortcuts to /private/...
        collapsed = collapsed[len("/private") :] or "/"
    if collapsed in _UNSAFE_TEMP_ROOTS:
        return False
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    if resolved == home:
        return False
    try:
        home.relative_to(resolved)
    except ValueError:
        return True
    # The claimed temp root is an ancestor of home (for example TMPDIR=/tmp
    # while a test places HOME under /tmp). Too broad to treat as scratch.
    return False


def _macos_user_temp_root(resolved: Path) -> Path | None:
    """Return the real /var/folders/.../T root, not a lookalike under home."""
    parts = resolved.parts
    # Only the OS location: /var/folders/<id>/<id>/T or /private/var/folders/.../T.
    # A planted .../var/folders/.../T under $HOME or /usr/local is not scratch.
    if (
        len(parts) >= 6
        and parts[:3] == ("/", "var", "folders")
        and parts[5] == "T"
    ):
        return Path(*parts[:6])
    if (
        len(parts) >= 7
        and parts[:4] == ("/", "private", "var", "folders")
        and parts[6] == "T"
    ):
        return Path(*parts[:7])
    return None


def _recognized_temp_roots() -> tuple[Path, ...]:
    """Safe OS temp directories custom skills may scratch in."""
    roots: list[Path] = []
    seen: set[str] = set()

    def _add(raw: str | Path | None) -> None:
        if not raw:
            return
        try:
            candidate = Path(raw)
        except (OSError, TypeError, ValueError):
            return
        if not candidate.is_absolute():
            return
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError, TypeError, ValueError):
            return
        if not _temp_root_is_safe(resolved):
            return
        key = str(resolved)
        if key in seen:
            return
        seen.add(key)
        roots.append(resolved)

    _add(tempfile.gettempdir())
    for env_name, _prefix in _TEMP_ENV_PREFIXES:
        _add(os.environ.get(env_name, "").strip())
    for well_known in ("/tmp", "/private/tmp", "/var/tmp"):
        _add(well_known)
    return tuple(roots)


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_os_temp_path(candidate: str) -> bool:
    """True for files under the OS temp directory (and well-known temp roots).

    Custom skills scratch here. The vault, home, and system paths stay
    protected: a symlink or ``..`` that resolves outside a recognized temp
    root is not allowed. A ``$TMPDIR/...`` specifier must stay under that
    env root, not merely land somewhere else that is also temp.
    """
    target = _expand_temp_shorthand(candidate)
    if target is None:
        return False
    try:
        resolved = target.resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    if _is_temp_env_specifier(candidate):
        for env_name, prefix in _TEMP_ENV_PREFIXES:
            if candidate != prefix[:-1] and not candidate.startswith(prefix):
                continue
            raw = os.environ.get(env_name, "").strip()
            if not raw:
                return False
            try:
                env_root = Path(raw).resolve()
            except (OSError, RuntimeError, TypeError, ValueError):
                return False
            return _temp_root_is_safe(env_root) and _is_under_root(resolved, env_root)
        return False
    for root in _recognized_temp_roots():
        if _is_under_root(resolved, root):
            return True
    macos_root = _macos_user_temp_root(resolved)
    if macos_root is None or not _temp_root_is_safe(macos_root):
        return False
    return _is_under_root(resolved, macos_root)


def _is_this_vault_claude_memory_path(candidate: str, vault: Path) -> bool:
    """True only for Claude Code's auto-memory folder for this vault.

    That folder lives outside the vault (``~/.claude/projects/<vault>/memory``),
    so the usual outside-vault rule would block Claude's own notes. The
    allowance is this one folder, not ``~/.claude`` and not another project.
    """
    target = _absolute_home_or_literal(candidate)
    if target is None:
        return False
    try:
        resolved = target.resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    slugs = _claude_project_slugs(vault)
    home = Path.home().resolve()
    for base in _claude_config_bases():
        try:
            base_resolved = base.expanduser().resolve()
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if base_resolved in {Path("/"), home} or str(base_resolved) in {"/Users", "/home"}:
            continue
        configured = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
        if not configured and base_resolved.name != ".claude":
            continue
        for slug in slugs:
            # Build the expected folder from parts so a planted symlink at
            # memory/ cannot retarget the allowance at /etc or $HOME.
            expected = base_resolved / "projects" / slug / "memory"
            try:
                resolved.relative_to(expected)
            except ValueError:
                continue
            return True
    return False


def _path_for_location_check(candidate: str) -> Path | None:
    """Expand home/temp shorthand, or return an absolute or relative Path."""
    expanded = _expand_temp_shorthand(candidate)
    if expanded is not None:
        return expanded
    try:
        return Path(candidate)
    except (OSError, TypeError, ValueError):
        return None


def _resolved_home() -> Path | None:
    try:
        return Path.home().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _is_inside_vault(candidate: str, vault: Path) -> bool:
    """True when the named path sits under the vault before following symlinks.

    A vault-relative mkdir whose parent is a symlink still uses the in-vault
    checks (escape protection and DEX-116). Following the symlink first would
    reclassify that target as an outside-vault write.
    """
    target = _path_for_location_check(candidate)
    if target is None:
        return False
    if not target.is_absolute():
        target = vault / target
    lexical = Path(os.path.normpath(str(target)))
    for root in (vault,):
        try:
            roots = {root, root.resolve()}
        except (OSError, RuntimeError, TypeError, ValueError):
            roots = {root}
        for base in roots:
            try:
                lexical.relative_to(Path(os.path.normpath(str(base))))
            except (OSError, ValueError):
                continue
            return True
    return False


def _is_direct_root_child(resolved: Path) -> bool:
    return len(resolved.parts) == 2 and resolved.parts[0] == "/"


def _is_foreign_user_tree(resolved: Path, home: Path | None) -> bool:
    """True for /Users, /home, and another user's directory under them."""
    parts = resolved.parts
    if len(parts) < 2 or parts[0] != "/" or parts[1] not in _FOREIGN_HOME_ROOTS:
        return False
    if home is not None:
        try:
            resolved.relative_to(home)
        except ValueError:
            return True
        else:
            return False
    return True


def _is_under_system_prefix(resolved: Path, prefix: str) -> bool:
    root = Path(prefix)
    if _is_under_root(resolved, root) or resolved == root:
        return True
    try:
        resolved_root = root.resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    collapsed = str(resolved_root).rstrip("/") or "/"
    if collapsed in {"/", "/Users", "/home"}:
        return False
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        home = None
    if home is not None and resolved_root == home:
        return False
    return _is_under_root(resolved, resolved_root) or resolved == resolved_root


def _is_windows_protected_path(candidate: str, resolved: Path) -> bool:
    for raw in (candidate, str(resolved)):
        normalized = raw.replace("/", "\\")
        if _WINDOWS_PROTECTED.match(normalized):
            return True
    return False


def _protected_location_reason(path: Any, vault: Path | None) -> str | None:
    """Refuse catastrophic, system, and private home locations; allow ordinary folders."""
    candidate = _safe_string(path)
    if not candidate:
        return None
    if vault is not None and _is_this_vault_claude_memory_path(candidate, vault):
        return None
    if _is_os_temp_path(candidate):
        return None
    if _is_catastrophic_path(candidate):
        return REASON_PROTECTED_LOCATION
    target = _path_for_location_check(candidate)
    if target is None:
        return REASON_PROTECTED_LOCATION
    try:
        resolved = target.expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return REASON_PROTECTED_LOCATION
    home = _resolved_home()
    if home is not None and resolved == home:
        return REASON_PROTECTED_LOCATION
    if _is_direct_root_child(resolved):
        return REASON_PROTECTED_LOCATION
    if _is_foreign_user_tree(resolved, home):
        return REASON_PROTECTED_LOCATION
    for prefix in _PROTECTED_SYSTEM_PREFIXES:
        if _is_under_system_prefix(resolved, prefix):
            return REASON_PROTECTED_LOCATION
    for prefix in _PROTECTED_VAR_PREFIXES:
        if _is_under_system_prefix(resolved, prefix):
            return REASON_PROTECTED_LOCATION
    if _is_windows_protected_path(candidate, resolved):
        return REASON_PROTECTED_LOCATION
    if home is not None:
        for name in _PROTECTED_HOME_CHILDREN:
            protected_root = home / name
            if resolved == protected_root or _is_under_root(resolved, protected_root):
                return REASON_PROTECTED_LOCATION
    return None


def _unsafe_path_reason(path: Any, vault: Path | None) -> str | None:
    # File tools use literal names. Trimming whitespace or expanding shell
    # variables can judge a different inode and hide an escaping symlink.
    candidate = _safe_string(path)
    if not candidate:
        return None
    if vault is not None and _is_this_vault_claude_memory_path(candidate, vault):
        return None
    if _is_catastrophic_path(candidate):
        return REASON_UNSAFE_PATH
    if vault is None:
        return None

    expanded = _absolute_home_or_literal(candidate)
    try:
        expanded_path = expanded if expanded is not None else Path(candidate)
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
        # The parent-only helper does not inspect a symlink in the final target.
        (vault / expanded_path).resolve().relative_to(vault.resolve())
    except (OSError, RuntimeError, TypeError, ValueError):
        return REASON_UNSAFE_PATH
    return REASON_UNSAFE_PATH if reason else None


def _resolve_shell_target(target: str, workdir: Path) -> str:
    if _is_unjoined_shell_target(target):
        return target
    return str(workdir / target)


def _shell_target_decision(
    target: str,
    *,
    root: Path,
    workdir: Path,
    allow_os_temp: bool,
    as_directory: bool,
) -> GateDecision | None:
    """Refuse one mkdir/write operand, or None when the shell target is allowed."""
    resolved_target = _resolve_shell_target(target, workdir)
    if _is_catastrophic_path(target) or _is_catastrophic_path(resolved_target):
        return GateDecision(
            DECISION_BLOCK, REASON_PROTECTED_LOCATION, CODE_PROTECTED_LOCATION, 2
        )
    if allow_os_temp and _is_os_temp_path(target):
        return None
    if _is_temp_env_specifier(target):
        return GateDecision(DECISION_BLOCK, REASON_UNSAFE_PATH, CODE_UNSAFE_PATH, 2)
    if _is_inside_vault(resolved_target, root):
        if not as_directory:
            return None
        target_path_reason = _unsafe_path_reason(resolved_target, root)
        if target_path_reason:
            return GateDecision(DECISION_BLOCK, target_path_reason, CODE_UNSAFE_PATH, 2)
        target_folder_reason = new_top_level_folder_reason(
            root, resolved_target, as_directory=True
        )
        if target_folder_reason:
            return GateDecision(
                DECISION_BLOCK, target_folder_reason, CODE_NEW_TOP_LEVEL_FOLDER, 2
            )
        return None
    protected = _protected_location_reason(resolved_target, root)
    if protected:
        return GateDecision(DECISION_BLOCK, protected, CODE_PROTECTED_LOCATION, 2)
    return None


def evaluate_safety_gate(
    *,
    tool_name: Any = "",
    command: Any = "",
    path: Any = "",
    vault: str | Path | None = None,
    cwd: str | Path | None = None,
    as_directory: bool = False,
    allow_os_temp: bool = True,
) -> GateDecision:
    """Refuse known destructive commands and paths; warnings still allow."""
    _ = tool_name  # Reserved for future shared interceptors.
    try:
        root = resolve_vault(vault)
    except VaultSelectionError as exc:
        return refusal(str(exc), exc.code)
    command_text = _safe_string(command)
    path_text = _safe_string(path)
    try:
        workdir = Path(cwd).expanduser().resolve() if cwd is not None else root
    except (OSError, RuntimeError, TypeError, ValueError):
        workdir = root

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

    path_is_os_temp = allow_os_temp and _is_os_temp_path(path_text)
    if _is_temp_env_specifier(path_text) and not path_is_os_temp:
        return GateDecision(DECISION_BLOCK, REASON_UNSAFE_PATH, CODE_UNSAFE_PATH, 2)
    if not path_is_os_temp:
        path_reason = _unsafe_path_reason(path_text, root)
        if path_reason:
            return GateDecision(DECISION_BLOCK, path_reason, CODE_UNSAFE_PATH, 2)
        folder_as_directory = as_directory or path_text.endswith(("/", "\\"))
        folder_reason = new_top_level_folder_reason(root, path_text, as_directory=folder_as_directory)
        if folder_reason:
            return GateDecision(DECISION_BLOCK, folder_reason, CODE_NEW_TOP_LEVEL_FOLDER, 2)
    if command_text:
        for target in mkdir_targets(command_text):
            decision = _shell_target_decision(
                target,
                root=root,
                workdir=workdir,
                allow_os_temp=allow_os_temp,
                as_directory=True,
            )
            if decision is not None:
                return decision
        for target in shell_write_targets(command_text):
            decision = _shell_target_decision(
                target,
                root=root,
                workdir=workdir,
                allow_os_temp=allow_os_temp,
                as_directory=False,
            )
            if decision is not None:
                return decision
        if CHMOD_777.search(command_text):
            return GateDecision(DECISION_ALLOW, REASON_CHMOD_777, CODE_CHMOD_777, 0)
        if KILL_9.search(command_text):
            return GateDecision(DECISION_ALLOW, REASON_KILL_9, CODE_KILL_9, 0)
    return ALLOW


# These are input fields, not a claim that arbitrary MCP schemas are understood.
PATH_FIELDS = ("file_path", "path", "notebook_path", "source", "destination", "source_path", "destination_path")
FILE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit", "Delete", "write_file", "replace"})
SHELL_TOOLS = frozenset({"Bash", "Shell", "exec_command", "shell_command", "run_shell_command"})


def read_hook_event(payload: Mapping[str, Any]) -> str | None:
    """Normalize recognized event names without defaulting missing/malformed input."""
    aliases = {"PreToolUse": "PreToolUse", "preToolUse": "PreToolUse", "BeforeTool": "PreToolUse",
               "SessionStart": "SessionStart", "sessionStart": "SessionStart"}
    values = [payload[key] for key in ("hook_event_name", "hookEventName") if key in payload]
    if not values or any(not isinstance(value, str) or value not in aliases for value in values):
        return None
    normalized = {aliases[value] for value in values}
    return normalized.pop() if len(normalized) == 1 else None


def evaluate_hook_payload(payload: Mapping[str, Any] | None, *, vault: str | Path | None = None) -> GateDecision:
    """Check all exposed action targets, refusing malformed intercepted events.

    Unknown tools with object inputs still have recognized fields checked. Opaque
    server-specific arguments and shell-language indirection are not a sandbox.
    """
    if not isinstance(payload, Mapping):
        return refusal("Blocked: invalid safety hook payload.")
    if read_hook_event(payload) != "PreToolUse":
        return refusal("Blocked: unknown or missing safety hook event.")
    tool = payload.get("tool_name")
    raw_input = payload.get("tool_input")
    if not isinstance(tool, str) or not tool.strip():
        return refusal("Blocked: safety hook is missing a tool name.")
    if tool == "apply_patch" and isinstance(raw_input, str):
        raw_input = {"command": raw_input}
    if not isinstance(raw_input, Mapping):
        return refusal("Blocked: safety hook requires an object tool input.")
    if "vault_path" in payload and not isinstance(payload["vault_path"], str):
        return refusal("Blocked: invalid explicit vault selection.", "vault_selection_conflict")
    if "cwd" in payload and not isinstance(payload["cwd"], str):
        return refusal("Blocked: invalid hook working directory.", "vault_selection_conflict")
    working_directory = payload.get("cwd", Path.cwd())
    try:
        root = select_vault(explicit=vault if vault is not None else payload.get("vault_path"),
                            cwd=working_directory, workspace_roots=payload.get("workspace_roots"))
        if vault is not None and "vault_path" in payload:
            if select_vault(explicit=payload["vault_path"]) != root:
                raise VaultSelectionError("Blocked: explicit vault selections conflict.")
    except VaultSelectionError as exc:
        return refusal(str(exc), exc.code)
    base = Path(working_directory or root).expanduser().resolve()
    paths: list[str] = []
    commands: list[str] = []
    for key in PATH_FIELDS:
        for source in (raw_input, payload) if key == "path" else (raw_input,):
            if key in source:
                value = source[key]
                if not isinstance(value, str) or not value.strip():
                    return refusal("Blocked: invalid action path.")
                paths.append(value)
    for key in ("command", "cmd"):
        if key in raw_input:
            value = raw_input[key]
            if not isinstance(value, str) or not value.strip():
                return refusal("Blocked: invalid action command.")
            commands.append(value)
    if tool == "apply_patch":
        patches = [raw_input[key] for key in ("command", "patch", "input") if key in raw_input]
        if not patches:
            return refusal("Blocked: patch input is missing.")
        for patch in patches:
            if not isinstance(patch, str):
                return refusal("Blocked: invalid patch input.")
            lines = patch.strip().splitlines()
            if not lines or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
                return refusal("Blocked: patch format cannot be checked.")
            targets = [line.split(": ", 1)[1] for line in lines
                       if line.startswith(("*** Add File: ", "*** Update File: ",
                                           "*** Delete File: ", "*** Move to: "))]
            if not targets or any(not target.strip() for target in targets):
                return refusal("Blocked: patch targets cannot be checked.")
            paths.extend(targets)
        # Patch content is data, not shell; only its target headers are actions.
        commands = []
    if tool in FILE_TOOLS and not paths:
        return refusal("Blocked: file action has no inspectable target.")
    if tool in SHELL_TOOLS and not commands:
        return refusal("Blocked: shell action has no inspectable command.")
    warning = ALLOW
    for command in commands:
        decision = evaluate_safety_gate(tool_name=tool, command=command, vault=root, cwd=base)
        if decision.refused:
            return decision
        if decision.reason:
            warning = decision
    for path in paths:
        # Relative paths are relative to the host's working directory, which
        # may be below the selected vault root. Preserve explicit root/home
        # refusals, but treat all other prefixes as literal filename characters.
        # Temp allowance is for paths the caller named as scratch (/tmp,
        # $TMPDIR, …). A relative path joined onto a vault that happens to
        # live under /tmp is not scratch — it still has to stay in the vault.
        if _is_os_temp_path(path):
            target = path
            allow_os_temp = True
        elif _is_unjoined_shell_target(path):
            target = path
            allow_os_temp = False
        else:
            target = str(base / path)
            allow_os_temp = False
        decision = evaluate_safety_gate(
            tool_name=tool, path=target, vault=root, allow_os_temp=allow_os_temp
        )
        if decision.refused:
            return decision
    return warning


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refuse destructive commands and unsafe paths")
    parser.add_argument("--hook", action="store_true", help="Read Claude PreToolUse JSON on stdin; exit 2 to block")
    parser.add_argument("--vault", default=None, help="Vault root")
    parser.add_argument("--tool-name", default="", help="Tool name (MCP path)")
    parser.add_argument("--command", default="", help="Shell command to evaluate")
    parser.add_argument("--path", default="", help="Filesystem path to evaluate")
    parser.add_argument("--format", choices=("json", "hook-json"), default="json")
    args = parser.parse_args(argv)
    vault = args.vault
    if args.hook:
        raw = sys.stdin.read()
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = None
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
