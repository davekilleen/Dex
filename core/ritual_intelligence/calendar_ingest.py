"""Calendar source ingestion for Ritual Intelligence."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

import yaml

from core.paths import LEGACY_MEETINGS_DIR, TRACKED_MEETINGS_DIR, USER_PROFILE_FILE

from .models import NormalizedAttendee, NormalizedCalendarEvent


class CalendarIngestError(RuntimeError):
    """Raised when the configured calendar cannot be ingested."""


def _load_profile() -> dict:
    if not USER_PROFILE_FILE.exists():
        return {}
    with USER_PROFILE_FILE.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def get_configured_work_calendar() -> str:
    profile = _load_profile()
    return profile.get("calendar", {}).get("work_calendar") or "Work"


def get_internal_domains() -> set[str]:
    profile = _load_profile()
    raw = profile.get("email_domain", "") or ""
    domains = {part.strip().lower() for part in raw.split(",") if part.strip()}
    work_email = (profile.get("work_email") or "").strip().lower()
    if work_email and "@" in work_email:
        domains.add(work_email.split("@", 1)[1])
    return domains


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise CalendarIngestError(f"Unsupported calendar datetime value: {value}") from exc


def normalize_events(raw_events: Iterable[dict]) -> list[NormalizedCalendarEvent]:
    events: list[NormalizedCalendarEvent] = []
    for raw in raw_events:
        attendees = [
            NormalizedAttendee(
                name=entry.get("name"),
                email=entry.get("email"),
                status=entry.get("status"),
                attendee_type=entry.get("type"),
                is_organizer=bool(entry.get("is_organizer")),
            )
            for entry in raw.get("attendees", [])
        ]
        starts_at = _parse_datetime(raw.get("start"))
        if starts_at is None:
            raise CalendarIngestError(f"Calendar event is missing a start time: {raw}")
        event = NormalizedCalendarEvent(
            provider=raw.get("provider", "eventkit"),
            source_event_id=raw.get("provider_event_id") or raw.get("source_event_id") or "",
            source_series_id=raw.get("provider_series_id") or raw.get("source_series_id"),
            title=(raw.get("title") or "").strip() or "Untitled Meeting",
            starts_at=starts_at,
            ends_at=_parse_datetime(raw.get("end")),
            calendar_id=raw.get("calendar_identifier"),
            calendar_name=raw.get("calendar_name"),
            state=raw.get("state", "scheduled"),
            attendees=attendees,
            location=raw.get("location"),
            notes=raw.get("notes"),
            url=raw.get("url"),
            all_day=bool(raw.get("all_day")),
            raw_payload=raw,
        )
        if not event.source_event_id:
            # Fallback for provider-neutral callers that do not have source ids yet.
            event.source_event_id = f"{event.title}:{event.starts_at.isoformat()}"
        events.append(event)
    return events


def load_calendar_events(
    *,
    start_offset_days: int = -28,
    end_offset_days: int = 14,
    calendar_name: str | None = None,
) -> list[NormalizedCalendarEvent]:
    """Load normalized events from the current EventKit adapter."""
    selected_calendar = calendar_name or get_configured_work_calendar()
    try:
        from core.mcp.scripts import calendar_eventkit
    except Exception as exc:  # pragma: no cover - environment-specific
        raise CalendarIngestError("The local calendar adapter is unavailable.") from exc

    if not hasattr(calendar_eventkit, "get_events_data"):
        raise CalendarIngestError("The calendar adapter does not expose get_events_data().")

    raw_events = calendar_eventkit.get_events_data(
        selected_calendar,
        start_offset_days,
        end_offset_days,
        with_attendees=True,
    )
    return normalize_events(raw_events)


def candidate_manual_note_roots(_vault_root: Path) -> list[Path]:
    """Read-only note locations that may already contain useful meeting history."""
    return [
        TRACKED_MEETINGS_DIR,
        LEGACY_MEETINGS_DIR,
    ]
