"""Resolve trusted release refs and sanitized probe environments."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

VALID_CHANNELS = frozenset({"stable", "beta"})
SAFE_BASE_DIRECTORIES = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_temporary_executable(path: Path) -> bool:
    for raw_root in ("/private/tmp", "/tmp", "/var/tmp", tempfile.gettempdir()):
        try:
            root = Path(raw_root).resolve(strict=True)
        except OSError:
            continue
        if _is_within(path, root):
            return True
    return False


def _validated_tool(
    name: str,
    *,
    user_path: str,
    vault_root: Path,
) -> tuple[Path, Path] | None:
    discovered = shutil.which(name, path=user_path)
    if discovered is None:
        return None
    candidate = Path(discovered)
    if not candidate.is_absolute():
        return None
    try:
        parent = candidate.parent
        resolved = candidate.resolve(strict=True)
        resolved_parent = resolved.parent
        vault = vault_root.resolve(strict=False)
        if (
            parent.is_symlink()
            or not parent.is_dir()
            or not resolved.is_file()
            or not os.access(candidate, os.X_OK)
            or not os.access(resolved, os.X_OK)
            or stat.S_IMODE(parent.stat().st_mode) & stat.S_IWOTH
            or stat.S_IMODE(resolved_parent.stat().st_mode) & stat.S_IWOTH
            or _is_within(candidate, vault)
            or _is_within(resolved, vault)
            or _is_temporary_executable(resolved)
        ):
            return None
    except OSError:
        return None
    return parent, resolved


def sanitized_path_with_tools(
    vault_root: Path,
    tool_names: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    """Return the safe base PATH plus validated real-user tool locations."""
    source_environment = os.environ if environment is None else environment
    user_path = source_environment.get("PATH", "")
    directories = list(SAFE_BASE_DIRECTORIES)
    tools: dict[str, str] = {}
    for name in tool_names:
        validated = _validated_tool(name, user_path=user_path, vault_root=vault_root)
        if validated is None:
            continue
        parent, resolved = validated
        rendered_parent = str(parent)
        if rendered_parent not in directories:
            directories.append(rendered_parent)
        tools[name] = str(resolved)
    return os.pathsep.join(directories), tools


def read_channel(vault_root: str | Path) -> str:
    """Return the configured channel, the stable default, ``missing-dependency``, or ``invalid``."""
    profile_path = Path(vault_root) / "System" / "user-profile.yaml"
    try:
        content = profile_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "stable"
    except OSError:
        return "invalid"

    try:
        import yaml
    except ImportError:
        # A missing PyYAML is not a broken settings file — keep the two distinguishable
        # so callers don't send users hunting for a config problem that doesn't exist.
        return "missing-dependency"

    try:
        profile = yaml.safe_load(content)
    except Exception:
        return "invalid"
    if not isinstance(profile, Mapping) or "updates" not in profile:
        return "stable"
    updates = profile["updates"]
    if not isinstance(updates, Mapping) or "channel" not in updates:
        return "stable"
    channel = updates["channel"]
    return channel if isinstance(channel, str) and channel in VALID_CHANNELS else "invalid"


def release_ref_candidates(channel: str) -> tuple[str, ...]:
    """Return trusted remote refs for ``channel`` in precedence order."""
    branch = release_branch(channel)
    if branch is None:
        return ()
    return (f"upstream/{branch}", f"origin/{branch}")


def release_branch(channel: str) -> str | None:
    """Return the release branch for ``channel``, if it is valid."""
    if channel == "stable":
        return "release"
    if channel == "beta":
        return "release-beta"
    return None
