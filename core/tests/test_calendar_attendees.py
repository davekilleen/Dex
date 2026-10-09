"""Organisers are never reported as people who have not accepted."""

from __future__ import annotations

from core.mcp.calendar_attendees import attendee_is_non_responder, attendee_is_organizer


def test_pending_invitee_is_a_non_responder() -> None:
    assert attendee_is_non_responder(
        {"name": "Pat Customer", "email": "pat@example.com", "status": "Pending"}
    )


def test_google_needs_action_invitee_is_a_non_responder() -> None:
    assert attendee_is_non_responder(
        {
            "name": "Pat Customer",
            "email": "pat@example.com",
            "responseStatus": "needsAction",
        }
    )


def test_eventkit_organizer_flag_is_never_a_non_responder() -> None:
    attendee = {
        "name": "Morgan Host",
        "email": "host@example.com",
        "status": "Pending",
        "is_organizer": True,
        "is_current_user": True,
    }
    assert attendee_is_organizer(attendee) is True
    assert attendee_is_non_responder(attendee) is False


def test_google_organizer_flag_is_never_a_non_responder() -> None:
    attendee = {
        "email": "host@example.com",
        "responseStatus": "needsAction",
        "organizer": True,
        "self": True,
    }
    assert attendee_is_non_responder(attendee) is False


def test_matching_event_organizer_email_is_never_a_non_responder() -> None:
    attendee = {
        "name": "Morgan Host",
        "email": "host@example.com",
        "status": "Unknown",
        "is_organizer": False,
    }
    organizer = {"email": "host@example.com"}
    assert attendee_is_organizer(attendee, organizer) is True
    assert attendee_is_non_responder(attendee, organizer) is False


def test_accepted_invitee_is_not_a_non_responder() -> None:
    assert attendee_is_non_responder(
        {"email": "pat@example.com", "status": "Accepted"}
    ) is False
