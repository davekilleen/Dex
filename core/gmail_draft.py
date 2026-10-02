"""Keep Gmail draft identifiers on one format.

Gmail returns two different ids on a draft:

- ``draft.id`` / ``draftId`` — the drafts resource id. Use this for get,
  update, send, and delete draft calls.
- ``message.id`` / ``threadId`` — mailbox message ids. Never pass these to
  a draft tool.

Callers also see ``drafts/{id}`` resource names and the older ``r-{digits}``
web form. Both still name the draft resource. A 16-character hex string is a
message id, not a draft id.
"""

from __future__ import annotations

import re
from typing import Any

_RESOURCE_PREFIX = re.compile(r"^drafts/", re.IGNORECASE)
_DRAFT_R_FORM = re.compile(r"^r-\d+$")
_MESSAGE_HEX = re.compile(r"^[0-9a-f]{16}$", re.IGNORECASE)


class GmailDraftIdError(ValueError):
    """Raised when a value is a message id or is not a draft id."""


def classify_gmail_id(value: str) -> str:
    """Return ``draft``, ``message``, or ``unknown`` for a raw identifier."""
    if not isinstance(value, str):
        return "unknown"
    text = value.strip()
    if not text:
        return "unknown"
    stripped = _RESOURCE_PREFIX.sub("", text)
    if _DRAFT_R_FORM.fullmatch(stripped):
        return "draft"
    if _MESSAGE_HEX.fullmatch(stripped):
        return "message"
    if stripped:
        return "unknown"
    return "unknown"


def normalize_gmail_draft_id(value: str) -> str:
    """Return the drafts resource id, or raise if this is a message id."""
    if not isinstance(value, str) or not value.strip():
        raise GmailDraftIdError("Gmail draft id is missing.")
    text = value.strip()
    stripped = _RESOURCE_PREFIX.sub("", text)
    if not stripped:
        raise GmailDraftIdError("Gmail draft id is missing.")
    if classify_gmail_id(stripped) == "message":
        raise GmailDraftIdError(
            "That value is a Gmail message id, not a draft id."
        )
    return stripped


def draft_id_from_payload(payload: Any) -> str:
    """Pick the drafts resource id from a Gmail draft payload.

    Prefers an explicit ``draft_id`` / ``draftId`` / nested ``draft.id`` over a
    bare top-level ``id``. A top-level ``id`` counts only when the payload is a
    drafts resource (nested ``message``, or ``kind`` names a draft).
    ``message.id`` and ``threadId`` are never used.
    """
    if not isinstance(payload, dict):
        raise GmailDraftIdError("Gmail draft payload must be an object.")

    for key in ("draft_id", "draftId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_gmail_draft_id(value)

    nested = payload.get("draft")
    if isinstance(nested, dict):
        nested_id = nested.get("id")
        if isinstance(nested_id, str) and nested_id.strip():
            return normalize_gmail_draft_id(nested_id)

    top_id = payload.get("id")
    kind = str(payload.get("kind") or "").casefold()
    is_draft_resource = isinstance(payload.get("message"), dict) or "draft" in kind
    if is_draft_resource and isinstance(top_id, str) and top_id.strip():
        return normalize_gmail_draft_id(top_id)

    raise GmailDraftIdError("Gmail draft payload has no draft id.")
