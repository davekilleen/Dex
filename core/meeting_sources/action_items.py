"""Route meeting action items to For Me vs For Others.

A line that starts with ``@Name`` or ``@[Name]:`` is assigned to that person.
Those belong under For Others so ``/process-meetings`` does not turn someone
else's promise into a task for the vault owner.
"""

from __future__ import annotations

import re

# `@Sarah: send the deck` / `@[Sarah Chen]: send the deck` / `@Sarah send`
_ASSIGNED_WITH_COLON = re.compile(r"^@\[?(?P<name>[^\]\n]+?)\]?\s*:")
_ASSIGNED_BARE = re.compile(r"^@(?P<name>[^\s@:[]+)")


def assigned_person(item: str) -> str | None:
    text = item.strip()
    match = _ASSIGNED_WITH_COLON.match(text) or _ASSIGNED_BARE.match(text)
    if not match:
        return None
    name = match.group("name").strip()
    return name or None


def action_item_bucket(item: str, owner_names: set[str] | None = None) -> str:
    """Return ``me`` or ``others`` for one action-item line."""
    assigned = assigned_person(item)
    if not assigned:
        return "me"
    owners = {value.casefold() for value in (owner_names or set()) if value}
    folded = assigned.casefold()
    if folded in owners:
        return "me"
    for owner in owners:
        first = owner.split()[0] if owner else ""
        if first and folded == first:
            return "me"
    return "others"
