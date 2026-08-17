"""Fail-closed walls for product analytics on the public Dex download path.

WO-057: anonymous product analytics may be on by default, but nothing leaves
the machine unless it passes every wall. A later emitter cannot bypass these
checks by calling fire_event with extra fields.

Walls:
1. No content — never vault text, file names, paths, conversation, transcripts.
2. No Guide/Coach usage log — no person-level work patterns.
3. No identity beyond an install-scoped identifier — not vault identity, not
   Record keys.
4. Career-grade surfaces emit nothing.

This module does not invent a vendor, a dashboard, or a Dex-held analytics key.
Transport stays whatever the existing helper already uses.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.analytics_events import CAREER_GRADE_EVENT_NAMES, SAFE_ANALYTICS_EVENT_NAMES

# App-level caller keys only. Counts/booleans may pass; free text may not.
_FORBIDDEN_PROPERTY_KEY_MARKERS = (
    "name",
    "path",
    "file",
    "note",
    "text",
    "content",
    "transcript",
    "ask",
    "conversation",
    "message",
    "prompt",
    "role",
    "company",
    "email",
    "visitor",
    "account",
    "record",
    "career",
    "coach",
    "guide",
    "journey",
    "adoption",
    "area",
    "folder",
    "vault",
    "title",
    "utterance",
)

# Person-level work-pattern fields from usage_log / Guide / Coach.
USAGE_PATTERN_PROPERTY_KEYS = frozenset(
    {
        "journey_stage",
        "days_since_setup",
        "feature_adoption_score",
        "most_active_area",
        "role",
        "role_group",
        "company_size",
        "pillars_count",
    }
)

IDENTITY_PROPERTY_KEYS = frozenset(
    {
        "visitor_id",
        "account_id",
        "visitorId",
        "accountId",
        "name",
        "email",
        "email_domain",
        "work_email",
        "install_id",
        "record_key",
        "telemetry_id",
    }
)

_SAFE_PROPERTY_KEY = re.compile(r"^[a-z][a-z0-9_]{0,32}$")
_SAFE_ERROR_CLASS = re.compile(r"^[a-z][a-z0-9_]{0,32}$")
_VAULT_FOLDER_MARKERS = (
    "00-Inbox",
    "01-Quarter_Goals",
    "02-Week_Priorities",
    "03-Tasks",
    "04-Projects",
    "05-Areas",
    "06-Resources",
    "07-Archives",
    "05-Areas/Career",
    "Career/",
)
_PATH_LIKE = re.compile(r"(?:^|[\s\"'/])(?:\.{0,2}/)?[\w.-]+\.(?:md|yaml|yml|json|txt)\b")
_EMAIL_LIKE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

ANALYTICS_INSTALL_ID_RELATIVE = "System/.dex/analytics-install-id"
ANALYTICS_ACCOUNT_SCOPE = "dex-installs"
WALL_CONTENT = "content_blocked"
WALL_USAGE_PATTERN = "usage_pattern_blocked"
WALL_IDENTITY = "identity_blocked"
WALL_CAREER = "career_surface_blocked"


def is_career_grade_event(event_name: object) -> bool:
    """True for Guide / career / Coach surfaces that must emit nothing."""
    if not isinstance(event_name, str):
        return False
    if event_name in CAREER_GRADE_EVENT_NAMES:
        return True
    lowered = event_name.lower()
    return any(marker in lowered for marker in ("career", "coach", "resume", "promotion"))


def _key_looks_forbidden(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _FORBIDDEN_PROPERTY_KEY_MARKERS)


def inspect_caller_properties(properties: object) -> str | None:
    """Return a wall reason if caller properties are unsafe, else None.

    Fail-closed: unknown shapes, free-text strings, usage-log fields, identity
    fields, and content-shaped keys refuse the whole event.
    """
    if properties is None:
        return None
    if not isinstance(properties, Mapping):
        return WALL_CONTENT
    for raw_key, value in properties.items():
        if not isinstance(raw_key, str) or not _SAFE_PROPERTY_KEY.fullmatch(raw_key):
            return WALL_CONTENT
        if raw_key in USAGE_PATTERN_PROPERTY_KEYS:
            return WALL_USAGE_PATTERN
        if raw_key in IDENTITY_PROPERTY_KEYS:
            return WALL_IDENTITY
        if _key_looks_forbidden(raw_key):
            return WALL_CONTENT
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1_000_000:
            continue
        if raw_key == "error_class" and isinstance(value, str) and _SAFE_ERROR_CLASS.fullmatch(value):
            continue
        if isinstance(value, str):
            return WALL_CONTENT
        return WALL_CONTENT
    return None


def serialized_payload_leaks(payload: Mapping[str, Any]) -> str | None:
    """Scan the exact JSON that would go on the wire."""
    try:
        serialized = json.dumps(payload, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return WALL_CONTENT
    if _EMAIL_LIKE.search(serialized):
        return WALL_IDENTITY
    for marker in _VAULT_FOLDER_MARKERS:
        if marker in serialized:
            return WALL_CONTENT
    if _PATH_LIKE.search(serialized):
        return WALL_CONTENT
    lowered = serialized.lower()
    if "transcript" in lowered or "conversation" in lowered:
        return WALL_CONTENT
    if "05-areas/career" in lowered or "career/" in lowered:
        return WALL_CAREER
    return None


def read_analytics_install_id(vault_root: Path) -> str | None:
    """Return the existing install-scoped id, or None. Never creates."""
    path = Path(vault_root) / ANALYTICS_INSTALL_ID_RELATIVE
    try:
        existing = path.read_text(encoding="utf-8").strip()
        return str(uuid.UUID(existing))
    except (FileNotFoundError, ValueError, UnicodeError, OSError):
        return None


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def get_or_create_analytics_install_id(vault_root: Path) -> str:
    """Install-scoped anonymous UUID. Not vault identity. Not a Record key."""
    existing = read_analytics_install_id(vault_root)
    if existing is not None:
        return existing
    install_id = str(uuid.uuid4())
    _atomic_write(Path(vault_root) / ANALYTICS_INSTALL_ID_RELATIVE, install_id + "\n")
    return install_id


def build_safe_track_payload(
    *,
    event_name: str,
    visitor_id: str,
    timestamp_ms: int,
    properties: Mapping[str, Any] | None,
    connection_test: bool = False,
    dex_version: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Build the wire payload or return (None, wall_reason)."""
    if event_name not in SAFE_ANALYTICS_EVENT_NAMES:
        return None, "invalid_event_name"
    if is_career_grade_event(event_name):
        return None, WALL_CAREER
    if connection_test:
        payload = {
            "type": "track",
            "event": event_name,
            "visitorId": "dex-analytics-test",
            "accountId": "dex-analytics-test",
            "timestamp": timestamp_ms,
            "properties": {"connection_test": True},
        }
        return payload, serialized_payload_leaks(payload)
    wall = inspect_caller_properties(properties)
    if wall is not None:
        return None, wall
    if not isinstance(visitor_id, str) or not visitor_id:
        return None, WALL_IDENTITY
    try:
        uuid.UUID(visitor_id)
    except ValueError:
        return None, WALL_IDENTITY
    event_props: dict[str, Any] = {}
    if dex_version:
        event_props["dex_version"] = dex_version
    if properties:
        for key, value in properties.items():
            if key == "dex_version":
                continue
            event_props[key] = value
    payload = {
        "type": "track",
        "event": event_name,
        "visitorId": visitor_id,
        "accountId": ANALYTICS_ACCOUNT_SCOPE,
        "timestamp": timestamp_ms,
        "properties": event_props,
    }
    return payload, serialized_payload_leaks(payload)


__all__ = [
    "ANALYTICS_ACCOUNT_SCOPE",
    "ANALYTICS_INSTALL_ID_RELATIVE",
    "CAREER_GRADE_EVENT_NAMES",
    "IDENTITY_PROPERTY_KEYS",
    "USAGE_PATTERN_PROPERTY_KEYS",
    "WALL_CAREER",
    "WALL_CONTENT",
    "WALL_IDENTITY",
    "WALL_USAGE_PATTERN",
    "build_safe_track_payload",
    "get_or_create_analytics_install_id",
    "inspect_caller_properties",
    "is_career_grade_event",
    "read_analytics_install_id",
    "serialized_payload_leaks",
]
