"""One selected-vault policy for portable tools and native/portable hooks.

Configuration binds a session to one vault. Request roots must agree with that
binding; a working directory can be a descendant. Without a binding, an explicit
root or single workspace selects a vault. Multiple workspaces require selection.
The process cwd is only a last resort, never an override of configuration.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class VaultSelectionError(ValueError):
    """A request has no unambiguous, usable selected vault."""

    code = "vault_selection_conflict"


MESSAGE = (
    "Blocked: vault selection is invalid or conflicting. Set DEX_VAULT_PATH to the selected Dex folder, "
    "align or clear VAULT_PATH/CLAUDE_PROJECT_DIR, and use that folder in the request. "
    "Multiple workspaces require an explicit selection."
)


def _root(value: Any) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise VaultSelectionError(MESSAGE)
    try:
        path = Path(value).expanduser()
        # Relative configuration changes meaning when a host launches from its
        # package cache; require stable absolute selections instead.
        if not path.is_absolute():
            raise VaultSelectionError(MESSAGE)
        path = path.resolve(strict=True)
        if not path.is_dir():
            raise VaultSelectionError(MESSAGE)
        return path
    except (OSError, RuntimeError, ValueError) as exc:
        raise VaultSelectionError(MESSAGE) from exc


def select_vault(*, explicit: Any = None, cwd: Any = None, workspace_roots: Any = None) -> Path:
    bindings = [_root(value) for key in ("DEX_VAULT_PATH", "VAULT_PATH", "CLAUDE_PROJECT_DIR")
                if (value := os.environ.get(key))]
    if explicit is not None:
        bindings.append(_root(explicit))
    if len(set(bindings)) > 1:
        raise VaultSelectionError(MESSAGE)
    workspaces: list[Path] = []
    if workspace_roots is not None:
        if not isinstance(workspace_roots, list):
            raise VaultSelectionError(MESSAGE)
        workspaces = list(dict.fromkeys(_root(value) for value in workspace_roots))
    working = _root(cwd) if cwd is not None else None
    if bindings:
        selected = bindings[0]
    elif len(workspaces) == 1:
        selected = workspaces[0]
    elif len(workspaces) > 1:
        raise VaultSelectionError(MESSAGE)
    else:
        selected = working or _root(Path.cwd())
    if workspaces and selected not in workspaces:
        raise VaultSelectionError(MESSAGE)
    if working is not None and not working.is_relative_to(selected):
        raise VaultSelectionError(MESSAGE)
    return selected
