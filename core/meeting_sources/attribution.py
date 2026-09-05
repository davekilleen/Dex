"""Resolve who was actually in a meeting, when the recorder could not say.

Some sources return a capture with no attendees and no title, because they
title and attribute from a calendar they cannot read. The summary still names
speakers, but those names are turns in a recording, not identified people. Left
alone that produces confident, plausible, invented commitments.

Dex already ships the resolver: ``match_capture_to_calendar`` matches a capture
to a calendar event by instant, tie-breaking on title and participant overlap,
and returns an allowlist of meeting identity. This module is the join between
that resolver and the meeting record, so an unattributed capture becomes an
attributed one wherever the calendar can prove it, and stays honestly
unattributed wherever it cannot.

**A match is proof; the absence of one is not disproof.** An unmatched capture
means the calendar could not confirm attendance, never that nobody was there.
The reason is carried through so the note can say which it was.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from core.meeting_capture_match import match_capture_to_calendar
from core.meeting_sources.record import Attendee, MeetingRecord


def record_as_capture(record: MeetingRecord) -> dict[str, Any]:
    """Present a record in the shape the shipped matcher expects.

    ``start_time`` is emitted as an ISO string carrying its offset. The matcher
    parses timestamps rather than accepting datetimes, and rejects any that does
    not declare a timezone rather than guessing an offset. Passing a datetime
    object here silently reads as "missing timezone" and every capture comes
    back unmatched, which looks exactly like a genuinely absent calendar entry.
    """
    capture: dict[str, Any] = {
        "start_time": record.start.isoformat(),
        "title": "" if record.extra.get("title_was_derived") else (record.title or ""),
    }
    if record.attendees:
        capture["attendees"] = [
            {"name": person.name, "email": person.email} for person in record.attendees
        ]
    return capture


def resolve(record: MeetingRecord, calendar_events: list[dict[str, Any]]) -> MeetingRecord:
    """Return the record with attendance filled in when the calendar proves it.

    A derived title is replaced by the real one on a match, because the calendar
    knows what the meeting was called and the summary only guessed.
    """
    if record.attribution_is_reliable:
        return record

    outcome = match_capture_to_calendar(record_as_capture(record), calendar_events or [])
    extra = dict(record.extra)
    extra["attribution_match"] = outcome.get("status")
    if outcome.get("status") != "matched":
        # Keep the reason. "No calendar event within five minutes" and "the
        # calendar could not be read" call for different responses from a user.
        extra["attribution_reason"] = outcome.get("reason")
        return replace(record, extra=extra)

    identity = outcome.get("identity") or {}
    attendees = tuple(
        Attendee(name=person.get("name"), email=person.get("email"))
        for person in identity.get("attendees") or []
        if person.get("name") or person.get("email")
    )
    if not attendees:
        # Matched an event that lists nobody. The match is real, the attendance
        # is still unknown, and claiming otherwise would be the invention this
        # module exists to prevent.
        extra["attribution_reason"] = "matched_event_has_no_attendees"
        return replace(record, extra=extra)

    extra["attribution_delta_seconds"] = outcome.get("delta_seconds")
    title = record.title
    if record.extra.get("title_was_derived") and identity.get("title"):
        title = identity["title"]
        extra["title_was_derived"] = False
        extra["title_from_calendar"] = True

    return replace(record, attendees=attendees, title=title, extra=extra)
