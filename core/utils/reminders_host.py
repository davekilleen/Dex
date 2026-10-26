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

_VSCODE_TERM_PROGRAM = "vscode"
_VSCODE_ENV_MARKERS = (
    "VSCODE_PID",
    "VSCODE_CWD",
    "VSCODE_IPC_HOOK",
    "VSCODE_INJECTION",
)
# Other VS Code-based editors inherit these environment markers but are not
# VS Code itself. Reminders may still work there; do not treat them as VS Code.
_OTHER_EDITOR_ENV_MARKERS = (
    "CURSOR_TRACE_ID",
    "CURSOR_AGENT",
)


def is_vscode_host(env: Mapping[str, str] | None = None) -> bool:
    """Return True when this process is running inside VS Code.

    macOS never shows the Reminders permission ask to that app, so Dex
    must not try to switch Reminders on from here.
    """
    environment = os.environ if env is None else env
    if any(environment.get(marker) for marker in _OTHER_EDITOR_ENV_MARKERS):
        return False
    term = environment.get("TERM_PROGRAM", "")
    if term.lower() == _VSCODE_TERM_PROGRAM:
        return True
    return any(environment.get(marker) for marker in _VSCODE_ENV_MARKERS)
