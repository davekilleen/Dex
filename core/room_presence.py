"""Local room-presence card: photo, title, and company.

This is who a beta person is in a shared room. It is not a career product,
not a live network, and not the Mac Dex app. Folders never grant audience —
another person sees this card only after an explicit yes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PROFILE_RELATIVE = "System/user-profile.yaml"
PRESENCE_KEY = "room_presence"
CARD_FIELDS = ("photo", "title", "company")
CONSENT_YES = "yes"
_ROOM_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_PHOTO_SUFFIXES = (".gif", ".jpeg", ".jpg", ".png", ".webp")


class RoomPresenceError(ValueError):
    """Raised when a room-presence field or room id is not saveable."""


def normalize_room_id(room_id: object) -> str:
    """Return a short room id, or raise if it looks like a folder path."""
    if not isinstance(room_id, str) or _ROOM_ID.fullmatch(room_id) is None:
        raise RoomPresenceError(
            "a shared room needs a short name like design-sync, not a folder path"
        )
    return room_id


def normalize_text(value: object, *, field: str) -> str:
    """Return a trimmed string. Missing or blank stays empty — never a name."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise RoomPresenceError(f"{field} must be text")
    return value.strip()


def normalize_photo(value: object) -> str:
    """Return a vault-relative photo path, or empty. Empty stays empty."""
    text = normalize_text(value, field="photo")
    if not text:
        return ""
    candidate = Path(text)
    if candidate.is_absolute() or "\\" in text or ".." in candidate.parts:
        raise RoomPresenceError("photo must be a file inside this Dex folder")
    if candidate.suffix.lower() not in _PHOTO_SUFFIXES:
        raise RoomPresenceError("photo must be a .jpg, .jpeg, .png, .webp, or .gif path")
    return candidate.as_posix()


def empty_card() -> dict[str, str]:
    """Return the three card fields as empty strings, not placeholder names."""
    return {field: "" for field in CARD_FIELDS}


def card_from_mapping(payload: Mapping[str, Any] | None) -> dict[str, str]:
    """Read photo, title, and company only. Never invent a name from elsewhere."""
    card = empty_card()
    if not isinstance(payload, Mapping):
        return card
    card["photo"] = normalize_photo(payload.get("photo"))
    card["title"] = normalize_text(payload.get("title"), field="title")
    card["company"] = normalize_text(payload.get("company"), field="company")
    return card


def presence_block(profile: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the local presence block, ignoring career and folder state."""
    if not isinstance(profile, Mapping):
        return {"card": empty_card(), "shared_rooms": {}}
    raw = profile.get(PRESENCE_KEY)
    if not isinstance(raw, Mapping):
        return {"card": empty_card(), "shared_rooms": {}}
    shared = raw.get("shared_rooms")
    rooms: dict[str, dict[str, bool]] = {}
    if isinstance(shared, Mapping):
        for room_id, state in shared.items():
            if not isinstance(room_id, str) or _ROOM_ID.fullmatch(room_id) is None:
                continue
            if isinstance(state, Mapping) and state.get("consented") is True:
                rooms[room_id] = {"consented": True}
    return {"card": card_from_mapping(raw), "shared_rooms": rooms}


def local_card(profile: Mapping[str, Any] | None) -> dict[str, str]:
    """Return the locally saved card. Profile name is never used as a stand-in."""
    return presence_block(profile)["card"]


def room_is_shared(profile: Mapping[str, Any] | None, room_id: str) -> bool:
    """Return whether this room was shared with an explicit yes."""
    block = presence_block(profile)
    return block["shared_rooms"].get(normalize_room_id(room_id), {}).get("consented") is True


def room_view(profile: Mapping[str, Any] | None, room_id: str) -> dict[str, Any]:
    """Return what another person in this room may see.

    Unshared rooms return no card. Shared rooms return photo, title, and
    company only — never a folder tree, never a guessed name.
    """
    normalized = normalize_room_id(room_id)
    if not room_is_shared(profile, normalized):
        return {"room": normalized, "shared": False, "card": None}
    return {"room": normalized, "shared": True, "card": local_card(profile)}


def apply_local_fields(
    profile: Mapping[str, Any],
    *,
    photo: object = None,
    title: object = None,
    company: object = None,
) -> dict[str, Any]:
    """Write photo, title, and company locally without granting any audience."""
    if not isinstance(profile, Mapping):
        raise RoomPresenceError("user profile must be a YAML object")
    updated = dict(profile)
    current = presence_block(profile)
    card = dict(current["card"])
    if photo is not None:
        card["photo"] = normalize_photo(photo)
    if title is not None:
        card["title"] = normalize_text(title, field="title")
    if company is not None:
        card["company"] = normalize_text(company, field="company")
    updated[PRESENCE_KEY] = {
        **card,
        "shared_rooms": current["shared_rooms"],
    }
    return updated


def apply_share(profile: Mapping[str, Any], room_id: str) -> dict[str, Any]:
    """Record that this room may see the card. Callers must already have a yes."""
    if not isinstance(profile, Mapping):
        raise RoomPresenceError("user profile must be a YAML object")
    normalized = normalize_room_id(room_id)
    updated = dict(profile)
    current = presence_block(profile)
    rooms = dict(current["shared_rooms"])
    rooms[normalized] = {"consented": True}
    updated[PRESENCE_KEY] = {
        **current["card"],
        "shared_rooms": rooms,
    }
    return updated


def require_yes(consent: object) -> None:
    """Sharing still requires a yes. Folders, tokens, and other words do not count."""
    if not isinstance(consent, str) or consent.strip() != CONSENT_YES:
        raise RoomPresenceError("sharing still requires a yes")
