"""Resolve a human attendee name without using the email as the page name.

Calendar and recorder payloads often send the address in ``name`` (or omit
``name`` and put a real name in ``display_name`` / ``displayName``). A page
called ``jane.doe@example.com`` is worse than a missing name: later matching,
auto-link, and meeting prep treat it as the person.
"""

from __future__ import annotations

import re
from typing import Any

_EMAIL_LIKE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def looks_like_email(value: str | None) -> bool:
    if not value or not isinstance(value, str):
        return False
    return _EMAIL_LIKE.fullmatch(value.strip()) is not None


def prettify_email_local_part(email: str) -> str:
    """``jane.doe+tag@example.com`` → ``Jane Doe``."""
    local = email.split("@", 1)[0].split("+", 1)[0]
    parts = [part for part in re.split(r"[._-]+", local) if part]
    return " ".join(part[:1].upper() + part[1:].lower() for part in parts)


def display_name_from_fields(*candidates: Any, email: str | None = None) -> str:
    """Pick a real display name, then a prettified local-part fallback."""
    for raw in candidates:
        if not isinstance(raw, str):
            continue
        name = " ".join(raw.split()).strip()
        if name and not looks_like_email(name):
            return name
    cleaned_email = email.strip() if isinstance(email, str) else ""
    if cleaned_email and looks_like_email(cleaned_email):
        pretty = prettify_email_local_part(cleaned_email)
        if pretty:
            return pretty
    return ""


def attendee_note_label(name: str | None, email: str | None) -> str:
    """Frontmatter line: prefer ``Name <email>`` so routing keeps the address."""
    display = (name or "").strip()
    address = (email or "").strip()
    if (not display or looks_like_email(display)) and address and looks_like_email(address):
        display = prettify_email_local_part(address) or display
    if display and address and display.casefold() != address.casefold():
        return f"{display} <{address}>"
    return display or address
