"""Capsule-construction sensitivity policy.

``inventory.py`` already excludes embedded-secret content at assessment time.
This module is the single policy source for capsule construction; it performs
no I/O and must remain the authority Lane C imports.
"""

from __future__ import annotations

import fnmatch
import posixpath

from core.portable_contract import HARD_DENY_PATTERNS, is_denied

CREDENTIAL_BEARING_CONFIGS = (
    *HARD_DENY_PATTERNS,
    ".mcp.json",
    ".claude/settings.json",
    ".claude/settings.local.json",
    "System/integrations/*.yaml",
)

SECRET_ARCHIVAL_POLICY = "record-finding-leave-in-place"
"""Capsules never archive secret bytes (threat-model section 5)."""

_CAPSULE_CREDENTIAL_PATTERNS = CREDENTIAL_BEARING_CONFIGS[
    len(HARD_DENY_PATTERNS) :
]


def capsule_readability(path: str) -> str:
    """Return the model readability allowed while constructing a capsule."""
    if not isinstance(path, str) or not path or "\x00" in path:
        return "restricted"
    try:
        if is_denied(path):
            return "restricted"
    except ValueError:
        return "restricted"
    candidate = path.strip().replace("\\", "/").lstrip("/")
    candidate = posixpath.normpath(candidate).lstrip("/")
    if candidate == "." or candidate == ".." or candidate.startswith("../"):
        return "restricted"
    candidate = candidate.casefold()
    if any(
        fnmatch.fnmatch(candidate, pattern.casefold())
        for pattern in _CAPSULE_CREDENTIAL_PATTERNS
    ):
        return "restricted"
    return "readable"


__all__ = [
    "CREDENTIAL_BEARING_CONFIGS",
    "SECRET_ARCHIVAL_POLICY",
    "capsule_readability",
]
