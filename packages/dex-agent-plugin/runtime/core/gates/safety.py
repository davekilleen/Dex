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
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.path_safety import unsafe_existing_parent
from core.vault_folders import mkdir_targets, new_top_level_folder_reason
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
CATASTROPHIC_BARE_PATHS = frozenset({"/", "~", "$HOME", "${HOME}", "/Users"})
_STRICT_MKDIR_FLAGS = frozenset({"-p", "--parents"})
_STRICT_MKDIR_PATH_CHARS = re.compile(r"^[A-Za-z0-9._/~-]+$")
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
    "/dev",
    "/proc",
    "/sys",
    "/run",
    "/boot",
)
_PROTECTED_VAR_PREFIXES = ("/var", "/private")
# Named denylist plus the leading-dot rule in _protected_location_reason.
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


def _is_recognized_braced_home(candidate: str) -> bool:
    """True for exact ``${HOME}`` or ``${HOME}/rest`` (backslash too)."""
    if not candidate.startswith("${HOME}"):
        return False
    rest = candidate[len("${HOME}") :]
    return rest == "" or rest[:1] in {"/", "\\"}


def _is_unparsed_braced_home(candidate: str) -> bool:
    """True for ``${HOME…}`` spellings that are not exact ``${HOME}`` / ``${HOME}/rest``.

    Bash parameter forms such as ``${HOME:0}`` are not evaluated. Callers fail
    closed instead of treating them as cwd-relative names.
    """
    return candidate.startswith("${HOME") and not _is_recognized_braced_home(candidate)


def _parse_home_shorthand(candidate: str) -> tuple[str, str] | None:
    """Split a current-user home spelling into ("", rest).

    Recognizes ``~``, ``$HOME``, ``${HOME}``, ``~/rest``, ``$HOME/rest``,
    and ``${HOME}/rest`` (backslash separators too). Other ``~user`` forms
    are not expanded; file tools treat them as filenames.
    """
    if not candidate:
        return None
    if candidate == "~" or candidate.startswith("~/") or candidate.startswith("~\\"):
        rest = candidate[1:]
        if rest[:1] in {"/", "\\"}:
            rest = rest[1:]
        return ("", rest)
    if _is_recognized_braced_home(candidate):
        rest = candidate[len("${HOME}") :]
        return ("", rest[1:] if rest else "")
    if candidate.startswith("$HOME"):
        rest = candidate[len("$HOME") :]
        if rest == "" or rest[:1] in {"/", "\\"}:
            return ("", rest[1:] if rest else "")
        return None
    return None


def _join_under(base: Path, rest: str) -> Path:
    """Join *rest* onto *base* without discarding *base* when *rest* looks absolute."""
    base_s = str(base)
    trimmed = rest.lstrip("/\\")
    if not trimmed:
        return Path(base_s)
    return Path(os.path.join(base_s, trimmed))


def _has_parent_dir_component(path: str) -> bool:
    """True when any ``/`` or ``\\``-separated component is exactly ``..``."""
    return any(part == ".." for part in re.split(r"[/\\]", path))


def _collapse_slashes_and_dot_components(raw: str) -> str:
    """Collapse extra slashes and ``.`` components; leave ``..`` in place."""
    if raw == "":
        return raw
    unified = raw.replace("\\", "/")
    drive = ""
    if len(unified) >= 2 and unified[1] == ":" and unified[0].isalpha():
        drive = unified[:2]
        unified = unified[2:]
    is_abs = unified.startswith("/")
    parts = [part for part in unified.split("/") if part and part != "."]
    body = "/".join(parts)
    if is_abs:
        body = "/" + body if body else "/"
    return drive + body


def _normalize_write_path(path: Path) -> Path | None:
    """Collapse extra slashes and ``.``, then realpath the deepest existing parent.

    Does not lexically collapse ``..``. A remaining ``..`` component is
    unresolved: return None so callers refuse.
    """
    raw = _collapse_slashes_and_dot_components(str(path))
    if _has_parent_dir_component(raw):
        return None
    suffix: list[str] = []
    cursor = raw
    while cursor and not os.path.lexists(cursor):
        parent = os.path.dirname(cursor)
        name = os.path.basename(cursor)
        if parent == cursor:
            break
        if name:
            suffix.append(name)
        cursor = parent
    if cursor and os.path.lexists(cursor):
        try:
            cursor = os.path.realpath(cursor)
        except OSError:
            pass
    rebuilt = cursor
    for name in reversed(suffix):
        rebuilt = os.path.join(rebuilt, name)
    collapsed = _collapse_slashes_and_dot_components(rebuilt)
    if _has_parent_dir_component(collapsed):
        return None
    return Path(collapsed)


def _expand_parsed_home(parsed: tuple[str, str]) -> Path | None:
    username, rest = parsed
    if username:
        return None
    try:
        home = Path.home()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    joined = _join_under(home, rest) if rest else home
    return _normalize_write_path(joined)


def _is_unjoined_shell_target(candidate: str) -> bool:
    """True when the caller named an absolute, home, or temp path, not cwd-relative.

    Bare ``~word`` is a filename. Current-user ``~`` / ``~/...`` / ``$HOME``
    spellings are home, not cwd-relative names.
    """
    if not candidate:
        return False
    if _is_catastrophic_path(candidate) or _is_temp_env_specifier(candidate):
        return True
    if _is_unparsed_braced_home(candidate):
        return True
    if _parse_home_shorthand(candidate) is not None:
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
    """Expand recognized home shorthand, or return an absolute literal path."""
    parsed = _parse_home_shorthand(candidate)
    if parsed is not None:
        return _expand_parsed_home(parsed)
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
            return _join_under(Path(raw), candidate[len(prefix) :])
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
    """Expand home/temp shorthand, or return an absolute or relative Path.

    Current-user home shorthand that cannot be resolved returns None so callers
    fail closed. Unparsed ``${HOME…}`` forms fail closed the same way.
    """
    if _is_unparsed_braced_home(candidate):
        return None
    parsed = _parse_home_shorthand(candidate)
    if parsed is not None:
        expanded = _expand_parsed_home(parsed)
        return None if expanded is None else expanded
    expanded = _expand_temp_shorthand(candidate)
    if expanded is not None:
        return _normalize_write_path(expanded) if expanded.is_absolute() else expanded
    try:
        path = Path(candidate)
    except (OSError, TypeError, ValueError):
        return None
    if path.is_absolute():
        return _normalize_write_path(path)
    collapsed = _collapse_slashes_and_dot_components(str(path))
    if _has_parent_dir_component(collapsed):
        return None
    return Path(collapsed)


def _resolved_home() -> Path | None:
    try:
        return Path.home().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _is_inside_vault(candidate: str, vault: Path) -> bool:
    """True when the named path sits under the vault after home/symlink normalisation."""
    target = _path_for_location_check(candidate)
    if target is None:
        return False
    if not target.is_absolute():
        target = _join_under(vault, str(target))
    target = _normalize_write_path(target)
    if target is None:
        return False
    lexical = Path(os.path.normpath(str(target)))
    try:
        roots = {vault, vault.resolve()}
    except (OSError, RuntimeError, TypeError, ValueError):
        roots = {vault}
    for base in roots:
        try:
            lexical.relative_to(Path(os.path.normpath(str(base))))
        except (OSError, ValueError):
            continue
        return True
    return False


def _is_direct_root_child(resolved: Path) -> bool:
    return len(resolved.parts) == 2 and resolved.parts[0] == "/"


def _is_under_direct_root_child(resolved: Path) -> bool:
    """True when *resolved* is ``/name`` or a nested path that mkdir -p would create under ``/name``."""
    parts = resolved.parts
    if len(parts) < 2 or parts[0] != "/":
        return False
    return _is_direct_root_child(Path("/") / parts[1])


def _is_well_known_os_temp_path(resolved: Path) -> bool:
    """True for well-known OS scratch trees, compared case-insensitively."""
    return any(_path_has_prefix_ci(resolved, prefix) for prefix in _WELL_KNOWN_OS_TEMP_PREFIXES)


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


def _path_has_prefix_ci(resolved: Path, prefix: str) -> bool:
    """True when *resolved* is *prefix* or a child of it, ignoring case."""
    left = str(resolved).replace("\\", "/").rstrip("/") or "/"
    right = prefix.replace("\\", "/").rstrip("/") or "/"
    left_c = unicodedata.normalize("NFC", left).casefold()
    right_c = unicodedata.normalize("NFC", right).casefold()
    return left_c == right_c or left_c.startswith(right_c + "/")


def _is_under_system_prefix(resolved: Path, prefix: str) -> bool:
    if _path_has_prefix_ci(resolved, prefix):
        return True
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


_WINDOWS_POSIX_PROTECTED = re.compile(
    r"^/(?:mnt/)?[A-Za-z]/(?:Windows|Program Files)",
    re.IGNORECASE,
)
# Lexical OS-temp prefixes. _is_os_temp_path refuses a claimed temp root
# that is an ancestor of $HOME, which happens in pytest (HOME lives under
# /tmp). Nested mkdir under these prefixes is still ordinary scratch.
_WELL_KNOWN_OS_TEMP_PREFIXES = (
    "/tmp",
    "/private/tmp",
    "/var/tmp",
    "/private/var/tmp",
)


def _is_windows_protected_path(candidate: str, resolved: Path) -> bool:
    for raw in (candidate, str(resolved)):
        normalized = raw.replace("/", "\\")
        if _WINDOWS_PROTECTED.match(normalized):
            return True
        posix = raw.replace("\\", "/")
        if _WINDOWS_POSIX_PROTECTED.match(posix):
            return True
    return False


def _nfc_fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


# Decision 2 (gtm-lab #741): writes and mkdir are allowed *inside* a
# cloud-sync provider folder or an external drive, judged on the realpath.
# The containers themselves, the rest of ~/Library and the boot volume stay
# protected.
def _is_cloud_sync_path(home: Path, parts: tuple[str, ...]) -> bool:
    """True for ~/Library/CloudStorage/<provider>/… or iCloud Drive's folder/…."""
    if len(parts) < 4 or _nfc_fold(parts[0]) != "library":
        return False
    second = _nfc_fold(parts[1])
    if second == "cloudstorage":
        container = home / parts[0] / parts[1] / parts[2]
    elif second == "mobile documents" and _nfc_fold(parts[2]) == "com~apple~clouddocs":
        container = home / parts[0] / parts[1] / parts[2]
    else:
        return False
    try:
        return container.is_dir() and not container.is_symlink()
    except OSError:
        return False


def _volume_is_external_mount(mount: Path, home: Path | None) -> bool:
    """True when *mount* is a mounted drive other than the boot/system or home volume."""
    try:
        if mount.is_symlink() or not os.path.ismount(mount):
            return False
        device = os.stat(mount).st_dev
        if device == os.stat("/").st_dev:
            return False
        if home is not None and device == os.stat(home).st_dev:
            return False
    except OSError:
        return False
    return True


def _is_external_volume_path(resolved: Path, home: Path | None) -> bool:
    """True for /Volumes/<drive>/… on a real external mount (not the boot volume)."""
    parts = resolved.parts
    if len(parts) < 4 or parts[0] != "/" or _nfc_fold(parts[1]) != "volumes":
        return False
    return _volume_is_external_mount(Path("/") / parts[1] / parts[2], home)


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
    if home is not None and (resolved == home or _is_under_root(resolved, home)):
        # Judge the user's own tree before /var or /private: on macOS, pytest
        # (and some real homes) live under /private/var/folders/.../T.
        if resolved == home:
            return REASON_PROTECTED_LOCATION
        try:
            relative = resolved.relative_to(home)
        except ValueError:
            return None
        if relative.parts:
            first = relative.parts[0]
            first_folded = _nfc_fold(first)
            if _is_cloud_sync_path(home, relative.parts):
                return None
            if first.startswith(".") or first_folded == "library":
                return REASON_PROTECTED_LOCATION
            protected = {_nfc_fold(name) for name in _PROTECTED_HOME_CHILDREN}
            if first_folded in protected:
                return REASON_PROTECTED_LOCATION
        return None
    if _is_well_known_os_temp_path(resolved):
        return None
    if _is_external_volume_path(resolved, home):
        return None
    if _is_direct_root_child(resolved) or _is_under_direct_root_child(resolved):
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
    return None


def _unsafe_path_reason(path: Any, vault: Path | None) -> str | None:
    # File tools use literal names. Trimming whitespace or expanding shell
    # variables can judge a different inode and hide an escaping symlink.
    candidate = _safe_string(path)
    if not candidate:
        return None
    if _has_parent_dir_component(candidate):
        return REASON_UNSAFE_PATH
    if vault is not None and _is_this_vault_claude_memory_path(candidate, vault):
        return None
    if _is_catastrophic_path(candidate):
        return REASON_UNSAFE_PATH
    if vault is None:
        return None

    if _is_unparsed_braced_home(candidate):
        return REASON_UNSAFE_PATH
    parsed = _parse_home_shorthand(candidate)
    expanded: Path | None = None
    if parsed is not None:
        expanded = _expand_parsed_home(parsed)
        if expanded is None and not parsed[0]:
            return REASON_UNSAFE_PATH
        # Unknown ``~user/rest`` is a cwd-relative filename for file tools.
    try:
        expanded_path = expanded if expanded is not None else Path(candidate)
    except (OSError, TypeError, ValueError):
        return REASON_UNSAFE_PATH
    if expanded_path.is_absolute():
        expanded_path = _normalize_write_path(expanded_path)
        if expanded_path is None:
            return REASON_UNSAFE_PATH
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


def _is_strict_mkdir_path(path: str) -> bool:
    """True for one allow-listed mkdir operand.

    Optional leading ``~/``, ``$HOME/``, or ``${HOME}/``. The rest is only
    ``[A-Za-z0-9._/~-]``. No ``..`` segment and no ``~user``.
    """
    if not path:
        return False
    if any(part == ".." for part in path.split("/")):
        return False
    rest = path
    if path.startswith("~/"):
        rest = path[2:]
    elif path.startswith("$HOME/"):
        rest = path[6:]
    elif path.startswith("${HOME}/"):
        rest = path[8:]
    elif path.startswith("~") or path.startswith("$"):
        return False
    if rest == "":
        return True
    return _STRICT_MKDIR_PATH_CHARS.fullmatch(rest) is not None


def _parse_strict_mkdir_command(command: str) -> list[str] | None:
    """Return operands when *command* fully matches the outside-vault allow-list.

    The only matching form is ``mkdir`` with optional `` -p`` or `` --parents``,
    then one or more space-separated paths. Anything else is not this exception.
    """
    if not command or any(char in command for char in "\n\r\0"):
        return None
    parts = command.split(" ")
    if not parts or parts[0] != "mkdir":
        return None
    index = 1
    if index < len(parts) and parts[index] in _STRICT_MKDIR_FLAGS:
        index += 1
    paths = parts[index:]
    if not paths or any(part == "" for part in paths):
        return None
    if any(not _is_strict_mkdir_path(part) for part in paths):
        return None
    return paths


def _evaluate_allowed_mkdir_paths(
    paths: list[str],
    *,
    root: Path,
    workdir: Path,
    allow_os_temp: bool,
) -> GateDecision | None:
    """Refuse one allow-listed mkdir operand, or None when every path is allowed."""
    for target in paths:
        decision = _shell_target_decision(
            target,
            root=root,
            workdir=workdir,
            allow_os_temp=allow_os_temp,
            as_directory=True,
        )
        if decision is not None:
            return decision
    return None


def _resolve_shell_target(target: str, workdir: Path) -> str:
    if _is_unjoined_shell_target(target):
        return target
    return str(_join_under(workdir, target))


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
    if _has_parent_dir_component(target) or _has_parent_dir_component(resolved_target):
        return GateDecision(
            DECISION_BLOCK, REASON_PROTECTED_LOCATION, CODE_PROTECTED_LOCATION, 2
        )
    if _is_catastrophic_path(target) or _is_catastrophic_path(resolved_target):
        return GateDecision(
            DECISION_BLOCK, REASON_PROTECTED_LOCATION, CODE_PROTECTED_LOCATION, 2
        )
    if allow_os_temp and _is_os_temp_path(target):
        return None
    if _is_temp_env_specifier(target):
        return GateDecision(DECISION_BLOCK, REASON_UNSAFE_PATH, CODE_UNSAFE_PATH, 2)
    if _is_inside_vault(resolved_target, root):
        target_path_reason = _unsafe_path_reason(resolved_target, root)
        if target_path_reason:
            return GateDecision(DECISION_BLOCK, target_path_reason, CODE_UNSAFE_PATH, 2)
        if not as_directory:
            return None
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


# === R3: shell write targets ===
#
# Threat model. The PreToolUse gate is a guard-rail against agent mistakes and
# prompt-injected *plain* commands. It is not an OS sandbox. R3 guarantees: any
# command that the trigger flags as a cp/mv/curl/tee/redirect write is either
# fully understood by the strict grammar, with every target resolved and
# judged by ``_protected_location_reason``, or blocked. Out of scope: payloads
# hidden from the trigger itself, such as base64/printf-decoded command names
# piped to a shell, interpreters (``python -c``, ``node -e``, ``perl -e``), and
# other writers (``ln``, ``install``, ``rsync``, ``dd of=``, ``touch``,
# ``sed -i``, ``scp``, ``wget``, ``ditto``). Those are R4.
#
# Design rule: this is an allow-list of shell forms Dex understands. Anything
# outside it, in a write-shaped command, is refused. Never add a deny-list of
# "bad spellings" here; narrow the grammar instead.

CODE_UNCHECKED_SHELL_WRITE = "unchecked_shell_write"
REASON_UNCHECKED_SHELL_WRITE = (
    "Blocked: Dex can't tell where this command writes. Use a plain cp, mv, "
    "curl -o, tee or > with a literal path, run cd as its own command, or use "
    "the Write tool."
)

_SHELL_WRITE_COMMANDS = frozenset({"cp", "mv", "curl", "tee"})
# Command words that run or reshape another command, or change shell state.
_SHELL_WRAPPERS = frozenset({
    "sudo", "doas", "env", "command", "builtin", "exec", "eval", "nohup", "time",
    "nice", "ionice", "timeout", "gtimeout", "stdbuf", "caffeinate", "xargs",
    "parallel", "watch", "script", "sh", "bash", "zsh", "dash", "ksh", "fish",
    "csh", "tcsh", "pwsh", "powershell", "source", ".", "alias", "unalias",
    "function", "trap", "export", "set", "unset", "declare", "typeset",
    "readonly", "local", "shopt", "setopt", "unsetopt", "hash", "enable",
    # Commands whose argument is a shell string they run.
    "su", "runuser", "sg", "flock", "ssh", "tmux", "screen", "osascript",
    "chroot", "setsid", "unbuffer",
    # Builtins that assign shell variables (HOME, IFS …) used by later words.
    "read", "mapfile", "readarray", "getopts", "let",
})
# Reserved words that only introduce the next command (``then cp …``).
_SHELL_RESERVED_PREFIXES = frozenset({"if", "then", "else", "elif", "while", "until", "do"})
# Shell runners that may not appear even as an argument of an unknown command
# (``uv run bash -c …``, ``nice -n5 sh x``). ``.`` is excluded: it is a path.
_SHELL_RUNNER_WORDS = frozenset({
    "sh", "bash", "zsh", "dash", "ksh", "fish", "csh", "tcsh", "pwsh",
    "powershell", "eval", "exec", "sudo", "doas", "su", "runuser", "xargs",
    "env", "osascript",
})
_CWD_COMMANDS = frozenset({"cd", "pushd", "popd"})
# Commands that may carry a write-command name as plain data.
_NAME_AS_DATA_COMMANDS = frozenset({"git", "echo", "printf", "which", "type", "man", "whatis", "brew"})
# Read-only commands whose quoted arguments (patterns, messages, bodies) are
# data, never run. Their redirects are still judged.
_PURE_DATA_COMMANDS = frozenset({"echo", "printf", "which", "type", "whatis", "grep", "egrep", "fgrep", "jq"})
_GH_DATA_SUBCOMMANDS = frozenset({
    "pr", "issue", "release", "repo", "api", "run", "workflow", "search",
    "label", "status", "browse", "project", "gist", "cache", "ruleset", "variable",
})
# ``git mv`` is not data: it is parsed as a move (see _git_mv_targets).
_GIT_DATA_SUBCOMMANDS = frozenset({
    "add", "rm", "commit", "log", "show", "diff", "status", "restore",
    "checkout", "switch", "branch", "tag", "stash", "blame", "reset",
})
_BREW_DATA_SUBCOMMANDS = frozenset({
    "install", "uninstall", "reinstall", "upgrade", "info", "search", "list",
    "deps", "uses", "desc", "home", "outdated", "remove",
})
_REDIRECT_SINKS = frozenset({"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "/dev/fd/1", "/dev/fd/2"})
_FIND_UNSAFE_ACTIONS = frozenset({"-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls", "-delete"})
_RECOGNISED_TARGET_VARS = ("HOME", "TMPDIR", "TEMP", "TMP")

_WRITE_NAME_RE = re.compile(r"(?<![a-z0-9_.-])(?:cp|mv|curl|tee)(?:\.exe)?(?![a-z0-9_-])")
# Mention test for words of other commands: the same as the trigger, so a
# suffixed name (``tee.bin``, ``cp.py``) counts too and fails closed.
_WRITE_MENTION_RE = _WRITE_NAME_RE
_UNQUOTED_WORD_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/~:=@%+,-*?[]"
)
_SHELL_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A command word Dex understands: a plain name or path (``cp``, ``/usr/bin/curl``,
# ``~/bin/tool``). zsh ``=name`` expansion and anything else is outside the grammar.
_COMMAND_WORD_RE = re.compile(r"(?:~/)?[A-Za-z0-9_.+/-]*[A-Za-z0-9_]|\[\[?")
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
_HEREDOC_SUBST_RE = re.compile(r"cat[ \t]*<<[ \t]*(?:'([A-Za-z_][A-Za-z0-9_]*)'|\"([A-Za-z_][A-Za-z0-9_]*)\")\n")

_CP_SHORT_FLAGS = frozenset("afinprRvLPHlsuxcT")
_CP_SHORT_VALUE = frozenset("t")
_CP_LONG_FLAGS = frozenset({
    "--archive", "--force", "--interactive", "--no-clobber", "--recursive",
    "--verbose", "--update", "--dereference", "--no-dereference", "--link",
    "--symbolic-link", "--one-file-system", "--no-target-directory", "--preserve",
})
_CP_LONG_FLAGS_WITH_OPTIONAL_VALUE = frozenset({"--preserve"})
_CP_LONG_VALUE = frozenset({"--target-directory"})
_MV_SHORT_FLAGS = frozenset("finvuT")
_MV_SHORT_VALUE = frozenset("t")
_MV_LONG_FLAGS = frozenset({
    "--force", "--interactive", "--no-clobber", "--verbose", "--update", "--no-target-directory",
})
_MV_LONG_VALUE = frozenset({"--target-directory"})
# -J / --remote-header-name are left out on purpose: the server picks the name.
_CURL_SHORT_FLAGS = frozenset("sSLfkviI#OgGN46qZ")
_CURL_SHORT_VALUE = frozenset("HXdFuAemrxbTzw")
_CURL_SHORT_WRITE = frozenset("oDc")
_CURL_LONG_FLAGS = frozenset({
    "--silent", "--show-error", "--location", "--fail", "--fail-with-body",
    "--insecure", "--verbose", "--include", "--head", "--compressed",
    "--progress-bar", "--remote-name", "--remote-name-all",
    "--create-dirs", "--globoff", "--get", "--no-buffer",
    "--http1.1", "--http2", "--ipv4", "--ipv6", "--no-progress-meter", "--parallel",
})
_CURL_LONG_VALUE = frozenset({
    "--header", "--request", "--data", "--data-raw", "--data-binary",
    "--data-urlencode", "--form", "--user", "--user-agent", "--referer",
    "--max-time", "--connect-timeout", "--retry", "--retry-delay",
    "--retry-max-time", "--range", "--proxy", "--cookie", "--cacert", "--cert",
    "--key", "--upload-file", "--limit-rate", "--time-cond", "--resolve",
    "--max-filesize", "--url", "--write-out",
})
_CURL_LONG_WRITE = frozenset({
    "--output", "--output-dir", "--dump-header", "--cookie-jar", "--trace",
    "--trace-ascii", "--stderr", "--etag-save", "--libcurl", "--hsts", "--alt-svc",
})
_CURL_REMOTE_NAME_SHORT = frozenset("O")
_CURL_REMOTE_NAME_LONG = frozenset({"--remote-name", "--remote-name-all"})
_TEE_SHORT_FLAGS = frozenset("aip")
_TEE_LONG_FLAGS = frozenset({"--append", "--ignore-interrupts"})


@dataclass(frozen=True)
class _ShellWord:
    text: str           # value after quote removal (quotes joined: 'c'p -> cp)
    has_var: bool       # contains $NAME or ${NAME} (quoted or not)
    has_glob: bool      # unquoted * ? or a [...] bracket
    tilde_home: bool    # unquoted leading "~" exactly or "~/"
    unquoted_var: bool = False  # a $NAME outside double quotes (word splitting)
    has_subst: bool = False     # contains a "$(cat <<'EOF' … EOF)" literal block
    quoted: bool = False        # any part was quoted


@dataclass(frozen=True)
class _ShellRedirect:
    op: str             # "write", "read" or "dup"
    target: _ShellWord | None   # None for fd dup (2>&1, >&2, 1>&-)


@dataclass(frozen=True)
class _ShellSegment:
    words: tuple[_ShellWord, ...]
    redirects: tuple[_ShellRedirect, ...]


@dataclass(frozen=True)
class _WriteTarget:
    word: _ShellWord
    kind: str           # "path" | "dir" | "move_source" | "create_dir"


class _Unparsed(Exception):
    """Raised inside the strict lexer when a form is outside the grammar."""


def _r3_unparsed_falls_back() -> bool:
    """Decision 3: PowerShell hosts keep today's behaviour for unparsed forms."""
    return os.name == "nt"


def _normalise_for_trigger(text: str) -> str:
    return text.replace("'", "").replace('"', "").replace("\\", "").casefold()


def _mentions_write_command(text: str) -> bool:
    return _WRITE_MENTION_RE.search(_normalise_for_trigger(text)) is not None


def _is_write_shaped(command: str) -> bool:
    """Cheap, over-approximate trigger: True means the strict parser must run."""
    if not command:
        return False
    if ">" in command:
        return True
    if _WRITE_NAME_RE.search(_normalise_for_trigger(command)):
        return True
    if "$'" in command or '$"' in command:
        return True
    for chunk in re.split(r"[;&|(){}\n]", command):
        words = chunk.split()
        while words and (
            words[0].strip("'\"") in _SHELL_RESERVED_PREFIXES or words[0] == "!"
            or _ASSIGNMENT_RE.match(words[0])
        ):
            words = words[1:]
        if not words:
            continue
        first = words[0]
        bare = first.lstrip("'\"")
        if bare.startswith(("$", "`")) or any(ch in first for ch in "*?["):
            return True
        name = _command_name(first.strip("'\""))
        if name in _SHELL_WRAPPERS and ("$" in chunk or "`" in chunk):
            return True
    return False


def _command_name(text: str) -> str:
    name = os.path.basename(text.rstrip("/")).casefold()
    if name.endswith(".exe"):
        name = name[: -len(".exe")]
    return name


class _StrictLexer:
    """Closed-grammar shell lexer. Any form not listed raises ``_Unparsed``."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0
        self.segments: list[_ShellSegment] = []
        self.words: list[_ShellWord] = []
        self.redirects: list[_ShellRedirect] = []
        self.pending: str | None = None  # "write" | "read" | "dupw" | "dupr"
        self.heredoc: tuple[str, bool, bool] | None = None  # (word, quoted, dash)
        self.body_start: int | None = None
        self._reset_word()

    # -- word buffer -------------------------------------------------------
    def _reset_word(self) -> None:
        self.buf: list[str] = []
        self.in_word = False
        self.w_var = False
        self.w_unquoted_var = False
        self.w_glob = False
        self.w_tilde = False
        self.w_subst = False
        self.w_quoted = False
        self.w_open_bracket = False
        self.w_unquoted_only_digits = True

    def _finish_word(self) -> None:
        if not self.in_word:
            return
        word = _ShellWord(
            text="".join(self.buf),
            has_var=self.w_var or self.w_subst,
            has_glob=self.w_glob,
            tilde_home=self.w_tilde,
            unquoted_var=self.w_unquoted_var,
            has_subst=self.w_subst,
            quoted=self.w_quoted,
        )
        self._reset_word()
        if self.pending is not None:
            op = self.pending
            self.pending = None
            if op in {"dupw", "dupr"}:
                plain = not (word.has_var or word.has_glob or word.quoted)
                if plain and (word.text == "-" or word.text.isdigit()):
                    self.redirects.append(_ShellRedirect("dup", None))
                    return
                if op == "dupr":
                    self.redirects.append(_ShellRedirect("read", word))
                    return
                op = "write"
            self.redirects.append(_ShellRedirect(op, word))
            return
        self.words.append(word)

    def _end_segment(self, *, final: bool) -> None:
        self._finish_word()
        if self.pending is not None:
            raise _Unparsed()
        if not self.words and not self.redirects:
            if final:
                return
            raise _Unparsed()
        self.segments.append(_ShellSegment(tuple(self.words), tuple(self.redirects)))
        self.words = []
        self.redirects = []

    def _start(self) -> None:
        self.in_word = True

    # -- scanning ----------------------------------------------------------
    def _peek(self, offset: int = 0) -> str:
        j = self.i + offset
        return self.text[j] if j < len(self.text) else ""

    def _read_var(self) -> str:
        """At ``$``: accept only $NAME or ${NAME}; return the raw spelling."""
        text = self.text
        j = self.i + 1
        if j < len(text) and text[j] == "{":
            match = _SHELL_NAME_RE.match(text, j + 1)
            if not match or match.end() >= len(text) or text[match.end()] != "}":
                raise _Unparsed()
            raw = text[self.i : match.end() + 1]
            self.i = match.end() + 1
            return raw
        match = _SHELL_NAME_RE.match(text, j)
        if not match:
            raise _Unparsed()
        raw = text[self.i : match.end()]
        self.i = match.end()
        return raw

    def _read_heredoc_subst(self) -> bool:
        """Inside double quotes at ``$(``: accept only ``$(cat <<'W'\\n…\\nW\\n)``.

        The body is literal (quoted delimiter), so the word's value is data that
        Dex does not try to read; the word is marked ``has_subst``.
        """
        text = self.text
        match = _HEREDOC_SUBST_RE.match(text, self.i + 2)
        if not match:
            return False
        delim = match.group(1) or match.group(2)
        body_start = match.end()
        closing = "\n" + delim + "\n)"
        if text.startswith(delim + "\n)", body_start):
            end = body_start + len(delim) + 2
        else:
            pos = text.find(closing, body_start - 1)
            if pos < 0:
                raise _Unparsed()
            # No earlier line may equal the delimiter.
            body = text[body_start:pos]
            if any(line == delim for line in body.split("\n")):
                raise _Unparsed()
            end = pos + len(closing)
        self.i = end
        return True

    def _read_single_quoted(self) -> None:
        end = self.text.find("'", self.i + 1)
        if end < 0:
            raise _Unparsed()
        chunk = self.text[self.i + 1 : end]
        if "\n" in chunk:
            raise _Unparsed()
        self.buf.append(chunk)
        self.w_quoted = True
        self.w_unquoted_only_digits = False
        self.i = end + 1

    def _read_double_quoted(self) -> None:
        text = self.text
        self.i += 1
        self.w_quoted = True
        self.w_unquoted_only_digits = False
        while True:
            if self.i >= len(text):
                raise _Unparsed()
            ch = text[self.i]
            if ch == '"':
                self.i += 1
                return
            if ch in "`\\!\n":
                raise _Unparsed()
            if ch == "$":
                if self._peek(1) == "(" and self._read_heredoc_subst():
                    self.w_subst = True
                    self.buf.append("${__dex_literal_block__}")
                    continue
                self.buf.append(self._read_var())
                self.w_var = True
                continue
            self.buf.append(ch)
            self.i += 1

    def _read_heredoc_operator(self) -> None:
        if self.heredoc is not None:
            raise _Unparsed()
        text = self.text
        j = self.i + 2
        dash = False
        if j < len(text) and text[j] == "-":
            dash = True
            j += 1
        while j < len(text) and text[j] in " \t":
            j += 1
        quoted = False
        if j < len(text) and text[j] in "'\"":
            quote = text[j]
            match = _SHELL_NAME_RE.match(text, j + 1)
            if not match or match.end() >= len(text) or text[match.end()] != quote:
                raise _Unparsed()
            delim = match.group(0)
            j = match.end() + 1
            quoted = True
        else:
            match = _SHELL_NAME_RE.match(text, j)
            if not match:
                raise _Unparsed()
            delim = match.group(0)
            j = match.end()
        if j < len(text) and text[j] not in " \t\n;&|":
            raise _Unparsed()
        self.heredoc = (delim, quoted, dash)
        self.i = j

    def _read_redirect(self, fd_prefixed: bool) -> None:
        text = self.text
        ch = text[self.i]
        nxt = self._peek(1)
        if ch == ">":
            if nxt == ">":
                if self._peek(2) in {"!", "|", "&", "("}:
                    raise _Unparsed()
                self.i += 2
                self.pending = "write"
            elif nxt == "|":
                self.i += 2
                self.pending = "write"
            elif nxt == "&":
                self.i += 2
                self.pending = "dupw"
            elif nxt in {"!", "("}:
                raise _Unparsed()
            else:
                self.i += 1
                self.pending = "write"
        else:  # "<"
            if nxt == "<":
                if self._peek(2) == "<":
                    self.i += 3
                    self.pending = "read"
                    return
                if fd_prefixed:
                    raise _Unparsed()
                self._read_heredoc_operator()
                return
            if nxt == ">":
                self.i += 2
                self.pending = "write"
            elif nxt == "&":
                self.i += 2
                self.pending = "dupr"
            elif nxt == "(":
                raise _Unparsed()
            else:
                self.i += 1
                self.pending = "read"
        if self._peek() in {">", "<", "&", "|", ";", "(", ")"}:
            raise _Unparsed()

    def run(self) -> list[_ShellSegment]:
        text = self.text
        while self.i < len(text):
            ch = text[self.i]
            if ch in " \t":
                self._finish_word()
                self.i += 1
                continue
            if ch == "\n":
                if self.heredoc is None:
                    raise _Unparsed()
                self._end_segment(final=True)
                self.body_start = self.i + 1
                return self.segments
            if ch == ";":
                if self._peek(1) == ";":
                    raise _Unparsed()
                self._end_segment(final=False)
                self.i += 1
                continue
            if ch == "|":
                if self._peek(1) == "&":
                    raise _Unparsed()
                self._end_segment(final=False)
                self.i += 2 if self._peek(1) == "|" else 1
                continue
            if ch == "&":
                if self._peek(1) == "&":
                    self._end_segment(final=False)
                    self.i += 2
                    continue
                if self._peek(1) == ">":
                    self._finish_word()
                    if self.pending is not None:
                        raise _Unparsed()
                    self.i += 1  # now at ">"
                    if self._peek(1) == "|" or self._peek(1) == "!":
                        raise _Unparsed()
                    if self._peek(1) == ">":
                        self.i += 2
                    else:
                        self.i += 1
                    if self._peek() in {">", "<", "&", "|", ";", "(", ")"}:
                        raise _Unparsed()
                    self.pending = "write"
                    continue
                # Background: treat like ";". A trailing "&" ends the line.
                self._end_segment(final=False)
                self.i += 1
                continue
            if ch in "<>":
                fd_prefixed = (
                    self.in_word
                    and self.w_unquoted_only_digits
                    and len(self.buf) == 1
                    and len(self.buf[0]) == 1
                    and self.buf[0].isdigit()
                )
                if fd_prefixed:
                    self._reset_word()
                else:
                    self._finish_word()
                if self.pending is not None:
                    raise _Unparsed()
                self._read_redirect(fd_prefixed)
                continue
            if ch == "'":
                self._start()
                self._read_single_quoted()
                continue
            if ch == '"':
                self._start()
                self._read_double_quoted()
                continue
            if ch == "$":
                self._start()
                self.buf.append(self._read_var())
                self.w_var = True
                self.w_unquoted_var = True
                self.w_unquoted_only_digits = False
                continue
            if ch == "~" and not self.in_word:
                nxt = self._peek(1)
                if nxt not in {"", "/", " ", "\t", "\n", ";", "|", "&", "<", ">"}:
                    raise _Unparsed()
                self._start()
                self.w_tilde = True
                self.w_unquoted_only_digits = False
                self.buf.append("~")
                self.i += 1
                continue
            if ch == "=" and not self.in_word:
                raise _Unparsed()  # zsh "=cmd" expands to a command's path
            if ch not in _UNQUOTED_WORD_CHARS:
                # Backslash, backtick, (, ), {, }, #, !, non-ASCII and the rest.
                raise _Unparsed()
            self._start()
            if ch in "*?":
                self.w_glob = True
            elif ch == "[":
                self.w_open_bracket = True
            elif ch == "]" and self.w_open_bracket:
                self.w_glob = True
            if not ch.isdigit():
                self.w_unquoted_only_digits = False
            self.buf.append(ch)
            self.i += 1
        self._end_segment(final=True)
        return self.segments


def _lex_strict_shell(text: str) -> tuple[list[_ShellSegment], tuple[str, bool, bool] | None, int | None] | None:
    lexer = _StrictLexer(text)
    try:
        segments = lexer.run()
    except _Unparsed:
        return None
    if lexer.heredoc is not None and lexer.body_start is None:
        return None  # "<<" with no body
    return segments, lexer.heredoc, lexer.body_start


def _parse_strict_shell(command: str) -> list[_ShellSegment] | None:
    """Segments of a fully understood command, or None (unparsed)."""
    if not command or "\0" in command or "\r" in command:
        return None
    lexed = _lex_strict_shell(command)
    if lexed is None:
        return None
    segments, heredoc, body_start = lexed
    segments = [_strip_reserved_prefixes(seg) for seg in segments]
    if heredoc is None:
        return segments
    delim, quoted, dash = heredoc
    body = command[body_start:]
    if body.endswith("\n"):
        body = body[:-1]
    lines = body.split("\n")
    if not lines:
        return None
    if dash:
        lines = [line.lstrip("\t") for line in lines]
    if lines[-1] != delim or any(line == delim for line in lines[:-1]):
        return None
    if not quoted and any(ch in body for ch in "$`\\"):
        return None
    return segments


def _strip_reserved_prefixes(seg: _ShellSegment) -> _ShellSegment:
    """``then cp a b`` runs ``cp``: judge the command after a reserved word."""
    words = seg.words
    while words and not words[0].quoted and words[0].text in _SHELL_RESERVED_PREFIXES:
        words = words[1:]
    return _ShellSegment(words, seg.redirects) if words is not seg.words else seg


def _segment_name(seg: _ShellSegment) -> str:
    return _command_name(seg.words[0].text) if seg.words else ""


def _is_data_segment(seg: _ShellSegment, name: str) -> bool:
    """True when the command never runs its arguments (they are pure data)."""
    words = seg.words
    if name == "printf" and any(w.text.startswith("-v") for w in words[1:]):
        return False  # printf -v assigns a shell variable
    if name in _PURE_DATA_COMMANDS:
        return True
    if name == "gh":
        return len(words) > 1 and words[1].text in _GH_DATA_SUBCOMMANDS
    if name in {"rg"}:
        return not any(w.text.startswith("--pre") for w in words[1:])
    if name == "man":
        return not any(w.text.startswith("-") for w in words[1:])
    if name == "git":
        return (
            len(words) > 1
            and not words[1].text.startswith("-")
            and words[1].text in _GIT_DATA_SUBCOMMANDS
            # diff/log/show --output=FILE writes a file: not a data form.
            and not any(w.text.startswith("--output") for w in words[2:])
        )
    if name == "brew":
        return len(words) > 1 and words[1].text in _BREW_DATA_SUBCOMMANDS
    return False


def _check_segment_grammar(seg: _ShellSegment) -> bool:
    """Segment rules from the plan (§3.3). False means unparsed."""
    if not seg.words:
        return True  # redirect-only segment, e.g. "> file"
    first = seg.words[0]
    if _ASSIGNMENT_RE.match(first.text):
        return False
    if first.has_var or first.has_glob or first.has_subst:
        return False
    if not _COMMAND_WORD_RE.fullmatch(first.text):
        return False  # e.g. zsh "=cp" (equals expansion) or "a=b"
    name = _segment_name(seg)
    if name not in _SHELL_WRITE_COMMANDS and _mentions_write_command(first.text):
        return False  # a look-alike program (tee.bin, ./curl.sh) Dex can't read
    if name in _SHELL_WRAPPERS:
        return False
    rest = seg.words[1:]
    if name == "printf" and any(w.text.startswith("-v") for w in rest):
        return False  # printf -v assigns a shell variable
    if name == "git" and any(w.text.startswith("--output") for w in rest):
        return False  # git diff/log/show --output=FILE writes a file
    if name == "find" and any(w.text in _FIND_UNSAFE_ACTIONS for w in rest):
        return False
    if _is_data_segment(seg, name):
        return True
    if name == "git" and len(seg.words) > 1 and seg.words[1].text == "mv":
        # Parsed by _git_mv_targets; its operands are paths, not commands.
        return not any(_command_name(w.text) in _SHELL_RUNNER_WORDS for w in seg.words[2:]) and not any(
            _mentions_write_command(w.text) for w in seg.words[2:]
        )
    for word in rest:
        if _mentions_write_command(word.text):
            return False
        if _command_name(word.text) in _SHELL_RUNNER_WORDS:
            return False
    if name in _SHELL_WRITE_COMMANDS or name in _CWD_COMMANDS:
        return True
    for word in rest:
        # A quoted ">" or a literal block handed to a command Dex doesn't know
        # may be run as shell by that command (git -c alias, awk, flock -c …).
        if word.has_subst or ">" in word.text:
            return False
    return True


def _recognised_var_word(word: _ShellWord) -> bool:
    """$HOME, ${HOME}, $TMPDIR, $TEMP, $TMP, optionally followed by /rest."""
    if word.has_subst or word.has_glob:
        return False
    text = word.text
    for name in _RECOGNISED_TARGET_VARS:
        for spelling in (f"${{{name}}}", f"${name}"):
            if text == spelling or text.startswith(spelling + "/"):
                if "$" in text[len(spelling):]:
                    return False
                if word.unquoted_var:
                    value = os.environ.get(name, "")
                    if not value or any(ch in value for ch in " \t\n*?[") or value.startswith("-"):
                        return False
                return True
    return False


def _argv_vars_ok(words: tuple[_ShellWord, ...]) -> bool:
    return all(not w.has_var or _recognised_var_word(w) for w in words)


def _value_word(word: _ShellWord, value: str) -> _ShellWord:
    """Word for the value half of ``--opt=value`` (a leading ~ counts as home)."""
    if value.startswith("~") and not (value == "~" or value.startswith("~/")):
        raise _Unparsed()
    tilde = value == "~" or value.startswith("~/")
    return _ShellWord(
        text=value,
        has_var=word.has_var,
        has_glob=word.has_glob,
        tilde_home=tilde,
        unquoted_var=word.unquoted_var,
        has_subst=word.has_subst,
        quoted=word.quoted,
    )


def _parse_options(
    args: tuple[_ShellWord, ...],
    *,
    short_flags: frozenset[str],
    short_value: frozenset[str],
    long_flags: frozenset[str],
    long_value: frozenset[str],
    long_optional_value: frozenset[str] = frozenset(),
) -> tuple[list[tuple[str, _ShellWord]], list[_ShellWord], set[str]] | None:
    """Closed option parser. Returns (valued options, operands, flags seen)."""
    valued: list[tuple[str, _ShellWord]] = []
    operands: list[_ShellWord] = []
    flags: set[str] = set()
    end_opts = False
    i = 0
    try:
        while i < len(args):
            word = args[i]
            text = word.text
            if not end_opts and text == "--":
                end_opts = True
            elif not end_opts and text.startswith("--"):
                name, eq, value = text.partition("=")
                if name in long_value:
                    if eq:
                        valued.append((name, _value_word(word, value)))
                    else:
                        i += 1
                        if i >= len(args):
                            return None
                        valued.append((name, args[i]))
                elif name in long_flags:
                    if eq and name not in long_optional_value:
                        return None
                    flags.add(name)
                else:
                    return None
            elif not end_opts and text.startswith("-") and text != "-":
                letters = text[1:]
                for index, letter in enumerate(letters):
                    if letter in short_flags:
                        flags.add("-" + letter)
                        continue
                    if letter in short_value:
                        if index != len(letters) - 1:
                            return None  # attached value (-tDIR, -oFILE)
                        i += 1
                        if i >= len(args):
                            return None
                        valued.append(("-" + letter, args[i]))
                        continue
                    return None
            else:
                operands.append(word)
            i += 1
    except _Unparsed:
        return None
    return valued, operands, flags


def _cp_mv_targets(seg: _ShellSegment, name: str) -> list[_WriteTarget] | None:
    args = seg.words[1:]
    if not _argv_vars_ok(args):
        return None
    if name == "cp":
        parsed = _parse_options(
            args,
            short_flags=_CP_SHORT_FLAGS,
            short_value=_CP_SHORT_VALUE,
            long_flags=_CP_LONG_FLAGS,
            long_value=_CP_LONG_VALUE,
            long_optional_value=_CP_LONG_FLAGS_WITH_OPTIONAL_VALUE,
        )
    else:
        parsed = _parse_options(
            args,
            short_flags=_MV_SHORT_FLAGS,
            short_value=_MV_SHORT_VALUE,
            long_flags=_MV_LONG_FLAGS,
            long_value=_MV_LONG_VALUE,
        )
    if parsed is None:
        return None
    valued, operands, _flags = parsed
    dirs = [word for _opt, word in valued]
    targets: list[_WriteTarget] = []
    if dirs:
        if not operands:
            return None
        targets.extend(_WriteTarget(word, "dir") for word in dirs)
        sources = operands
    else:
        if len(operands) < 2:
            return None
        targets.append(_WriteTarget(operands[-1], "path"))
        sources = operands[:-1]
    if name == "mv":
        targets.extend(_WriteTarget(word, "move_source") for word in sources)
    return targets


def _join_words(base: _ShellWord, rest: _ShellWord) -> _ShellWord:
    return _ShellWord(
        text=base.text.rstrip("/") + "/" + rest.text,
        has_var=base.has_var or rest.has_var,
        has_glob=base.has_glob or rest.has_glob,
        tilde_home=base.tilde_home,
        unquoted_var=base.unquoted_var or rest.unquoted_var,
        has_subst=base.has_subst or rest.has_subst,
        quoted=base.quoted or rest.quoted,
    )


def _curl_targets(seg: _ShellSegment) -> list[_WriteTarget] | None:
    args = seg.words[1:]
    if not _argv_vars_ok(args):
        return None
    parsed = _parse_options(
        args,
        short_flags=_CURL_SHORT_FLAGS,
        short_value=_CURL_SHORT_VALUE | _CURL_SHORT_WRITE,
        long_flags=_CURL_LONG_FLAGS,
        long_value=_CURL_LONG_VALUE | _CURL_LONG_WRITE,
    )
    if parsed is None:
        return None
    valued, _operands, flags = parsed
    write_short = {"-" + letter for letter in _CURL_SHORT_WRITE}
    output_dirs: list[_ShellWord] = []
    files: list[_ShellWord] = []
    for option, word in valued:
        if option in {"-w", "--write-out"} and (
            word.text.startswith("@") or "%output" in word.text.casefold()
        ):
            return None  # format read from a file/stdin, or one that writes files
        if option in write_short or option in _CURL_LONG_WRITE:
            if re.search(r"#[0-9]", word.text):
                return None
            if option == "--output-dir":
                output_dirs.append(word)
            else:
                files.append(word)
    create_dirs = "--create-dirs" in flags
    dir_kind = "create_dir" if create_dirs else "dir"
    targets: list[_WriteTarget] = [_WriteTarget(word, dir_kind) for word in output_dirs]
    for word in files:
        targets.append(_WriteTarget(word, "path"))
        relative = not (word.tilde_home or word.text.startswith("/") or word.has_var)
        if relative:
            # curl writes relative -o files under --output-dir.
            targets.extend(_WriteTarget(_join_words(base, word), "path") for base in output_dirs)
    remote_name = bool(flags & ({"-" + letter for letter in _CURL_REMOTE_NAME_SHORT} | _CURL_REMOTE_NAME_LONG))
    if remote_name and not output_dirs:
        targets.append(_WriteTarget(_ShellWord(".", False, False, False), dir_kind))
    return targets


def _tee_targets(seg: _ShellSegment) -> list[_WriteTarget] | None:
    args = seg.words[1:]
    if not _argv_vars_ok(args):
        return None
    parsed = _parse_options(
        args,
        short_flags=_TEE_SHORT_FLAGS,
        short_value=frozenset(),
        long_flags=_TEE_LONG_FLAGS,
        long_value=frozenset(),
    )
    if parsed is None:
        return None
    _valued, operands, _flags = parsed
    return [_WriteTarget(word, "path") for word in operands]


def _redirect_targets(seg: _ShellSegment) -> list[_WriteTarget]:
    targets: list[_WriteTarget] = []
    for redirect in seg.redirects:
        if redirect.op != "write" or redirect.target is None:
            continue
        word = redirect.target
        if word.text in _REDIRECT_SINKS and not (word.has_var or word.has_glob):
            continue
        targets.append(_WriteTarget(word, "path"))
    return targets


_GIT_MV_SHORT_FLAGS = frozenset("fknv")
_GIT_MV_LONG_FLAGS = frozenset({"--force", "--dry-run", "--verbose"})


def _git_mv_targets(seg: _ShellSegment) -> list[_WriteTarget] | None:
    """``git mv [-f -k -n -v] SRC… DEST``: judged like mv (git follows dir symlinks)."""
    args = seg.words[2:]
    if not _argv_vars_ok(args):
        return None
    parsed = _parse_options(
        args,
        short_flags=_GIT_MV_SHORT_FLAGS,
        short_value=frozenset(),
        long_flags=_GIT_MV_LONG_FLAGS,
        long_value=frozenset(),
    )
    if parsed is None:
        return None
    _valued, operands, _flags = parsed
    if len(operands) < 2:
        return None
    targets = [_WriteTarget(operands[-1], "path")]
    targets.extend(_WriteTarget(word, "move_source") for word in operands[:-1])
    return targets


def _segment_write_targets(seg: _ShellSegment) -> list[_WriteTarget] | None:
    if not _check_segment_grammar(seg):
        return None
    name = _segment_name(seg)
    targets: list[_WriteTarget] = []
    if name in {"cp", "mv"}:
        found = _cp_mv_targets(seg, name)
    elif name == "git" and len(seg.words) > 1 and seg.words[1].text == "mv":
        found = _git_mv_targets(seg)
    elif name == "curl":
        found = _curl_targets(seg)
    elif name == "tee":
        found = _tee_targets(seg)
    else:
        found = []
    if found is None:
        return None
    targets.extend(found)
    targets.extend(_redirect_targets(seg))
    return targets


_UNKNOWN_CWD = None


def _next_cwd_candidates(seg: _ShellSegment, candidates: list[Path] | None) -> list[Path] | None:
    name = _segment_name(seg)
    if name != "cd" or candidates is _UNKNOWN_CWD:
        return _UNKNOWN_CWD
    args = [w for w in seg.words[1:]]
    while args and args[0].text in {"-P", "-L"}:
        args = args[1:]
    if args and args[0].text == "--":
        args = args[1:]
    if not args:
        home = _resolved_home()
        return _UNKNOWN_CWD if home is None else candidates + [home]
    if len(args) != 1:
        return _UNKNOWN_CWD
    word = args[0]
    text = word.text
    if word.has_var or word.has_glob or word.has_subst or text == "-" or text.startswith("-"):
        return _UNKNOWN_CWD
    added: list[Path] = []
    if word.tilde_home:
        home_path = _path_for_location_check(text)
        if home_path is None:
            return _UNKNOWN_CWD
        added.append(home_path)
    elif text.startswith("/"):
        added.append(Path(text))
    else:
        bases = list(candidates)
        for entry in os.environ.get("CDPATH", "").split(":"):
            if entry:
                entry_path = Path(entry)
                if entry_path.is_absolute():
                    bases.append(entry_path)
                else:
                    bases.extend(_join_under(base, entry) for base in candidates)
        for base in bases:
            joined = _join_under(base, text)
            added.append(Path(os.path.normpath(str(joined))))
            try:
                added.append(Path(os.path.realpath(str(joined))))
            except OSError:
                return _UNKNOWN_CWD
    merged = list(candidates)
    for path in added:
        if path not in merged:
            merged.append(path)
    return merged


def _unchecked_write() -> GateDecision:
    return GateDecision(DECISION_BLOCK, REASON_UNCHECKED_SHELL_WRITE, CODE_UNCHECKED_SHELL_WRITE, 2)


def _protected_write() -> GateDecision:
    return GateDecision(DECISION_BLOCK, REASON_PROTECTED_LOCATION, CODE_PROTECTED_LOCATION, 2)


def _target_spelling(target: _WriteTarget) -> tuple[str, _ShellWord, bool] | GateDecision:
    """The text to resolve for one target, after glob and variable rules (§4.6)."""
    word = target.word
    text = word.text
    if word.has_subst:
        return _unchecked_write()
    if word.has_glob:
        if target.kind != "move_source":
            return _unchecked_write()
        head, sep, last = text.rpartition("/")
        static_parent = (head or "/") if sep else "."
        if any(ch in static_parent for ch in "*?[]"):
            return _unchecked_write()
        parent_word = _ShellWord(
            static_parent, word.has_var, False,
            word.tilde_home and (static_parent == "~" or static_parent.startswith("~/")),
            word.unquoted_var, False, word.quoted,
        )
        return static_parent, parent_word, True
    if word.has_var and not _recognised_var_word(word):
        return _unchecked_write()
    return text, word, False


def _absolute_target(text: str, word: _ShellWord, cwd: Path) -> Path | None:
    for name in ("TMPDIR", "TEMP", "TMP"):
        braced = f"${{{name}}}"
        if text == braced or text.startswith(braced + "/"):
            text = f"${name}" + text[len(braced):]
    if word.has_var:
        expanded = _path_for_location_check(text)
        if expanded is None or not expanded.is_absolute():
            return None
        return expanded
    if word.tilde_home:
        return _path_for_location_check(text)
    if text.startswith("/") or Path(text).is_absolute():
        return Path(text)
    return _join_under(cwd, text)


def _is_relative_target(text: str, word: _ShellWord) -> bool:
    if word.has_var or word.tilde_home:
        return False
    return not (text.startswith("/") or Path(text).is_absolute())


def _judge_write_target(
    target: _WriteTarget, *, root: Path, workdirs: list[Path] | None
) -> GateDecision | None:
    spelled = _target_spelling(target)
    if isinstance(spelled, GateDecision):
        return spelled
    text, word, glob_parent = spelled
    if _has_parent_dir_component(text):
        return _protected_write()
    relative = _is_relative_target(text, word)
    if relative and workdirs is _UNKNOWN_CWD:
        return _unchecked_write()
    cwds = workdirs if relative else (workdirs or [root])[:1]
    for cwd in cwds:
        absolute = _absolute_target(text, word, cwd)
        if absolute is None:
            return _protected_write()
        if _has_parent_dir_component(str(absolute)):
            return _protected_write()
        if target.kind == "move_source" and not glob_parent:
            parent = _normalize_write_path(absolute.parent)
            real = None if parent is None else parent / absolute.name
        else:
            real = _normalize_write_path(absolute)
        if real is None:
            return _protected_write()
        decision = _shell_target_decision(
            str(real),
            root=root,
            workdir=cwd,
            allow_os_temp=True,
            as_directory=target.kind == "create_dir",
        )
        if decision is not None:
            return decision
    return None


# Decision 3 (PowerShell keeps today's behaviour) applies only to commands that
# are recognisably PowerShell: a drive-letter backslash path, ``$env:`` or a
# Verb-Noun cmdlet. Git Bash forms on Windows are refused like everywhere else.
_POWERSHELL_HINT_RE = re.compile(r"[A-Za-z]:\\|\$env:|(?<![\w-])[A-Z][a-z]+-[A-Z][A-Za-z]+(?![\w-])")
_HOME_SPELLINGS_RE = re.compile(r"^(?:\$env:USERPROFILE|\$env:HOME|\$HOME|~)(?=$|[\\/])", re.IGNORECASE)


def _unparsed_decision(command: str) -> GateDecision | None:
    """Refuse an unparsed write-shaped command, except the PowerShell gap (Decision 3)."""
    if not _r3_unparsed_falls_back() or not _POWERSHELL_HINT_RE.search(command):
        return _unchecked_write()
    tokens = [t.strip("'\"`") for t in re.split(r"[\s;|&(){}<>,]+", command) if t]
    for token in tokens:
        name = _command_name(token.replace("\\", "/"))
        if name in _SHELL_WRAPPERS or name in _SHELL_RUNNER_WORDS:
            return _unchecked_write()
    for token in tokens:
        homed = _HOME_SPELLINGS_RE.sub("~", token)
        # PowerShell reads "\\" as a separator; Git Bash reads it as an escape.
        for candidate in {homed.replace("\\", "/"), homed.replace("\\", "")}:
            if not (candidate.startswith(("~", "/")) or re.match(r"^[A-Za-z]:/", candidate)):
                continue
            if _has_parent_dir_component(candidate):
                return _protected_write()
            if _WINDOWS_PROTECTED.match(candidate.replace("/", "\\")):
                return _protected_write()
            if re.match(r"^[A-Za-z]:/", candidate) and os.name != "nt":
                continue  # a drive path only means something on Windows itself
            if _protected_location_reason(candidate, None):
                return _protected_write()
    return None


def _shell_write_decision(command: str, *, root: Path, workdir: Path) -> GateDecision | None:
    """Block a cp/mv/curl/tee/redirect write into a protected place, or one Dex can't read."""
    if not _is_write_shaped(command):
        return None
    segments = _parse_strict_shell(command)
    if segments is None:
        return _unparsed_decision(command)
    plan: list[tuple[_ShellSegment, list[_WriteTarget]]] = []
    for seg in segments:
        targets = _segment_write_targets(seg)
        if targets is None:
            return _unparsed_decision(command)
        plan.append((seg, targets))
    candidates: list[Path] | None = [workdir]
    for seg, targets in plan:
        for target in targets:
            decision = _judge_write_target(target, root=root, workdirs=candidates)
            if decision is not None:
                return decision
        if _segment_name(seg) in _CWD_COMMANDS:
            candidates = _next_cwd_candidates(seg, candidates)
    return None


# === end R3 ===


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
    command_text = command if isinstance(command, str) else ""
    path_text = path if isinstance(path, str) else ""
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

    if path_text and _has_parent_dir_component(path_text):
        return GateDecision(DECISION_BLOCK, REASON_UNSAFE_PATH, CODE_UNSAFE_PATH, 2)
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
        allowed_paths = _parse_strict_mkdir_command(command_text)
        if allowed_paths is not None:
            mkdir_decision = _evaluate_allowed_mkdir_paths(
                allowed_paths,
                root=root,
                workdir=workdir,
                allow_os_temp=allow_os_temp,
            )
            return ALLOW if mkdir_decision is None else mkdir_decision
        for target in mkdir_targets(command_text):
            if _is_catastrophic_path(target) or _is_unjoined_shell_target(target):
                resolved_target = target
            else:
                resolved_target = str(workdir / target)
            # Non-allow-list mkdir does not get the outside-vault exception,
            # including OS-temp paths. Only the strict allow-list may create
            # a folder outside the vault.
            if _is_temp_env_specifier(target):
                return GateDecision(DECISION_BLOCK, REASON_UNSAFE_PATH, CODE_UNSAFE_PATH, 2)
            target_path_reason = _unsafe_path_reason(resolved_target, root)
            if target_path_reason:
                return GateDecision(DECISION_BLOCK, target_path_reason, CODE_UNSAFE_PATH, 2)
            target_folder_reason = new_top_level_folder_reason(root, resolved_target, as_directory=True)
            if target_folder_reason:
                return GateDecision(
                    DECISION_BLOCK, target_folder_reason, CODE_NEW_TOP_LEVEL_FOLDER, 2
                )
        write_decision = _shell_write_decision(command_text, root=root, workdir=workdir)
        if write_decision is not None:
            return write_decision
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
