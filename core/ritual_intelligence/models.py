"""Canonical local models for Ritual Intelligence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def _normalize_email(value: str | None) -> str | None:
    return value.strip().lower() if value else None


@dataclass(slots=True)
class NormalizedAttendee:
    """Provider-neutral attendee shape for meeting occurrences."""

    name: str | None = None
    email: str | None = None
    status: str | None = None
    attendee_type: str | None = None
    is_organizer: bool = False

    def __post_init__(self) -> None:
        self.email = _normalize_email(self.email)

    @property
    def domain(self) -> str | None:
        if not self.email or "@" not in self.email:
            return None
        return self.email.split("@", 1)[1]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NormalizedCalendarEvent:
    """Provider-neutral meeting source model."""

    provider: str
    source_event_id: str
    title: str
    starts_at: datetime
    ends_at: datetime | None = None
    source_series_id: str | None = None
    calendar_id: str | None = None
    calendar_name: str | None = None
    state: str = "scheduled"
    attendees: list[NormalizedAttendee] = field(default_factory=list)
    location: str | None = None
    notes: str | None = None
    url: str | None = None
    all_day: bool = False
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["starts_at"] = self.starts_at.isoformat()
        data["ends_at"] = self.ends_at.isoformat() if self.ends_at else None
        return data


@dataclass(slots=True)
class RitualSuggestion:
    """Suggested recurring ritual candidate."""

    series_id: str
    series_key: str
    title: str
    occurrence_count: int
    recurring_pattern_score: float
    reason: str
    status: str = "suggested"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TranscriptArtifact:
    """Source-neutral transcript record."""

    transcript_id: str
    source: str
    source_transcript_id: str
    title: str
    started_at: datetime | None
    ended_at: datetime | None
    source_event_id: str | None = None
    attendees: list[NormalizedAttendee] = field(default_factory=list)
    raw_text: str | None = None
    raw_path: str | None = None
    summary_path: str | None = None
    summary_text: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat() if self.started_at else None
        data["ended_at"] = self.ended_at.isoformat() if self.ended_at else None
        return data
