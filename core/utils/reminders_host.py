"""Detect hosts where macOS will not show the Reminders permission ask."""

from __future__ import annotations

import os
from collections.abc import Mapping

VSCODE_REMINDERS_UNAVAILABLE_MESSAGE = (
    "Reminders can't be switched on from inside VS Code. "
    "The Mac never shows the permission ask in that app. "
    "Use the Claude app or Terminal if you want Reminders. "
    "You can keep using Dex here without phone capture."
)

CLAUDE_DESKTOP_REMINDERS_UNAVAILABLE_MESSAGE = (
    "Reminders can't be switched on from inside the Claude app without Dex Helper. "
    "Dex will open a small helper so macOS can ask. "
    "Use Terminal if you want Reminders without the helper. "
    "You can keep using Dex here without phone capture."
)

_VSCODE_TERM_PROGRAM = "vscode"
_VSCODE_ENV_MARKERS = (
    "VSCODE_PID",
    "VSCODE_CWD",
    "VSCODE_IPC_HOOK",
    "VSCODE_INJECTION",
)
# Other VS Code-based editors inherit these environment markers but are not
# VS Code itself. Reminders may still work there; do not treat them as VS Code.
_CURSOR_ENV_MARKERS = (
    "CURSOR_TRACE_ID",
    "CURSOR_AGENT",
)
_CLAUDE_DESKTOP_MARKERS = (
    "CLAUDE_DESKTOP",
)
_CLAUDE_DESKTOP_BUNDLE = "com.anthropic.claudefordesktop"


def _env(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return os.environ if env is None else env


def is_cursor_host(env: Mapping[str, str] | None = None) -> bool:
    environment = _env(env)
    return any(environment.get(marker) for marker in _CURSOR_ENV_MARKERS)


def is_claude_desktop_host(env: Mapping[str, str] | None = None) -> bool:
    """Return True when this process is the Claude desktop app, not Claude Code."""
    environment = _env(env)
    if environment.get("CLAUDE_CODE"):
        return False
    if any(environment.get(marker) for marker in _CLAUDE_DESKTOP_MARKERS):
        return True
    bundle = environment.get("__CFBundleIdentifier", "")
    return bundle.lower() == _CLAUDE_DESKTOP_BUNDLE


def is_vscode_host(env: Mapping[str, str] | None = None) -> bool:
    """Return True when this process is running inside VS Code.

    macOS never shows the Reminders permission ask to that app, so Dex
    must not try to switch Reminders on from here.
    """
    environment = _env(env)
    if is_cursor_host(environment) or is_claude_desktop_host(environment):
        return False
    term = environment.get("TERM_PROGRAM", "")
    if term.lower() == _VSCODE_TERM_PROGRAM:
        return True
    return any(environment.get(marker) for marker in _VSCODE_ENV_MARKERS)


def is_terminal_host(env: Mapping[str, str] | None = None) -> bool:
    environment = _env(env)
    if is_vscode_host(environment) or is_cursor_host(environment) or is_claude_desktop_host(environment):
        return False
    return bool(environment.get("TERM") or environment.get("TERM_PROGRAM"))


def reminders_blocked_without_helper(env: Mapping[str, str] | None = None) -> str | None:
    """Return the feature_status message when Reminders cannot prompt here."""
    environment = _env(env)
    if environment.get("DEX_HELPER_PROCESS"):
        return None
    if is_vscode_host(environment):
        return VSCODE_REMINDERS_UNAVAILABLE_MESSAGE
    if is_claude_desktop_host(environment):
        return CLAUDE_DESKTOP_REMINDERS_UNAVAILABLE_MESSAGE
    return None
