"""Occurrence reconciliation and capture-mode classification."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterable
from datetime import datetime

from .db import utc_now
from .models import NormalizedAttendee, NormalizedCalendarEvent

SERVICE_ACCOUNT_PATTERNS = (
    "room",
    "resource",
    "group",
    "noreply",
)


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _is_service_account(attendee: NormalizedAttendee) -> bool:
    email = attendee.email or ""
    local_part = email.split("@", 1)[0] if "@" in email else email
    lowered = f"{attendee.name or ''} {local_part}".lower()
    return any(pattern in lowered for pattern in SERVICE_ACCOUNT_PATTERNS)


def has_external_attendee(event: NormalizedCalendarEvent, internal_domains: set[str]) -> bool:
    for attendee in event.attendees:
        if _is_service_account(attendee):
            continue
        if attendee.domain and attendee.domain not in internal_domains:
            return True
    return False


def event_has_other_attendees(event: NormalizedCalendarEvent) -> bool:
    return any(not _is_service_account(attendee) for attendee in event.attendees)


def is_declined_event(event: NormalizedCalendarEvent) -> bool:
    for attendee in event.attendees:
        if attendee.status and attendee.status.lower() == "declined" and attendee.is_organizer:
            return True
    return False


def should_include_event(event: NormalizedCalendarEvent, internal_domains: set[str]) -> bool:
    if event.all_day:
        return False
    if is_declined_event(event):
        return False
    if not event_has_other_attendees(event):
        return False
    if event.ends_at and (event.ends_at - event.starts_at).total_seconds() < 15 * 60:
        return has_external_attendee(event, internal_domains)
    return True


def build_series_key(event: NormalizedCalendarEvent) -> str:
    if event.source_series_id:
        return f"{event.provider}:{event.source_series_id}"
    participants = sorted(
        attendee.email or attendee.name or ""
        for attendee in event.attendees
        if not _is_service_account(attendee)
    )
    digest = hashlib.sha1(
        f"{event.provider}|{_normalize_title(event.title)}|{'|'.join(participants)}".encode("utf-8")
    ).hexdigest()
    return f"{event.provider}:series:{digest}"


def build_occurrence_id(event: NormalizedCalendarEvent) -> str:
    basis = f"{event.provider}|{event.source_event_id}|{event.starts_at.isoformat()}"
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()
    return f"occ_{digest[:16]}"


def _contact_id(attendee: NormalizedAttendee) -> str:
    basis = attendee.email or attendee.name or str(uuid.uuid4())
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()
    return f"ctc_{digest[:16]}"


def classify_capture_mode(event: NormalizedCalendarEvent, internal_domains: set[str]) -> str:
    return "tracked meeting" if has_external_attendee(event, internal_domains) else "activity log"


def reconcile_events(
    conn,
    events: Iterable[NormalizedCalendarEvent],
    *,
    internal_domains: set[str],
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> dict[str, int]:
    """Reconcile a batch of normalized events onto canonical occurrences."""
    now = utc_now()
    processed: list[NormalizedCalendarEvent] = [event for event in events if should_include_event(event, internal_domains)]
    seen_ids = {event.source_event_id for event in processed}

    min_start = window_start.isoformat() if window_start else min((event.starts_at.isoformat() for event in processed), default=None)
    max_start = window_end.isoformat() if window_end else max((event.starts_at.isoformat() for event in processed), default=None)

    created = 0
    updated = 0

    for event in processed:
        occurrence_id = build_occurrence_id(event)
        series_key = build_series_key(event)
        capture_mode = classify_capture_mode(event, internal_domains)

        existing = conn.execute(
            "SELECT occurrence_id FROM source_events WHERE provider = ? AND source_event_id = ?",
            (event.provider, event.source_event_id),
        ).fetchone()

        if existing:
            occurrence_id = existing["occurrence_id"]
            updated += 1
        else:
            created += 1

        conn.execute(
            """
            INSERT INTO occurrences (
              id, title, starts_at, ends_at, state, capture_mode, provider,
              source_series_id, series_key, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title = excluded.title,
              starts_at = excluded.starts_at,
              ends_at = excluded.ends_at,
              state = excluded.state,
              capture_mode = excluded.capture_mode,
              source_series_id = excluded.source_series_id,
              series_key = excluded.series_key,
              updated_at = excluded.updated_at
            """,
            (
                occurrence_id,
                event.title,
                event.starts_at.isoformat(),
                event.ends_at.isoformat() if event.ends_at else None,
                event.state,
                capture_mode,
                event.provider,
                event.source_series_id,
                series_key,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO source_events (
              provider, source_event_id, occurrence_id, source_series_id, calendar_id, last_seen_at, raw_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, source_event_id) DO UPDATE SET
              occurrence_id = excluded.occurrence_id,
              source_series_id = excluded.source_series_id,
              calendar_id = excluded.calendar_id,
              last_seen_at = excluded.last_seen_at,
              raw_payload = excluded.raw_payload
            """,
            (
                event.provider,
                event.source_event_id,
                occurrence_id,
                event.source_series_id,
                event.calendar_id,
                now,
                json.dumps(event.as_dict(), sort_keys=True),
            ),
        )

        conn.execute("DELETE FROM occurrence_contacts WHERE occurrence_id = ?", (occurrence_id,))
        for attendee in event.attendees:
            if _is_service_account(attendee):
                continue
            contact_id = _contact_id(attendee)
            conn.execute(
                """
                INSERT INTO contacts (
                  id, name, email, normalized_name, domain, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                  name = COALESCE(excluded.name, contacts.name),
                  normalized_name = COALESCE(excluded.normalized_name, contacts.normalized_name),
                  domain = COALESCE(excluded.domain, contacts.domain),
                  updated_at = excluded.updated_at
                """,
                (
                    contact_id,
                    attendee.name,
                    attendee.email,
                    (attendee.name or "").strip().lower() or None,
                    attendee.domain,
                    now,
                    now,
                ),
            )
            resolved_contact = conn.execute(
                "SELECT id FROM contacts WHERE email = ? OR (email IS NULL AND id = ?)",
                (attendee.email, contact_id),
            ).fetchone()
            final_contact_id = resolved_contact["id"] if resolved_contact else contact_id
            conn.execute(
                """
                INSERT OR REPLACE INTO occurrence_contacts (
                  occurrence_id, contact_id, attendee_name, attendee_email, attendee_type, is_external
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    occurrence_id,
                    final_contact_id,
                    attendee.name,
                    attendee.email,
                    attendee.attendee_type,
                    0 if attendee.domain in internal_domains else 1,
                ),
            )

    if min_start and max_start:
        rows = conn.execute(
            """
            SELECT se.provider, se.source_event_id, se.occurrence_id
            FROM source_events se
            JOIN occurrences o ON o.id = se.occurrence_id
            WHERE se.provider = ?
              AND o.starts_at BETWEEN ? AND ?
              AND o.state != 'cancelled'
            """,
            ((processed[0].provider if processed else "eventkit"), min_start, max_start),
        ).fetchall()
        for row in rows:
            if row["source_event_id"] in seen_ids:
                continue
            conn.execute(
                "UPDATE occurrences SET state = 'cancelled', updated_at = ? WHERE id = ?",
                (now, row["occurrence_id"]),
            )

    return {"created": created, "updated": updated, "total": len(processed)}
