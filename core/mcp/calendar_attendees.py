"""Attendee RSVP helpers shared by Calendar MCP and EventKit formatting."""

from __future__ import annotations

from typing import Any, Mapping

_NON_RESPONDER_STATUSES = frozenset(
    {
        "",
        "pending",
        "unknown",
        "needsaction",
        "notresponded",
        "inprocess",
    }
)


def _folded_email(value: Any) -> str:
    return str(value or "").strip().casefold()


def _folded_status(attendee: Mapping[str, Any]) -> str:
    raw = attendee.get("status")
    if raw is None or raw == "":
        raw = attendee.get("responseStatus")
    normalized = str(raw or "").replace("_", " ").replace("-", " ").casefold()
    return "".join(normalized.split())


def attendee_is_organizer(
    attendee: Mapping[str, Any],
    organizer: Mapping[str, Any] | None = None,
) -> bool:
    """Whether this attendee organised the meeting.

    Calendar APIs disagree on the field: EventKit uses ``is_organizer``,
    Google Calendar uses ``organizer: true`` on the attendee and a separate
    ``organizer.email`` on the event. Any of those is enough.
    """
    if attendee.get("is_organizer") is True or attendee.get("organizer") is True:
        return True
    if not organizer:
        return False
    attendee_email = _folded_email(attendee.get("email"))
    organizer_email = _folded_email(
        organizer.get("email") or organizer.get("emailAddress")
    )
    return bool(attendee_email and organizer_email and attendee_email == organizer_email)


def attendee_is_non_responder(
    attendee: Mapping[str, Any],
    organizer: Mapping[str, Any] | None = None,
) -> bool:
    """Whether this invitee still owes an RSVP.

    The organiser — including the user when they organised the meeting — is
    never a non-responder. EventKit and Google often leave that person as
    Pending, Unknown, or needsAction.
    """
    if attendee_is_organizer(attendee, organizer):
        return False
    return _folded_status(attendee) in _NON_RESPONDER_STATUSES
