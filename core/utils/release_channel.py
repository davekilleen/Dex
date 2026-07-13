"""Resolve the installed Dex release channel and its trusted Git refs."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml

VALID_CHANNELS = frozenset({"stable", "beta"})


def read_channel(vault_root: str | Path) -> str:
    """Return the configured channel, the stable default, or ``invalid``."""
    profile_path = Path(vault_root) / "System" / "user-profile.yaml"
    try:
        content = profile_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "stable"
    except OSError:
        return "invalid"

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
